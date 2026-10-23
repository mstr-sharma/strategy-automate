"""How each kind of database Strategy connects to describes itself: the catalog views that list tables, columns and
their comments, row counts the database keeps, declared primary and foreign keys, and column statistics. Metadata only:
every statement here reads a database's own catalog, never a table. Strategy's gateway refuses "UNION [ALL] SELECT" in
source SQL (HTTP 403), so union branches are always parenthesized.

A source's Strategy type ("Microsoft SQL Server 2019/2022", "Google BigQuery Native", "Amazon Aurora PostgreSQL
Compatible") maps to a flavor; a flavor knows its SQL. Sources with no catalog we can read (NoSQL stores, SaaS and file
connectors, cube providers) return None everywhere, and callers fall back to Strategy's own catalog API.

Strategy returns at most 1,000 rows per source query, so catalog statements are paged (`paged`), and where the
database can aggregate, a table's columns come back joined in one row ("tables" queries) so a whole database fits in a
few pages; elsewhere one row per column ("columns" queries).
"""
from __future__ import annotations

import re

PAGE = 1000
SEP = "|"

# Strategy type name → flavor (first match wins; order matters: "Aurora PostgreSQL" before "Aurora MySQL")
FLAVORS: list[tuple[str, str]] = [
    (r"snowflake", "snowflake"),
    (r"redshift|actian matrix|par_accel", "redshift"),
    (r"postgres|alloydb|greenplum|yellowbrick|cockroach|timescale", "postgres"),
    (r"synapse|parallel data warehouse|\bpdw\b", "synapse"),          # no OFFSET … FETCH: pages by ROW_NUMBER
    (r"fabric (warehouse|lakehouse)|sql server|azure sql", "sqlserver"),
    (r"mysql|mariadb|aurora mysql|singlestore|memsql|infobright|starrocks|doris|tidb|mongodb bi", "mysql"),
    (r"clickhouse", "clickhouse"),
    (r"databricks|spark sql|unity", "databricks"),
    (r"bigquery", "bigquery"),
    (r"oracle(?! (essbase|cx|eloqua))", "oracle"),
    (r"db2 for i\b", "db2i"),
    (r"db2 for z", "db2z"),
    (r"\bdb2\b|integrated analytics system", "db2"),
    (r"teradata", "teradata"),
    (r"sap hana(?! 2\.0 sps4)|datasphere", "hana"),
    (r"vertica", "vertica"),
    (r"trino|presto|starburst|athena", "trino"),
    (r"exasol|exasolution", "exasol"),
    (r"netezza", "netezza"),
    (r"dremio", "dremio"),
]


def flavor(dbms: str | None) -> str | None:
    d = (dbms or "").lower()
    for pattern, f in FLAVORS:
        if re.search(pattern, d):
            return f
    return None


def lit(s: str) -> str:
    if re.search(r"[\\\x00-\x1f\x7f]", str(s)):
        raise ValueError("SQL literals cannot contain backslashes or control characters")
    return "'" + str(s).replace("'", "''") + "'"


def safe_name(name: str | None) -> bool:
    """a schema or dataset name the catalog SQL may carry: no backslash (an escape character in MySQL, Snowflake,
    Databricks, ClickHouse and BigQuery strings), no control characters, no backtick. Anything else is read through
    Strategy's catalog API instead, never pasted into SQL."""
    return name is None or (bool(name) and not re.search(r"[\\`\x00-\x1f]", name) and len(name) <= 256)


SKIP = "('INFORMATION_SCHEMA','information_schema','pg_catalog','sys','mysql','performance_schema','SYS','SYSTEM','system','INFORMATION_SCHEMA_ACCESS')"


def catalog_queries(dbms: str, schema: str | None) -> list[tuple[str, str]]:
    """[(kind, sql)] to try in order: kind "tables" returns s, t, n, tc, cols, cc (one row per table, columns and their
    comments joined by SEP); kind "columns" returns s, t, c, cc, tc, n (one row per column). schema None = every schema
    the source can list in one statement (where the flavor can't, the list is empty: list schemas, then ask per schema)."""
    f = flavor(dbms)
    one = schema is not None
    q: list[tuple[str, str]] = []
    if not safe_name(schema):
        return []
    if f == "snowflake":
        w = f" AND c.TABLE_SCHEMA={lit(schema)}" if one else ""
        q.append(("tables", "SELECT c.TABLE_SCHEMA AS s, c.TABLE_NAME AS t, MAX(tb.ROW_COUNT) AS n, MAX(tb.COMMENT) AS tc, "  # nosec B608  # catalog names pass safe_name/lit; paging wraps generated SQL with bounded integers
                            f"LISTAGG(c.COLUMN_NAME, '{SEP}') WITHIN GROUP (ORDER BY c.ORDINAL_POSITION) AS cols, "
                            f"LEFT(LISTAGG(COALESCE(c.COMMENT, ''), '{SEP}') WITHIN GROUP (ORDER BY c.ORDINAL_POSITION), 8000) AS cc "
                            "FROM INFORMATION_SCHEMA.COLUMNS c JOIN INFORMATION_SCHEMA.TABLES tb ON tb.TABLE_SCHEMA=c.TABLE_SCHEMA AND tb.TABLE_NAME=c.TABLE_NAME "
                            f"WHERE c.TABLE_SCHEMA NOT IN {SKIP}{w} GROUP BY 1, 2 ORDER BY 1, 2"))
    elif f == "postgres":
        w = f" AND c.table_schema={lit(schema)}" if one else ""
        q.append(("tables", "SELECT c.table_schema AS s, c.table_name AS t, MAX(NULLIF(cl.reltuples, -1))::bigint AS n, MAX(obj_description(cl.oid, 'pg_class')) AS tc, "  # nosec B608  # catalog names pass safe_name/lit; paging wraps generated SQL with bounded integers
                            f"string_agg(c.column_name, '{SEP}' ORDER BY c.ordinal_position) AS cols, "
                            f"LEFT(string_agg(COALESCE(col_description(cl.oid, c.ordinal_position::int), ''), '{SEP}' ORDER BY c.ordinal_position), 8000) AS cc "
                            "FROM information_schema.columns c JOIN pg_namespace ns ON ns.nspname=c.table_schema "
                            "JOIN pg_class cl ON cl.relnamespace=ns.oid AND cl.relname=c.table_name "
                            f"WHERE c.table_schema NOT IN {SKIP}{w} GROUP BY 1, 2 ORDER BY 1, 2"))
    elif f == "redshift":
        w = f" AND c.table_schema={lit(schema)}" if one else ""
        q.append(("columns", "SELECT c.table_schema AS s, c.table_name AS t, c.column_name AS c, c.remarks AS cc, NULL AS tc, NULL AS n "  # nosec B608  # catalog names pass safe_name/lit; paging wraps generated SQL with bounded integers
                             f"FROM svv_columns c WHERE c.table_schema NOT IN {SKIP}{w} ORDER BY 1, 2, c.ordinal_position"))
    elif f in ("sqlserver", "synapse"):
        w = f" AND c.TABLE_SCHEMA={lit(schema)}" if one else ""
        # descriptions are MS_Description extended properties; row counts from sys.partitions (heap or clustered index)
        q.append(("tables", "SELECT c.TABLE_SCHEMA AS s, c.TABLE_NAME AS t, "
                            + ("NULL AS n, " if f == "synapse" else
                               "(SELECT SUM(p.rows) FROM sys.partitions p WHERE p.object_id=OBJECT_ID(QUOTENAME(c.TABLE_SCHEMA)+'.'+QUOTENAME(c.TABLE_NAME)) AND p.index_id IN (0, 1)) AS n, ") +
                            "CAST((SELECT TOP 1 ep.value FROM sys.extended_properties ep WHERE ep.major_id=OBJECT_ID(QUOTENAME(c.TABLE_SCHEMA)+'.'+QUOTENAME(c.TABLE_NAME)) "  # nosec B608  # catalog names pass safe_name/lit; paging wraps generated SQL with bounded integers
                            "AND ep.minor_id=0 AND ep.name='MS_Description') AS NVARCHAR(4000)) AS tc, "
                            f"STRING_AGG(CAST(c.COLUMN_NAME AS NVARCHAR(MAX)), '{SEP}') WITHIN GROUP (ORDER BY c.ORDINAL_POSITION) AS cols, NULL AS cc "
                            f"FROM INFORMATION_SCHEMA.COLUMNS c WHERE c.TABLE_SCHEMA NOT IN {SKIP}{w} GROUP BY c.TABLE_SCHEMA, c.TABLE_NAME ORDER BY 1, 2"))
        # SQL Server before 2017 has no STRING_AGG: one row per column
        q.append(("columns", "SELECT c.TABLE_SCHEMA AS s, c.TABLE_NAME AS t, c.COLUMN_NAME AS c, NULL AS cc, NULL AS tc, NULL AS n "  # nosec B608  # catalog names pass safe_name/lit; paging wraps generated SQL with bounded integers
                             f"FROM INFORMATION_SCHEMA.COLUMNS c WHERE c.TABLE_SCHEMA NOT IN {SKIP}{w} ORDER BY 1, 2, c.ORDINAL_POSITION"))
    elif f == "mysql":
        w = f" AND c.TABLE_SCHEMA={lit(schema)}" if one else ""
        q.append(("tables", "SELECT /*+ SET_VAR(group_concat_max_len=1048576) */ c.TABLE_SCHEMA AS s, c.TABLE_NAME AS t, MAX(tb.TABLE_ROWS) AS n, MAX(tb.TABLE_COMMENT) AS tc, COUNT(*) AS k, "  # nosec B608  # catalog names pass safe_name/lit; paging wraps generated SQL with bounded integers
                            f"GROUP_CONCAT(c.COLUMN_NAME ORDER BY c.ORDINAL_POSITION SEPARATOR '{SEP}') AS cols, "
                            f"LEFT(GROUP_CONCAT(COALESCE(c.COLUMN_COMMENT, '') ORDER BY c.ORDINAL_POSITION SEPARATOR '{SEP}'), 8000) AS cc "
                            "FROM INFORMATION_SCHEMA.COLUMNS c JOIN INFORMATION_SCHEMA.TABLES tb ON tb.TABLE_SCHEMA=c.TABLE_SCHEMA AND tb.TABLE_NAME=c.TABLE_NAME "
                            f"WHERE c.TABLE_SCHEMA NOT IN {SKIP}{w} GROUP BY 1, 2 ORDER BY 1, 2"))
        q.append(("columns", "SELECT c.TABLE_SCHEMA AS s, c.TABLE_NAME AS t, c.COLUMN_NAME AS c, c.COLUMN_COMMENT AS cc, NULL AS tc, NULL AS n "  # nosec B608  # catalog names pass safe_name/lit; paging wraps generated SQL with bounded integers
                             f"FROM INFORMATION_SCHEMA.COLUMNS c WHERE c.TABLE_SCHEMA NOT IN {SKIP}{w} ORDER BY 1, 2, c.ORDINAL_POSITION"))
    elif f == "clickhouse":
        w = f" AND c.database={lit(schema)}" if one else ""
        q.append(("tables", "SELECT c.database AS s, c.table AS t, any(tb.total_rows) AS n, any(tb.comment) AS tc, "  # nosec B608  # catalog names pass safe_name/lit; paging wraps generated SQL with bounded integers
                            f"arrayStringConcat(arrayMap(x -> x.2, arraySort(groupArray((c.position, c.name)))), '{SEP}') AS cols, "
                            f"arrayStringConcat(arrayMap(x -> x.2, arraySort(groupArray((c.position, c.comment)))), '{SEP}') AS cc, count() AS k "
                            "FROM system.columns c LEFT JOIN system.tables tb ON tb.database=c.database AND tb.name=c.table "
                            f"WHERE c.database NOT IN ('system','INFORMATION_SCHEMA','information_schema'){w} GROUP BY s, t ORDER BY s, t"))
    elif f == "databricks":
        # Unity Catalog's information_schema (the connection's current catalog); hive_metastore has none (names only)
        w = f" AND c.table_schema={lit(schema)}" if one else ""
        q.append(("tables", "SELECT c.table_schema AS s, c.table_name AS t, NULL AS n, MAX(tb.comment) AS tc, "  # nosec B608  # catalog names pass safe_name/lit; paging wraps generated SQL with bounded integers
                            f"concat_ws('{SEP}', transform(array_sort(collect_list(named_struct('p', c.ordinal_position, 'v', c.column_name))), x -> x.v)) AS cols, "
                            f"concat_ws('{SEP}', transform(array_sort(collect_list(named_struct('p', c.ordinal_position, 'v', coalesce(c.comment, '')))), x -> x.v)) AS cc "
                            "FROM information_schema.columns c LEFT JOIN information_schema.tables tb ON tb.table_schema=c.table_schema AND tb.table_name=c.table_name "
                            f"WHERE c.table_schema <> 'information_schema'{w} GROUP BY 1, 2 ORDER BY 1, 2"))
    elif f == "bigquery":
        if not one:
            return []                          # one dataset at a time (a region-wide view needs the region): list, then ask
        ds = "`" + schema.replace("`", "") + "`"
        q.append(("tables", f"SELECT c.table_schema AS s, c.table_name AS t, NULL AS n, MAX(TRIM(o.option_value, '\"')) AS tc, "  # nosec B608  # catalog names pass safe_name/lit; paging wraps generated SQL with bounded integers
                            f"STRING_AGG(c.column_name, '{SEP}' ORDER BY c.ordinal_position) AS cols, "
                            f"STRING_AGG(COALESCE(p.description, ''), '{SEP}' ORDER BY c.ordinal_position) AS cc "
                            f"FROM {ds}.INFORMATION_SCHEMA.COLUMNS c "
                            f"LEFT JOIN {ds}.INFORMATION_SCHEMA.COLUMN_FIELD_PATHS p ON p.table_name=c.table_name AND p.column_name=c.column_name AND p.field_path=c.column_name "
                            f"LEFT JOIN {ds}.INFORMATION_SCHEMA.TABLE_OPTIONS o ON o.table_name=c.table_name AND o.option_name='description' "
                            "GROUP BY 1, 2 ORDER BY 1, 2"))
        # the table is not aliased c: BigQuery would read c.ordinal_position as the output column c
        q.append(("columns", f"SELECT col.table_schema AS s, col.table_name AS t, col.column_name AS c, NULL AS cc, NULL AS tc, NULL AS n "  # nosec B608  # catalog names pass safe_name/lit; paging wraps generated SQL with bounded integers
                             f"FROM {ds}.INFORMATION_SCHEMA.COLUMNS col ORDER BY 1, 2, col.ordinal_position"))
    elif f == "oracle":
        w = f" AND c.OWNER={lit(schema)}" if one else " AND c.OWNER NOT IN ('SYS','SYSTEM','XDB','MDSYS','CTXSYS','ORDSYS','OUTLN','DBSNMP','WMSYS','APPQOSSYS','GSMADMIN_INTERNAL','LBACSYS','OLAPSYS','DVSYS','AUDSYS','OJVMSYS','ORDDATA')"
        q.append(("columns", "SELECT c.OWNER AS s, c.TABLE_NAME AS t, c.COLUMN_NAME AS c, cm.COMMENTS AS cc, tm.COMMENTS AS tc, tb.NUM_ROWS AS n "  # nosec B608  # catalog names pass safe_name/lit; paging wraps generated SQL with bounded integers
                             "FROM ALL_TAB_COLUMNS c LEFT JOIN ALL_COL_COMMENTS cm ON cm.OWNER=c.OWNER AND cm.TABLE_NAME=c.TABLE_NAME AND cm.COLUMN_NAME=c.COLUMN_NAME "
                             "LEFT JOIN ALL_TAB_COMMENTS tm ON tm.OWNER=c.OWNER AND tm.TABLE_NAME=c.TABLE_NAME LEFT JOIN ALL_TABLES tb ON tb.OWNER=c.OWNER AND tb.TABLE_NAME=c.TABLE_NAME "
                             f"WHERE 1=1{w} ORDER BY c.OWNER, c.TABLE_NAME, c.COLUMN_ID"))
    elif f == "db2":
        w = f" AND c.TABSCHEMA={lit(schema)}" if one else " AND c.TABSCHEMA NOT LIKE 'SYS%'"
        q.append(("columns", "SELECT c.TABSCHEMA AS s, c.TABNAME AS t, c.COLNAME AS c, c.REMARKS AS cc, tb.REMARKS AS tc, tb.CARD AS n "  # nosec B608  # catalog names pass safe_name/lit; paging wraps generated SQL with bounded integers
                             "FROM SYSCAT.COLUMNS c JOIN SYSCAT.TABLES tb ON tb.TABSCHEMA=c.TABSCHEMA AND tb.TABNAME=c.TABNAME "
                             f"WHERE tb.TYPE IN ('T','V'){w} ORDER BY 1, 2, c.COLNO"))
    elif f == "db2i":
        w = f" AND c.TABLE_SCHEMA={lit(schema)}" if one else " AND c.TABLE_SCHEMA NOT LIKE 'Q%'"
        q.append(("columns", "SELECT c.TABLE_SCHEMA AS s, c.TABLE_NAME AS t, c.COLUMN_NAME AS c, c.LONG_COMMENT AS cc, NULL AS tc, st.NUMBER_ROWS AS n "  # nosec B608  # catalog names pass safe_name/lit; paging wraps generated SQL with bounded integers
                             "FROM QSYS2.SYSCOLUMNS c LEFT JOIN QSYS2.SYSTABLESTAT st ON st.TABLE_SCHEMA=c.TABLE_SCHEMA AND st.TABLE_NAME=c.TABLE_NAME "
                             f"WHERE 1=1{w} ORDER BY 1, 2, c.ORDINAL_POSITION"))
    elif f == "db2z":
        w = f" AND c.TBCREATOR={lit(schema)}" if one else " AND c.TBCREATOR NOT LIKE 'SYS%'"
        q.append(("columns", "SELECT TRIM(c.TBCREATOR) AS s, TRIM(c.TBNAME) AS t, TRIM(c.NAME) AS c, c.REMARKS AS cc, tb.REMARKS AS tc, tb.CARDF AS n "  # nosec B608  # catalog names pass safe_name/lit; paging wraps generated SQL with bounded integers
                             "FROM SYSIBM.SYSCOLUMNS c JOIN SYSIBM.SYSTABLES tb ON tb.CREATOR=c.TBCREATOR AND tb.NAME=c.TBNAME "
                             f"WHERE tb.TYPE IN ('T','V'){w} ORDER BY 1, 2, c.COLNO"))
    elif f == "teradata":
        w = f" AND c.DatabaseName={lit(schema)}" if one else " AND c.DatabaseName NOT IN ('DBC','SYSLIB','SYSUDTLIB','SystemFe','SYSBAR','TD_SYSFNLIB','SYSSPATIAL','SQLJ','TDStats')"
        q.append(("columns", "SELECT TRIM(c.DatabaseName) AS s, TRIM(c.TableName) AS t, TRIM(c.ColumnName) AS c, c.CommentString AS cc, tb.CommentString AS tc, NULL AS n "  # nosec B608  # catalog names pass safe_name/lit; paging wraps generated SQL with bounded integers
                             "FROM DBC.ColumnsV c JOIN DBC.TablesV tb ON tb.DatabaseName=c.DatabaseName AND tb.TableName=c.TableName "
                             f"WHERE tb.TableKind IN ('T','O','V'){w}"))
    elif f == "hana":
        w = f" AND c.SCHEMA_NAME={lit(schema)}" if one else " AND c.SCHEMA_NAME NOT IN ('SYS','SYSTEM','PUBLIC') AND (c.SCHEMA_NAME NOT LIKE '\\_SYS%' ESCAPE '\\' OR c.SCHEMA_NAME='_SYS_BIC')"
        q.append(("tables", "SELECT c.SCHEMA_NAME AS s, c.TABLE_NAME AS t, MAX(m.RECORD_COUNT) AS n, MAX(tb.COMMENTS) AS tc, "  # nosec B608  # catalog names pass safe_name/lit; paging wraps generated SQL with bounded integers
                            f"STRING_AGG(c.COLUMN_NAME, '{SEP}' ORDER BY c.POSITION) AS cols, STRING_AGG(COALESCE(c.COMMENTS, ''), '{SEP}' ORDER BY c.POSITION) AS cc "
                            "FROM ((SELECT SCHEMA_NAME, TABLE_NAME, COLUMN_NAME, POSITION, COMMENTS FROM SYS.TABLE_COLUMNS) UNION ALL "
                            "(SELECT SCHEMA_NAME, VIEW_NAME, COLUMN_NAME, POSITION, COMMENTS FROM SYS.VIEW_COLUMNS)) c "
                            "LEFT JOIN SYS.TABLES tb ON tb.SCHEMA_NAME=c.SCHEMA_NAME AND tb.TABLE_NAME=c.TABLE_NAME "
                            "LEFT JOIN SYS.M_TABLES m ON m.SCHEMA_NAME=c.SCHEMA_NAME AND m.TABLE_NAME=c.TABLE_NAME "
                            f"WHERE 1=1{w} GROUP BY c.SCHEMA_NAME, c.TABLE_NAME ORDER BY 1, 2"))
        # a gateway that refuses the union above still lets tables through
        q.append(("columns", "SELECT c.SCHEMA_NAME AS s, c.TABLE_NAME AS t, c.COLUMN_NAME AS c, c.COMMENTS AS cc, NULL AS tc, NULL AS n "  # nosec B608  # catalog names pass safe_name/lit; paging wraps generated SQL with bounded integers
                             f"FROM SYS.TABLE_COLUMNS c WHERE 1=1{w} ORDER BY 1, 2, c.POSITION"))
    elif f == "vertica":
        w = f" AND c.table_schema={lit(schema)}" if one else " AND c.table_schema NOT IN ('v_catalog','v_monitor','v_internal')"
        q.append(("columns", "SELECT c.table_schema AS s, c.table_name AS t, c.column_name AS c, NULL AS cc, NULL AS tc, NULL AS n "  # nosec B608  # catalog names pass safe_name/lit; paging wraps generated SQL with bounded integers
                             f"FROM v_catalog.columns c WHERE 1=1{w} ORDER BY 1, 2, c.ordinal_position"))
    elif f == "trino":
        w = f" AND c.table_schema={lit(schema)}" if one else ""
        cc = f"array_join(array_agg(coalesce(c.comment, '') ORDER BY c.ordinal_position), '{SEP}')" if "athena" in (dbms or "").lower() else "NULL"
        q.append(("tables", "SELECT c.table_schema AS s, c.table_name AS t, NULL AS n, NULL AS tc, "  # nosec B608  # catalog names pass safe_name/lit; paging wraps generated SQL with bounded integers
                            f"array_join(array_agg(c.column_name ORDER BY c.ordinal_position), '{SEP}') AS cols, {cc} AS cc "
                            f"FROM information_schema.columns c WHERE c.table_schema <> 'information_schema'{w} GROUP BY 1, 2 ORDER BY 1, 2"))
    elif f == "exasol":
        w = f" AND c.COLUMN_SCHEMA={lit(schema)}" if one else ""
        q.append(("columns", "SELECT c.COLUMN_SCHEMA AS s, c.COLUMN_TABLE AS t, c.COLUMN_NAME AS c, c.COLUMN_COMMENT AS cc, tb.TABLE_COMMENT AS tc, tb.TABLE_ROW_COUNT AS n "  # nosec B608  # catalog names pass safe_name/lit; paging wraps generated SQL with bounded integers
                             "FROM EXA_ALL_COLUMNS c LEFT JOIN EXA_ALL_TABLES tb ON tb.TABLE_SCHEMA=c.COLUMN_SCHEMA AND tb.TABLE_NAME=c.COLUMN_TABLE "
                             f"WHERE 1=1{w} ORDER BY 1, 2, c.COLUMN_ORDINAL_POSITION"))
    elif f in ("netezza", "dremio"):
        view = {"netezza": ("_V_RELATION_COLUMN", "SCHEMA", "NAME", "ATTNAME", "DESCRIPTION", "ATTNUM"),
                "dremio": ('INFORMATION_SCHEMA."COLUMNS"', "TABLE_SCHEMA", "TABLE_NAME", "COLUMN_NAME", "NULL", "ORDINAL_POSITION")}[f]
        w = f" AND c.{view[1]}={lit(schema)}" if one else ""
        q.append(("columns", f"SELECT c.{view[1]} AS s, c.{view[2]} AS t, c.{view[3]} AS c, {('c.' + view[4]) if view[4] != 'NULL' else 'NULL'} AS cc, NULL AS tc, NULL AS n "  # nosec B608  # catalog names pass safe_name/lit; paging wraps generated SQL with bounded integers
                             f"FROM {view[0]} c WHERE 1=1{w} ORDER BY 1, 2, c.{view[5]}"))
    else:
        return []
    return q


def paged(dbms: str, sql: str, page: int, size: int = PAGE) -> str:
    """one page of a catalog statement (it already ends in ORDER BY): each database's own paging"""
    if type(page) is not int or type(size) is not int or page < 0 or not 1 <= size <= PAGE:
        raise ValueError("Catalog paging needs a nonnegative integer page and a size from 1 to 1000")
    f = flavor(dbms)
    off = page * size
    if f == "oracle" and re.search(r"\b(8i|9i|10g|11g)\b", (dbms or "").lower()):
        return f"SELECT * FROM (SELECT x.*, ROWNUM AS rn_ FROM ({sql}) x WHERE ROWNUM <= {off + size}) WHERE rn_ > {off}"      # before 12c  # nosec B608  # catalog names pass safe_name/lit; paging wraps generated SQL with bounded integers
    if f in ("sqlserver", "oracle", "db2", "db2i", "db2z"):
        return f"{sql} OFFSET {off} ROWS FETCH NEXT {size} ROWS ONLY"
    if f == "synapse":
        # no OFFSET; a derived table may not keep its ORDER BY, so number the rows instead
        body = re.sub(r"(?is)\s+ORDER BY [^()]*$", "", sql)
        by = "s, t, c" if " AS c," in sql else "s, t"
        return f"SELECT * FROM (SELECT x.*, ROW_NUMBER() OVER (ORDER BY {by}) AS rn_ FROM ({body}) x) y WHERE rn_ BETWEEN {off + 1} AND {off + size} ORDER BY rn_"  # nosec B608  # catalog names pass safe_name/lit; paging wraps generated SQL with bounded integers
    if f == "teradata":
        by = "s, t, c" if " AS c," in sql else "s, t"
        return f"SELECT * FROM ({sql}) x QUALIFY ROW_NUMBER() OVER (ORDER BY {by}) BETWEEN {off + 1} AND {off + size} ORDER BY {by}"  # nosec B608  # catalog names pass safe_name/lit; paging wraps generated SQL with bounded integers
    if f == "trino":
        return f"{sql} OFFSET {off} LIMIT {size}"
    return f"{sql} LIMIT {size} OFFSET {off}"


def row_counts_sql(dbms: str, schema: str) -> str | None:
    """t, n: the row counts the database keeps for a schema's tables (no table is counted)"""
    if not safe_name(schema):
        return None
    f, s = flavor(dbms), lit(schema)
    return {
        "snowflake": f"SELECT TABLE_NAME AS t, ROW_COUNT AS n FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA={s} AND TABLE_TYPE='BASE TABLE'",  # nosec B608  # catalog names pass safe_name/lit; paging wraps generated SQL with bounded integers
        "postgres": ("SELECT c.relname AS t, NULLIF(c.reltuples, -1)::bigint AS n FROM pg_class c JOIN pg_namespace ns ON ns.oid=c.relnamespace "  # nosec B608  # catalog names pass safe_name/lit; paging wraps generated SQL with bounded integers
                     f"WHERE ns.nspname={s} AND c.relkind IN ('r','p')"),
        # svv_table_info is for superusers only; the planner's estimate is readable by anyone
        "redshift": ("SELECT c.relname AS t, c.reltuples::bigint AS n FROM pg_class c JOIN pg_namespace ns ON ns.oid=c.relnamespace "  # nosec B608  # catalog names pass safe_name/lit; paging wraps generated SQL with bounded integers
                     f"WHERE ns.nspname={s} AND c.relkind='r'"),
        "sqlserver": ("SELECT t.name AS t, SUM(p.rows) AS n FROM sys.tables t JOIN sys.schemas sc ON sc.schema_id=t.schema_id "  # nosec B608  # catalog names pass safe_name/lit; paging wraps generated SQL with bounded integers
                      f"JOIN sys.partitions p ON p.object_id=t.object_id AND p.index_id IN (0, 1) WHERE sc.name={s} GROUP BY t.name"),
        "mysql": f"SELECT TABLE_NAME AS t, TABLE_ROWS AS n FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA={s}",  # nosec B608  # catalog names pass safe_name/lit; paging wraps generated SQL with bounded integers
        "clickhouse": f"SELECT name AS t, total_rows AS n FROM system.tables WHERE database={s}",  # nosec B608  # catalog names pass safe_name/lit; paging wraps generated SQL with bounded integers
        "bigquery": f"SELECT table_id AS t, row_count AS n FROM `{schema.replace('`', '')}`.__TABLES__",  # nosec B608  # catalog names pass safe_name/lit; paging wraps generated SQL with bounded integers
        "oracle": f"SELECT TABLE_NAME AS t, NUM_ROWS AS n FROM ALL_TABLES WHERE OWNER={s}",  # nosec B608  # catalog names pass safe_name/lit; paging wraps generated SQL with bounded integers
        "db2": f"SELECT TABNAME AS t, CARD AS n FROM SYSCAT.TABLES WHERE TABSCHEMA={s}",  # nosec B608  # catalog names pass safe_name/lit; paging wraps generated SQL with bounded integers
        "db2i": f"SELECT TABLE_NAME AS t, NUMBER_ROWS AS n FROM QSYS2.SYSTABLESTAT WHERE TABLE_SCHEMA={s}",  # nosec B608  # catalog names pass safe_name/lit; paging wraps generated SQL with bounded integers
        "db2z": f"SELECT TRIM(NAME) AS t, CARDF AS n FROM SYSIBM.SYSTABLES WHERE CREATOR={s} AND TYPE='T'",  # nosec B608  # catalog names pass safe_name/lit; paging wraps generated SQL with bounded integers
        "teradata": f"SELECT TRIM(TableName) AS t, MAX(RowCount) AS n FROM DBC.TableStatsV WHERE DatabaseName={s} GROUP BY 1",  # nosec B608  # catalog names pass safe_name/lit; paging wraps generated SQL with bounded integers
        "exasol": f"SELECT TABLE_NAME AS t, TABLE_ROW_COUNT AS n FROM EXA_ALL_TABLES WHERE TABLE_SCHEMA={s}",  # nosec B608  # catalog names pass safe_name/lit; paging wraps generated SQL with bounded integers
        "hana": f"SELECT TABLE_NAME AS t, RECORD_COUNT AS n FROM SYS.M_TABLES WHERE SCHEMA_NAME={s}",  # nosec B608  # catalog names pass safe_name/lit; paging wraps generated SQL with bounded integers
    }.get(f or "")


def keys_sqls(dbms: str, schema: str) -> list[str]:
    """statements whose rows together are the declared keys in a schema: t, c, k ('PRIMARY KEY' | 'FOREIGN KEY'), pt, pc,
    n, one row per key column (Snowflake keeps its keys in each table's DDL: see mosaic_discover._declared_keys). Where
    primary and foreign keys live in different views they are separate statements: Strategy's gateway refuses a UNION
    over system views, parenthesized or not."""
    sql = _keys_sql(dbms, schema) if safe_name(schema) else None
    return [] if not sql else sql if isinstance(sql, list) else [sql]


def _keys_sql(dbms: str, schema: str):
    f, s = flavor(dbms), lit(schema)
    ansi = ("SELECT tc.table_name AS t, kcu.column_name AS c, tc.constraint_type AS k, ccu.table_name AS pt, ccu.column_name AS pc, tc.constraint_name AS n "  # nosec B608  # catalog names pass safe_name/lit; paging wraps generated SQL with bounded integers
            "FROM information_schema.table_constraints tc JOIN information_schema.key_column_usage kcu ON kcu.constraint_name=tc.constraint_name "
            "AND kcu.table_schema=tc.table_schema AND kcu.table_name=tc.table_name LEFT JOIN information_schema.constraint_column_usage ccu "
            f"ON ccu.constraint_name=tc.constraint_name AND ccu.table_schema=tc.table_schema WHERE tc.table_schema={s} AND tc.constraint_type IN ('PRIMARY KEY','FOREIGN KEY')")
    if f == "postgres":
        # pg_constraint, not information_schema: the standard views hide constraints of tables the reader only SELECTs,
        # and pair the columns of a several-column key with each other
        return ("SELECT cl.relname AS t, a.attname AS c, CASE co.contype WHEN 'p' THEN 'PRIMARY KEY' ELSE 'FOREIGN KEY' END AS k, "  # nosec B608  # catalog names pass safe_name/lit; paging wraps generated SQL with bounded integers
                "rcl.relname AS pt, ra.attname AS pc, co.conname AS n FROM pg_constraint co JOIN pg_class cl ON cl.oid=co.conrelid "
                "JOIN pg_namespace ns ON ns.oid=cl.relnamespace CROSS JOIN LATERAL unnest(co.conkey, co.confkey) WITH ORDINALITY AS u(att, fatt, ord) "
                "JOIN pg_attribute a ON a.attrelid=co.conrelid AND a.attnum=u.att LEFT JOIN pg_class rcl ON rcl.oid=co.confrelid "
                f"LEFT JOIN pg_attribute ra ON ra.attrelid=co.confrelid AND ra.attnum=u.fatt WHERE ns.nspname={s} AND co.contype IN ('p','f')")
    if f in ("redshift", "databricks"):
        return ansi
    if f in ("sqlserver", "synapse"):
        # the catalog views: INFORMATION_SCHEMA misses a foreign key that references a unique index
        return [("SELECT t.name AS t, c.name AS c, 'FOREIGN KEY' AS k, rt.name AS pt, rc.name AS pc, fk.name AS n FROM sys.foreign_key_columns fkc "  # nosec B608  # catalog names pass safe_name/lit; paging wraps generated SQL with bounded integers
                "JOIN sys.foreign_keys fk ON fk.object_id=fkc.constraint_object_id JOIN sys.tables t ON t.object_id=fkc.parent_object_id "
                "JOIN sys.schemas sc ON sc.schema_id=t.schema_id JOIN sys.columns c ON c.object_id=fkc.parent_object_id AND c.column_id=fkc.parent_column_id "
                "JOIN sys.tables rt ON rt.object_id=fkc.referenced_object_id JOIN sys.columns rc ON rc.object_id=fkc.referenced_object_id AND rc.column_id=fkc.referenced_column_id "
                f"WHERE sc.name={s}"),
                ("SELECT t.name AS t, c.name AS c, 'PRIMARY KEY' AS k, NULL AS pt, NULL AS pc, i.name AS n FROM sys.indexes i JOIN sys.index_columns ic ON ic.object_id=i.object_id AND ic.index_id=i.index_id "  # nosec B608  # catalog names pass safe_name/lit; paging wraps generated SQL with bounded integers
                "JOIN sys.tables t ON t.object_id=i.object_id JOIN sys.schemas sc ON sc.schema_id=t.schema_id JOIN sys.columns c ON c.object_id=ic.object_id AND c.column_id=ic.column_id "
                f"WHERE i.is_primary_key=1 AND sc.name={s}")]
    if f == "mysql":
        return ("SELECT k.TABLE_NAME AS t, k.COLUMN_NAME AS c, CASE WHEN k.CONSTRAINT_NAME='PRIMARY' THEN 'PRIMARY KEY' ELSE 'FOREIGN KEY' END AS k, "  # nosec B608  # catalog names pass safe_name/lit; paging wraps generated SQL with bounded integers
                "k.REFERENCED_TABLE_NAME AS pt, k.REFERENCED_COLUMN_NAME AS pc, k.CONSTRAINT_NAME AS n FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE k "
                f"WHERE k.TABLE_SCHEMA={s} AND (k.CONSTRAINT_NAME='PRIMARY' OR k.REFERENCED_TABLE_NAME IS NOT NULL)")
    if f == "bigquery":
        ds = "`" + schema.replace("`", "") + "`"
        return ("SELECT tc.table_name AS t, kcu.column_name AS c, tc.constraint_type AS k, ccu.table_name AS pt, ccu.column_name AS pc, tc.constraint_name AS n "  # nosec B608  # catalog names pass safe_name/lit; paging wraps generated SQL with bounded integers
                f"FROM {ds}.INFORMATION_SCHEMA.TABLE_CONSTRAINTS tc JOIN {ds}.INFORMATION_SCHEMA.KEY_COLUMN_USAGE kcu ON kcu.constraint_name=tc.constraint_name "
                f"LEFT JOIN {ds}.INFORMATION_SCHEMA.CONSTRAINT_COLUMN_USAGE ccu ON ccu.constraint_name=tc.constraint_name AND tc.constraint_type='FOREIGN KEY' "
                "WHERE tc.constraint_type IN ('PRIMARY KEY','FOREIGN KEY')")
    if f == "oracle":
        return ("SELECT c.TABLE_NAME AS t, cc.COLUMN_NAME AS c, CASE c.CONSTRAINT_TYPE WHEN 'P' THEN 'PRIMARY KEY' ELSE 'FOREIGN KEY' END AS k, "  # nosec B608  # catalog names pass safe_name/lit; paging wraps generated SQL with bounded integers
                "rc.TABLE_NAME AS pt, rcc.COLUMN_NAME AS pc, c.CONSTRAINT_NAME AS n FROM ALL_CONSTRAINTS c "
                "JOIN ALL_CONS_COLUMNS cc ON cc.OWNER=c.OWNER AND cc.CONSTRAINT_NAME=c.CONSTRAINT_NAME "
                "LEFT JOIN ALL_CONSTRAINTS rc ON rc.OWNER=c.R_OWNER AND rc.CONSTRAINT_NAME=c.R_CONSTRAINT_NAME "
                "LEFT JOIN ALL_CONS_COLUMNS rcc ON rcc.OWNER=rc.OWNER AND rcc.CONSTRAINT_NAME=rc.CONSTRAINT_NAME AND rcc.POSITION=cc.POSITION "
                f"WHERE c.OWNER={s} AND c.CONSTRAINT_TYPE IN ('P','R')")
    if f == "db2":
        return ("SELECT k.TABNAME AS t, k.COLNAME AS c, CASE tc.TYPE WHEN 'P' THEN 'PRIMARY KEY' ELSE 'FOREIGN KEY' END AS k, r.REFTABNAME AS pt, pk.COLNAME AS pc, k.CONSTNAME AS n "  # nosec B608  # catalog names pass safe_name/lit; paging wraps generated SQL with bounded integers
                "FROM SYSCAT.KEYCOLUSE k JOIN SYSCAT.TABCONST tc ON tc.TABSCHEMA=k.TABSCHEMA AND tc.CONSTNAME=k.CONSTNAME "
                "LEFT JOIN SYSCAT.REFERENCES r ON r.TABSCHEMA=k.TABSCHEMA AND r.CONSTNAME=k.CONSTNAME "
                "LEFT JOIN SYSCAT.KEYCOLUSE pk ON pk.TABSCHEMA=r.REFTABSCHEMA AND pk.CONSTNAME=r.REFKEYNAME AND pk.COLSEQ=k.COLSEQ "
                f"WHERE k.TABSCHEMA={s} AND tc.TYPE IN ('P','F')")
    if f == "hana":
        # primary keys in SYS.CONSTRAINTS, foreign keys only in SYS.REFERENTIAL_CONSTRAINTS
        return [("SELECT TABLE_NAME AS t, COLUMN_NAME AS c, 'PRIMARY KEY' AS k, NULL AS pt, NULL AS pc, CONSTRAINT_NAME AS n FROM SYS.CONSTRAINTS "  # nosec B608  # catalog names pass safe_name/lit; paging wraps generated SQL with bounded integers
                f"WHERE SCHEMA_NAME={s} AND IS_PRIMARY_KEY='TRUE'"),
                ("SELECT TABLE_NAME AS t, COLUMN_NAME AS c, 'FOREIGN KEY' AS k, REFERENCED_TABLE_NAME AS pt, REFERENCED_COLUMN_NAME AS pc, CONSTRAINT_NAME AS n FROM SYS.REFERENTIAL_CONSTRAINTS "  # nosec B608  # catalog names pass safe_name/lit; paging wraps generated SQL with bounded integers
                f"WHERE SCHEMA_NAME={s}")]
    if f == "exasol":
        return ("SELECT CONSTRAINT_TABLE AS t, COLUMN_NAME AS c, CONSTRAINT_TYPE AS k, REFERENCED_TABLE AS pt, REFERENCED_COLUMN AS pc, CONSTRAINT_NAME AS n "  # nosec B608  # catalog names pass safe_name/lit; paging wraps generated SQL with bounded integers
                f"FROM EXA_ALL_CONSTRAINT_COLUMNS WHERE CONSTRAINT_SCHEMA={s} AND CONSTRAINT_TYPE IN ('PRIMARY KEY','FOREIGN KEY')")
    return None


def column_stats_sql(dbms: str, schema: str) -> str | None:
    """t, c, rows_n, ndv, nulls (and, for PostgreSQL, the most common values and histogram bounds as text): the
    statistics the database keeps for its query planner, read from its catalog. ndv below 0 is PostgreSQL's
    fraction of rows (-1 = every row distinct)."""
    if not safe_name(schema):
        return None
    f, s = flavor(dbms), lit(schema)
    if f == "postgres":
        return ("SELECT st.tablename AS t, st.attname AS c, NULLIF(cl.reltuples, -1)::bigint AS rows_n, st.n_distinct AS ndv, st.null_frac AS nulls, "  # nosec B608  # catalog names pass safe_name/lit; paging wraps generated SQL with bounded integers
                "st.most_common_vals::text AS mcv, st.histogram_bounds::text AS hist FROM pg_stats st JOIN pg_namespace ns ON ns.nspname=st.schemaname "
                f"JOIN pg_class cl ON cl.relnamespace=ns.oid AND cl.relname=st.tablename WHERE st.schemaname={s}")
    if f == "oracle":
        return ("SELECT s.TABLE_NAME AS t, s.COLUMN_NAME AS c, tb.NUM_ROWS AS rows_n, s.NUM_DISTINCT AS ndv, s.NUM_NULLS AS nulls "  # nosec B608  # catalog names pass safe_name/lit; paging wraps generated SQL with bounded integers
                "FROM ALL_TAB_COL_STATISTICS s JOIN ALL_TABLES tb ON tb.OWNER=s.OWNER AND tb.TABLE_NAME=s.TABLE_NAME "
                f"WHERE s.OWNER={s} AND s.NUM_DISTINCT IS NOT NULL")
    if f == "db2":
        return ("SELECT c.TABNAME AS t, c.COLNAME AS c, tb.CARD AS rows_n, c.COLCARD AS ndv, c.NUMNULLS AS nulls "  # nosec B608  # catalog names pass safe_name/lit; paging wraps generated SQL with bounded integers
                "FROM SYSCAT.COLUMNS c JOIN SYSCAT.TABLES tb ON tb.TABSCHEMA=c.TABSCHEMA AND tb.TABNAME=c.TABNAME "
                f"WHERE c.TABSCHEMA={s} AND c.COLCARD >= 0 AND tb.CARD >= 0")
    if f == "mysql":
        return ("SELECT st.TABLE_NAME AS t, st.COLUMN_NAME AS c, tb.TABLE_ROWS AS rows_n, st.CARDINALITY AS ndv, NULL AS nulls "  # nosec B608  # catalog names pass safe_name/lit; paging wraps generated SQL with bounded integers
                "FROM INFORMATION_SCHEMA.STATISTICS st JOIN INFORMATION_SCHEMA.TABLES tb ON tb.TABLE_SCHEMA=st.TABLE_SCHEMA AND tb.TABLE_NAME=st.TABLE_NAME "
                f"WHERE st.TABLE_SCHEMA={s} AND st.SEQ_IN_INDEX=1")
    if f == "db2z":
        return ("SELECT TRIM(c.TBNAME) AS t, TRIM(c.NAME) AS c, tb.CARDF AS rows_n, c.COLCARDF AS ndv, NULL AS nulls "  # nosec B608  # catalog names pass safe_name/lit; paging wraps generated SQL with bounded integers
                "FROM SYSIBM.SYSCOLUMNS c JOIN SYSIBM.SYSTABLES tb ON tb.CREATOR=c.TBCREATOR AND tb.NAME=c.TBNAME "
                f"WHERE c.TBCREATOR={s} AND c.COLCARDF >= 0 AND tb.CARDF >= 0")
    if f == "teradata":
        return ("SELECT TRIM(TableName) AS t, TRIM(ColumnName) AS c, RowCount AS rows_n, UniqueValueCount AS ndv, NullCount AS nulls "  # nosec B608  # catalog names pass safe_name/lit; paging wraps generated SQL with bounded integers
                f"FROM DBC.StatsV WHERE DatabaseName={s} AND ColumnName IS NOT NULL AND ColumnName NOT LIKE '%,%'")
    if f == "sqlserver":
        # single-column statistics: distinct values ≈ histogram steps + the distinct values between them (2016 SP1 CU2+)
        return ("SELECT t.name AS t, c.name AS c, sp.rows AS rows_n, (SELECT COUNT(*) + SUM(h.distinct_range_rows) FROM sys.dm_db_stats_histogram(st.object_id, st.stats_id) h) AS ndv, "  # nosec B608  # catalog names pass safe_name/lit; paging wraps generated SQL with bounded integers
                "NULL AS nulls FROM sys.stats st JOIN sys.stats_columns sc ON sc.object_id=st.object_id AND sc.stats_id=st.stats_id AND sc.stats_column_id=1 "
                "JOIN sys.columns c ON c.object_id=sc.object_id AND c.column_id=sc.column_id JOIN sys.tables t ON t.object_id=st.object_id "
                "JOIN sys.schemas sch ON sch.schema_id=t.schema_id CROSS APPLY sys.dm_db_stats_properties(st.object_id, st.stats_id) sp "
                f"WHERE sch.name={s} AND sp.rows > 0 AND NOT EXISTS (SELECT 1 FROM sys.stats_columns x WHERE x.object_id=st.object_id AND x.stats_id=st.stats_id AND x.stats_column_id=2)")
    return None
