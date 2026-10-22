import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _hermetic  # noqa: E402,F401  (scrub MSTR_*/proxy env, private secret store)

# Each kind of database Strategy connects to, read from its own catalog: the right flavor for every Strategy type name,
# statements that read catalog views only (never a table), and each database's own paging.
import os  # noqa: E402
import re  # noqa: E402
import sys  # noqa: E402
import unittest  # noqa: E402

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "skills", "build-mosaic-model", "scripts"))
import mosaic_dialects as d  # noqa: E402

TYPES = {
    "Snowflake": "snowflake", "PostgreSQL": "postgres", "AlloyDB": "postgres", "Amazon Aurora PostgreSQL Compatible": "postgres",
    "Pivotal Greenplum": "postgres", "Yellowbrick": "postgres", "Amazon Redshift": "redshift", "Actian Matrix": "redshift",
    "Microsoft SQL Server 2019/2022": "sqlserver", "Microsoft SQL Server 2008 and 2008 R2": "sqlserver", "Azure SQL Database": "sqlserver",
    "Azure Synapse Analytics": "synapse", "Microsoft Fabric Warehouse": "sqlserver", "Microsoft Fabric Lakehouse": "sqlserver",
    "MySQL 8.x": "mysql", "MariaDB": "mysql", "Amazon Aurora MySQL Compatible": "mysql", "SingleStore": "mysql", "StarRocks": "mysql",
    "Infobright": "mysql", "ClickHouse": "clickhouse", "Databricks": "databricks", "Spark SQL 3.x": "databricks",
    "Google BigQuery": "bigquery", "Google BigQuery Native": "bigquery", "Oracle 19c": "oracle", "Oracle 11g": "oracle",
    "IBM Db2": "db2", "IBM Db2 for i": "db2i", "IBM Db2 for z/OS": "db2z", "Teradata 17.x": "teradata", "SAP HANA 2.x": "hana",
    "SAP Datasphere": "hana", "Vertica": "vertica", "Trino": "trino", "Presto": "trino", "Starburst": "trino", "Amazon Athena": "trino",
    "Exasol": "exasol", "IBM Netezza Performance Server": "netezza", "Dremio": "dremio",
    "MongoDB": None, "Apache Cassandra": None, "Azure Cosmos DB": None, "Salesforce": None, "ServiceNow": None, "Elasticsearch": None,
    "Oracle Essbase 11.x MDX Cube provider": None, "SAP HANA 2.0 SPS4 (MDX Cube Provider)": None, "Google Sheet": None,
}
# the catalog and system objects each flavor may read; anything else would be a user table
CATALOG = re.compile(r"(?i)^(information_schema\.|`?[\w-]+`?\.information_schema\.|`[\w-]+`\.__tables__$|pg_|svv_|sys\.|system\.|all_|syscat\.|qsys2\.|dbc\.|v_catalog\.|exa_|_v_|sysibm\.|lateral$|\(select)")


def sources(sql: str) -> list[str]:
    return re.findall(r"(?i)\b(?:FROM|JOIN)\s+([^\s,()]+|\(SELECT)", sql)


class FlavorTests(unittest.TestCase):
    def test_every_strategy_type_maps_to_its_flavor(self):
        for name, want in TYPES.items():
            self.assertEqual(d.flavor(name), want, name)


class ReadOnlyCatalogTests(unittest.TestCase):
    def statements(self):
        for name, f in TYPES.items():
            if not f:
                continue
            for schema in ("SALES", None):
                for kind, sql in d.catalog_queries(name, schema):
                    yield name, sql
                    yield name, d.paged(name, sql, 2)
            for fn in (d.row_counts_sql, lambda n, s_: "\n".join(d.keys_sqls(n, s_)) or None, d.column_stats_sql):
                sql = fn(name, "SALES")
                if sql:
                    yield name, sql

    def test_statements_read_catalog_views_only(self):
        seen = 0
        for name, sql in self.statements():
            for src in sources(sql):
                self.assertRegex(src, CATALOG, f"{name}: {src} in {sql[:160]}")
            seen += 1
        self.assertGreater(seen, 60)

    def test_no_statement_has_a_bare_union_select_strategys_gateway_refuses(self):
        for name, sql in self.statements():
            self.assertNotRegex(sql, r"(?i)UNION(\s+ALL)?\s+SELECT", name)

    def test_a_name_a_quote_cannot_contain_safely_never_reaches_sql(self):
        for name in TYPES:
            for evil in ("x\\' OR 1=1 --", "a`b", "tab\there"):
                self.assertEqual(d.catalog_queries(name, evil), [], name)
                self.assertIsNone(d.row_counts_sql(name, evil))
                self.assertEqual(d.keys_sqls(name, evil), [])
                self.assertIsNone(d.column_stats_sql(name, evil))

    def test_a_schema_name_is_a_literal_never_injected(self):
        for name, f in TYPES.items():
            for kind, sql in d.catalog_queries(name, "O'BRIEN") if f and f != "bigquery" else []:
                self.assertIn("'O''BRIEN'", sql, name)

    def test_every_sql_flavor_reads_one_schema_and_most_read_a_whole_source(self):
        flavors = {f for f in TYPES.values() if f}
        self.assertTrue(all(d.catalog_queries(n, "SALES") for n, f in TYPES.items() if f))
        whole = {f for n, f in TYPES.items() if f and d.catalog_queries(n, None)}
        self.assertEqual(flavors - whole, {"bigquery"})                      # BigQuery is read one dataset at a time

    def test_nosql_saas_and_cube_sources_fall_back_to_strategys_catalog(self):
        for name in ("MongoDB", "Salesforce", "Oracle Essbase 11.x MDX Cube provider", "Google Sheet"):
            self.assertEqual(d.catalog_queries(name, "X"), [])


class PagingTests(unittest.TestCase):
    def test_each_database_pages_its_own_way(self):
        base = "SELECT s, t FROM x ORDER BY 1, 2"
        self.assertTrue(d.paged("Snowflake", base, 2).endswith("LIMIT 1000 OFFSET 2000"))
        self.assertTrue(d.paged("Microsoft Fabric Warehouse", base, 1).endswith("OFFSET 1000 ROWS FETCH NEXT 1000 ROWS ONLY"))
        self.assertTrue(d.paged("Oracle 19c", base, 0).endswith("OFFSET 0 ROWS FETCH NEXT 1000 ROWS ONLY"))
        self.assertTrue(d.paged("Trino", base, 3).endswith("OFFSET 3000 LIMIT 1000"))
        self.assertIn("QUALIFY ROW_NUMBER()", d.paged("Teradata 17.x", "SELECT s, t, c FROM DBC.ColumnsV", 1))
        self.assertIn("ROWNUM <= 2000) WHERE rn_ > 1000", d.paged("Oracle 11g", base, 1))       # before 12c: no OFFSET
        syn = d.paged("Azure Synapse Analytics", base, 1)                                     # no OFFSET, no ORDER BY inside
        self.assertNotIn("OFFSET", syn)
        self.assertIn("FROM (SELECT s, t FROM x) x", syn)
        self.assertTrue(syn.endswith("rn_ BETWEEN 1001 AND 2000 ORDER BY rn_"))


class CutListTests(unittest.TestCase):
    def test_a_joined_column_list_the_database_cut_short_is_read_again_one_row_per_column(self):
        import mosaic_find as mf

        class Live:
            def __init__(self):
                self.sql = []

            def run_sql(self, m, ds, sql):
                self.sql.append(sql)
                if "GROUP_CONCAT" in sql:               # 3 of 5 columns fit in the joined list
                    return [{"s": "S", "t": "WIDE", "n": 10, "tc": "", "k": 5, "cols": "A|B|C", "cc": ""}]
                return [{"s": "S", "t": "WIDE", "c": c, "cc": "", "tc": "", "n": 10} for c in "ABCDE"]
        live = Live()
        got = mf.catalog_tables(None, live, {"id": "x", "dbms": "MySQL 8.x"}, "S")
        self.assertEqual([c["name"] for c in got["S"][0]["columns"]], list("ABCDE"))
        self.assertEqual(len(live.sql), 2)

    def test_a_bigquery_dataset_is_found_without_its_project(self):
        import mosaic_find as mf

        class Live:
            def run_sql(self, m, ds, sql):
                return [{"s": "Sales", "t": "Transactions", "n": None, "tc": "", "cols": "ID|AMOUNT", "cc": "|"}]
        tables, how = mf.schema_tables(None, Live(), None, {"id": "x", "dbms": "Google BigQuery"}, "analytics-project.Sales")
        self.assertEqual((how, [t["table"] for t in tables]), ("catalog views", ["Transactions"]))


if __name__ == "__main__":
    unittest.main()
