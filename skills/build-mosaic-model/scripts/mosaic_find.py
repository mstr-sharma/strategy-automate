"""Find the tables that fit a description, from metadata only: table and column names, comments and descriptions, the
catalog's row counts, the tables existing models already use, and what the person's references name. No table is read:
each schema costs one query on its own catalog views (information_schema / pg_catalog), or a listing from Strategy's
catalog when the database has none we can read.

  find(m, "downtime by plant and shift", scopes=None)  → every source the person can reach, best schemas first
  find(m, "…", scopes=[{"datasource": "Snowflake-SE"}])                 → every schema of one source
  find(m, "…", scopes=[{"datasource": "…", "schema": "SALES"}])         → one schema
  find(m, "…", scopes=[{"datasource": "…", "schema": "…", "tables": ["FACT_*"]}])

The search stops at its time budget and says which schemas it read and which it left (never silent). The tables it
returns are the best matches plus the tables they join to (a shared key column in the same schema), ready for a scan.
"""
from __future__ import annotations

import fnmatch
import math
import re
import time
from typing import Any

import mosaic_plan as mp

STOP = set("""a about above after all also am an and any are as at be been being but by can could did do does doing done
each for from get got had has have how i if in into is it its just let lets like look looking make me more most my need
needs of on or our over please really see seem should show so some tell than that the their them then there these they
this those to understand us use using want was we were what whats when where which while who why will with would you
your across between compare comparing give going help know find model models data question questions start trying way
best doing well good bad high low top lot lots many much every per vs versus table tables database databases schema
schemas build building analyze analyse analysis report reports dashboard track tracking""".split())
THESAURUS = [
    {"revenue", "sales", "sale", "income", "turnover", "bookings", "billing", "billings", "earnings", "gmv"},
    {"cost", "spend", "expense", "expenditure", "charge"},
    {"profit", "margin", "profitability"},
    {"customer", "client", "account", "buyer", "member", "subscriber", "patient", "shopper", "cust"},
    {"product", "item", "sku", "article", "merchandise", "prod"},
    {"store", "location", "site", "branch", "outlet", "shop"},
    {"region", "territory", "geography", "market", "state", "country"},
    {"order", "purchase", "transaction", "txn"},
    {"employee", "staff", "worker", "headcount", "agent", "emp"},
    {"churn", "cancellation", "cancel", "attrition", "retention", "renewal", "lapse"},
    {"delay", "late", "lateness", "delivery", "shipment", "freight", "ontime"},
    {"downtime", "outage", "failure", "breakdown", "stoppage"},
    {"inventory", "stock", "onhand", "supply"},
    {"campaign", "promotion", "promo", "offer", "marketing"},
    {"claim", "reimbursement", "payer", "denial"},
    {"loan", "credit", "lending", "borrower", "default", "delinquency"},
    {"vendor", "supplier", "carrier", "partner"},
    {"plant", "factory", "mill", "production", "manufacturing"},
    {"price", "pricing", "rate", "fee"},
    {"quantity", "volume", "units", "qty"},
    {"date", "day", "calendar", "time", "period"},
]
SYN: dict[str, set[str]] = {}


def _stem(w: str) -> str:
    w = w.casefold().replace("'s", "")
    for suffix, keep in (("ies", "y"), ("ing", ""), ("ed", ""), ("es", ""), ("s", "")):
        if len(w) > len(suffix) + 3 and w.endswith(suffix) and not w.endswith("ss"):
            return w[: -len(suffix)] + keep
    return w


for _group in THESAURUS:
    _stems = {_stem(x) for x in _group}
    for _w in _stems:
        SYN.setdefault(_w, set()).update(_stems - {_w})


def terms(text: str) -> list[str]:
    """the description's content words, stemmed, each once"""
    out: list[str] = []
    for raw in re.findall(r"[A-Za-z][A-Za-z0-9']+", text or ""):
        if raw.casefold() in STOP or len(raw) < 3:
            continue
        w = _stem(raw)
        if w not in STOP and w not in out:
            out.append(w)
    return out


def words(name: str) -> set[str]:
    """a name's words: SNAKE_CASE, camelCase, spaces"""
    return {_stem(w) for w in re.findall(r"[A-Za-z][A-Za-z0-9]+", re.sub(r"([a-z])([A-Z])", r"\1 \2", (name or "").replace("_", " "))) if len(w) >= 2}


# ── metadata, one query per schema on its own catalog views ──────────────────────────────────────────────────────────
def _lit(s: str) -> str:
    return "'" + str(s).replace("'", "''") + "'"


PAGE = 1000                                             # Strategy returns at most 1,000 rows per source query
SEP = "|"


def _flavor(dbms: str) -> str | None:
    d = (dbms or "").lower()
    if "snowflake" in d:
        return "snowflake"
    if "postgres" in d or "redshift" in d:
        return "postgres"
    if "sql server" in d or "sqlserver" in d or "azure sql" in d or "synapse" in d:
        return "sqlserver"
    if "mysql" in d or "mariadb" in d:
        return "mysql"
    return None


def _catalog_sql(dbms: str, schema: str | None) -> str | None:
    """one row per table (its schema, name, row count, comment, and its columns and their comments joined), so a
    schema or a whole database fits in a few pages; catalog views only, no table is read"""
    f = _flavor(dbms)
    where = f" AND c.TABLE_SCHEMA={_lit(schema)}" if schema else ""
    skip = "('INFORMATION_SCHEMA','information_schema','pg_catalog','sys','mysql','performance_schema')"
    if f == "snowflake":
        return ("SELECT c.TABLE_SCHEMA AS s, c.TABLE_NAME AS t, MAX(tb.ROW_COUNT) AS n, MAX(tb.COMMENT) AS tc, "
                f"LISTAGG(c.COLUMN_NAME, '{SEP}') WITHIN GROUP (ORDER BY c.ORDINAL_POSITION) AS cols, "
                f"LEFT(LISTAGG(COALESCE(c.COMMENT, ''), '{SEP}') WITHIN GROUP (ORDER BY c.ORDINAL_POSITION), 4000) AS cc "
                "FROM INFORMATION_SCHEMA.COLUMNS c JOIN INFORMATION_SCHEMA.TABLES tb ON tb.TABLE_SCHEMA=c.TABLE_SCHEMA AND tb.TABLE_NAME=c.TABLE_NAME "
                f"WHERE c.TABLE_SCHEMA NOT IN {skip}{where} GROUP BY 1, 2 ORDER BY 1, 2")
    if f == "postgres":
        where = f" AND c.table_schema={_lit(schema)}" if schema else ""
        return ("SELECT c.table_schema AS s, c.table_name AS t, MAX(GREATEST(cl.reltuples, 0))::bigint AS n, MAX(obj_description(cl.oid)) AS tc, "
                f"string_agg(c.column_name, '{SEP}' ORDER BY c.ordinal_position) AS cols, "
                f"LEFT(string_agg(COALESCE(col_description(cl.oid, c.ordinal_position::int), ''), '{SEP}' ORDER BY c.ordinal_position), 4000) AS cc "
                "FROM information_schema.columns c JOIN pg_namespace ns ON ns.nspname=c.table_schema "
                "JOIN pg_class cl ON cl.relnamespace=ns.oid AND cl.relname=c.table_name "
                f"WHERE c.table_schema NOT IN {skip}{where} GROUP BY 1, 2 ORDER BY 1, 2")
    if f == "sqlserver":
        return (f"SELECT c.TABLE_SCHEMA AS s, c.TABLE_NAME AS t, NULL AS n, NULL AS tc, STRING_AGG(CAST(c.COLUMN_NAME AS NVARCHAR(MAX)), '{SEP}') AS cols, NULL AS cc "
                f"FROM INFORMATION_SCHEMA.COLUMNS c WHERE c.TABLE_SCHEMA NOT IN {skip}{where} GROUP BY c.TABLE_SCHEMA, c.TABLE_NAME ORDER BY 1, 2")
    if f == "mysql":
        return ("SELECT c.TABLE_SCHEMA AS s, c.TABLE_NAME AS t, MAX(tb.TABLE_ROWS) AS n, MAX(tb.TABLE_COMMENT) AS tc, "
                f"GROUP_CONCAT(c.COLUMN_NAME ORDER BY c.ORDINAL_POSITION SEPARATOR '{SEP}') AS cols, "
                f"LEFT(GROUP_CONCAT(COALESCE(c.COLUMN_COMMENT, '') ORDER BY c.ORDINAL_POSITION SEPARATOR '{SEP}'), 4000) AS cc "
                "FROM INFORMATION_SCHEMA.COLUMNS c JOIN INFORMATION_SCHEMA.TABLES tb ON tb.TABLE_SCHEMA=c.TABLE_SCHEMA AND tb.TABLE_NAME=c.TABLE_NAME "
                f"WHERE c.TABLE_SCHEMA NOT IN {skip}{where} GROUP BY 1, 2 ORDER BY 1, 2")
    return None


def _paged(dbms: str, sql: str, page: int) -> str:
    offset = page * PAGE
    if _flavor(dbms) == "sqlserver":
        return f"{sql} OFFSET {offset} ROWS FETCH NEXT {PAGE} ROWS ONLY"
    return f"{sql} LIMIT {PAGE} OFFSET {offset}"


def catalog_tables(m, live, info: dict[str, Any], schema: str | None, deadline: float | None = None) -> dict[str, list[dict[str, Any]]] | None:
    """{schema: [{table, rows, comment, columns: [{name, comment}]}]} from the source's catalog views, page by page;
    None when the source has none we can read"""
    sql = _catalog_sql(info["dbms"], schema)
    if not sql:
        return None
    out: dict[str, list[dict[str, Any]]] = {}
    page = 0
    while True:
        try:
            rows = live.run_sql(m, info["id"], _paged(info["dbms"], sql, page))
        except RuntimeError:
            return out or None
        for r in rows:
            names = str(r.get("cols") or "").split(SEP)
            notes = str(r.get("cc") or "").split(SEP) + [""] * len(names)
            out.setdefault(r["s"], []).append({"table": r["t"], "rows": _int(r.get("n")), "comment": r.get("tc") or "",
                                               "columns": [{"name": n, "comment": notes[i]} for i, n in enumerate(names) if n]})
        if len(rows) < PAGE or page >= 199 or (deadline and time.monotonic() > deadline):
            return out
        page += 1


def schema_tables(m, live, matrix, info: dict[str, Any], schema: str) -> tuple[list[dict[str, Any]], str]:
    """one schema's tables with their columns and comments ("catalog views"), or only their names from Strategy's
    catalog when the source has no catalog views we can read ("names")"""
    got = catalog_tables(m, live, info, schema)
    if got:
        return got.get(schema, []), "catalog views"
    return [{"table": n, "rows": None, "comment": "", "columns": []} for n in matrix.list_tables(m, info["id"], schema)], "names"


def _int(v) -> int | None:
    try:
        return int(float(v)) if v is not None else None
    except (TypeError, ValueError):
        return None


# ── scoring ──────────────────────────────────────────────────────────────────────────────────────────────────────────
def score_table(t: dict[str, Any], want: list[str], usage: dict[str, int], referenced: set[str]) -> tuple[float, list[str]]:
    """how well a table fits the description: its name (3), its columns (1.5 each word, at most twice), comments (1),
    a table the references name (+3), tables existing models already use (a little), empty tables (less)"""
    name_w = words(t["table"])
    col_w = [words(c["name"]) for c in t["columns"]]
    text = " ".join([t.get("comment") or ""] + [c.get("comment") or "" for c in t["columns"]]).casefold()
    score, why = 0.0, []
    used_name: set[str] = set()
    used_cols: set[str] = set()                         # a word of a name counts for one term only ("plant" ≈ "production")
    for term in want:
        vs = {term} | SYN.get(term, set())
        if (name_w - used_name) & vs:
            used_name |= name_w & vs
            score += 3.0 if term in name_w else 2.4
            why.append(f"its name says {term}")
            continue
        cols = [c["name"] for c, w in zip(t["columns"], col_w) if w & vs and c["name"] not in used_cols]
        if cols:
            used_cols.update(cols)
            score += 1.5 * min(2, len(cols)) * (1 if any(term in w for w in col_w) else 0.8)
            why.append(f"{', '.join(cols[:2])} {'match' if len(cols) > 1 else 'matches'} {term}")
            continue
        if any(re.search(r"(?<![a-z])" + re.escape(v) + r"[a-z]{0,3}(?![a-z])", text) for v in vs):
            score += 1.0
            why.append(f"its description mentions {term}")
    if t["table"].casefold() in referenced:
        score += 3.0
        why.append("your references name it")
    used = usage.get(t["table"].casefold(), 0)
    if used and score:
        score += min(1.0, 0.4 * math.log2(1 + used))
        why.append(f"{used} existing model{'s use' if used > 1 else ' uses'} it")
    if t.get("rows") == 0:
        score *= 0.5
        why.append("it is empty")
    return round(score, 2), why


def _keyish(col: str) -> bool:
    return bool(mp.KEYISH.search(col)) or col.casefold().endswith(("_id", "_key", "_code", "_sk"))


def find(m, query: str, scopes: list[dict[str, Any]] | None = None, *, references: list[dict[str, Any]] | None = None,
         usage: dict[str, int] | None = None, budget: float = 120.0, max_tables: int = 12, log=lambda s: None) -> dict[str, Any]:
    """{picked: [{datasource_id, datasource, dbms, schema, table, score, why, role}], read: [...], left: [...], terms}"""
    import mosaic_live as live
    import mosaic_matrix as matrix
    deadline = time.monotonic() + budget
    refs = references or []
    want = terms(query + " " + " ".join(r.get("text", "")[:2000] for r in refs if r.get("kind") in ("document", "data", "image")))
    referenced = {str(e).split(".")[-1].strip('"`[] ').casefold() for r in refs for e in (r.get("entities") or [])}
    use = {k.casefold(): v for k, v in (usage or {}).items()}
    # where to look: the named scopes, else every source this person can reach
    if scopes:
        targets = scopes
    else:
        rows = m.get("/api/datasources").json()
        targets = [{"datasource": d["id"]} for d in (rows.get("datasources") if isinstance(rows, dict) else rows) or [] if d.get("id")]
    cache: dict[str, dict] = {}
    work: list[tuple[float, dict[str, Any], str, list[str]]] = []
    pre: dict[tuple[str, str], list[dict[str, Any]]] = {}    # schemas already read with their whole source
    for sc in targets:
        try:
            info = live.datasource(m, sc["datasource"], cache)
        except Exception:  # noqa: BLE001 - a source that cannot be read is left out and said
            log(f"  · {sc['datasource']}: not readable, left out")
            continue
        schemas = [sc["schema"]] if sc.get("schema") else []
        if not schemas and time.monotonic() < deadline:
            whole = catalog_tables(m, live, info, None, deadline)      # every schema at once, when the source allows it
            if whole is not None:
                log(f"  · {info['name']}: {len(whole)} schemas, {sum(len(x) for x in whole.values())} tables read from its catalog")
                for schema, tables in whole.items():
                    pre[(info["id"], schema)] = tables
                    hint = len(words(schema) & {x for w in want for x in {w} | SYN.get(w, set())}) * 2
                    work.append((hint, info, schema, sc.get("tables") or []))
                continue
        if not schemas:
            try:
                schemas = matrix.list_schemas(m, info["id"])
            except Exception:  # noqa: BLE001
                log(f"  · {info['name']}: its schemas could not be listed, left out")
                continue
        for schema in schemas:
            # schemas whose names fit, or whose tables existing models use, are read first
            hint = len(words(schema) & {x for w in want for x in {w} | SYN.get(w, set())}) * 2 + len(words(info["name"]) & set(want))
            work.append((hint, info, schema, sc.get("tables") or []))
    work.sort(key=lambda x: -x[0])
    log(f"→ Searching the catalog of {len(work)} schema{'s' if len(work) != 1 else ''} for: {', '.join(want[:12]) or 'everything'}…")
    found: list[dict[str, Any]] = []
    read, left = [], []
    for i, (hint, info, schema, patterns) in enumerate(work):
        if time.monotonic() > deadline and (info["id"], schema) not in pre:
            left = [f"{w[1]['name']}/{w[2]}" for w in work[i:]]
            log(f"  · time budget reached: {len(left)} schema{'s' if len(left) != 1 else ''} not read")
            break
        try:
            tables, how = (pre[(info["id"], schema)], "catalog views") if (info["id"], schema) in pre else schema_tables(m, live, matrix, info, schema)
        except Exception as e:  # noqa: BLE001 - one schema that cannot be read never ends the search
            log(f"  {info['name']}/{schema}: not readable ({str(e)[:80]})")
            continue
        if patterns:
            tables = [t for t in tables if any(fnmatch.fnmatchcase(t["table"].upper(), p.upper()) for p in patterns)]
        best = None
        for t in tables:
            s, why = score_table(t, want, use, referenced)
            row = {"datasource_id": info["id"], "datasource": info["name"], "dbms": info["dbms"], "schema": schema, "table": t["table"],
                   "score": s, "why": why, "rows": t.get("rows"), "columns": [c["name"] for c in t["columns"]], "read": how}
            found.append(row)
            if s and (best is None or s > best["score"]):
                best = row
        read.append(f"{info['name']}/{schema}")
        log(f"  {info['name']}/{schema}: {len(tables)} tables" + (f"; best {best['table']} ({best['score']})" if best else "; nothing matches"))
    found.sort(key=lambda r: -r["score"])
    top = [r for r in found if r["score"] > 0]
    floor = max(2.0, (top[0]["score"] * 0.35) if top else 0)
    picked = [dict(r, role="match") for r in top if r["score"] >= floor][: max(1, max_tables // 2 + 1)] if top else []
    # the tables they join to: in the same schema, sharing a key column (from the metadata, no data read)
    for p in list(picked):
        keys = {c.casefold() for c in p["columns"] if _keyish(c)}
        mates = [r for r in found if r["schema"] == p["schema"] and r["datasource_id"] == p["datasource_id"]
                 and not any(q["table"] == r["table"] and q["schema"] == r["schema"] and q["datasource_id"] == r["datasource_id"] for q in picked)
                 and keys & {c.casefold() for c in r["columns"] if _keyish(c)}]
        for r in sorted(mates, key=lambda r: -r["score"]):
            if len(picked) >= max_tables:
                break
            shared = sorted(keys & {c.casefold() for c in r["columns"] if _keyish(c)})
            picked.append(dict(r, role="join", why=[f"joins {p['table']} on {', '.join(shared[:2])}"] + r["why"]))
    return {"terms": want, "picked": picked[:max_tables], "read": read, "left": left, "candidates": len(top)}
