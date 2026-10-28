"""Live reads for the plan → check → apply → prove builder (see ../REBUILD.md): sign-in, the catalog of the selected
tables, and a data profile of the columns that matter (row counts, distinct keys, nulls), read through Strategy so the
same code covers every source Strategy can query. Nothing here writes to Strategy.

A source that cannot run SQL through Strategy (an API connector such as Salesforce or Google Drive) still gets a
catalog; its profile says `measured: false` and the plan falls back to names and types, which the check reports.
"""
from __future__ import annotations

import os
import re
import sys
import types
from typing import Any, Callable

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_mosaic as bm  # noqa: E402  (session, catalog helpers, datatype mapping)

SQL_ROW_LIMIT = 1000


# ── sign-in ──────────────────────────────────────────────────────────────────────────────────────────────────────────
def credentials_block(path: str, env_name: str) -> dict[str, str]:
    """login / url / password of one environment in an operator credentials file (`<name>:` then indented `key: value`
    lines). Quotes around a value are part of the file's notation, not of the value."""
    lines = open(path, encoding="utf-8").read().splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if line.strip().lower() == f"{env_name.lower()}:")
    except StopIteration:
        raise SystemExit(f"no '{env_name}:' block in {path}") from None
    out: dict[str, str] = {}
    for line in lines[start + 1:]:
        m = re.match(r"\s+(\w+)\s*:\s*(.+)$", line)
        if not m:
            break
        out[m.group(1).lower()] = m.group(2).strip().strip("\"'")
    return out


def sign_in(*, base: str, user: str, password: str, project_id: str, identity: bool = True) -> bm.MSTR:
    base = base.split("/MicroStrategyLibrary")[0].rstrip("/") + "/MicroStrategyLibrary"
    m = bm.MSTR(types.SimpleNamespace(base=base, project_id=project_id, user=user, password=password, login_mode=1, verbose=False))
    m.login(identity=identity)
    return m


def sign_in_from_env() -> bm.MSTR:
    """MSTR_BASE / MSTR_USER / MSTR_PASSWORD / MSTR_PROJECT_ID, or MSTR_CREDENTIALS_FILE + MSTR_CREDENTIALS_ENV"""
    project = os.environ.get("MSTR_PROJECT_ID", "")
    missing = [] if os.environ.get("MSTR_CREDENTIALS_FILE") else [k for k in ("MSTR_BASE", "MSTR_USER", "MSTR_PASSWORD") if not os.environ.get(k)]
    if missing:                                     # one line a person can act on, never a traceback
        raise SystemExit("sign-in: set " + ", ".join(missing) + " (or MSTR_CREDENTIALS_FILE and MSTR_CREDENTIALS_ENV)")
    if os.environ.get("MSTR_CREDENTIALS_FILE"):
        blk = credentials_block(os.environ["MSTR_CREDENTIALS_FILE"], os.environ.get("MSTR_CREDENTIALS_ENV", "studio"))
        return sign_in(base=blk["url"], user=blk["login"], password=blk["password"], project_id=project)
    return sign_in(base=os.environ["MSTR_BASE"], user=os.environ["MSTR_USER"], password=os.environ["MSTR_PASSWORD"], project_id=project)


def load_json(path: str, what: str):
    """a JSON file the command was given, or one line saying what is wrong with it (exit, no traceback)"""
    import json
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except OSError as e:
        raise SystemExit(f"{what}: cannot read {path} ({e.strerror or e})") from None
    except ValueError as e:
        raise SystemExit(f"{what}: {path} is not valid JSON ({e})") from None


# ── SQL through a datasource ─────────────────────────────────────────────────────────────────────────────────────────
def quote(dbms: str, ident: str) -> str:
    # Delimiter doubling alone is unsafe when a database also honors backslash
    # escapes. Refuse ambiguous names rather than depending on connection modes.
    if not isinstance(ident, str) or not ident or re.search(r"[\\\x00-\x1f\x7f]", ident):
        raise ValueError("SQL identifiers must be nonempty and contain no backslashes or control characters")
    d = (dbms or "").lower()
    if any(k in d for k in ("bigquery", "google", "mysql", "mariadb", "databricks", "spark", "hive", "starrocks")):
        return "`" + ident.replace("`", "``") + "`"
    return '"' + ident.replace('"', '""') + '"'


def table_ref(table: dict[str, Any]) -> str:
    q = lambda s: quote(table.get("dbms", ""), s)  # noqa: E731
    return f"{q(table['schema'])}.{q(table['table'])}" if table.get("schema") else q(table["table"])


def run_sql(m: bm.MSTR, datasource_id: str, sql: str) -> list[dict[str, Any]]:
    """rows as dicts; raises RuntimeError with Strategy's message when the source refuses the SQL"""
    r = m.post(f"/api/datasources/{datasource_id}/sqlQuery", json={"sqlStatement": sql})
    if not r.ok:
        raise RuntimeError(bm.format_mstr_error(r))
    body = r.json()
    names = [c.get("name") for c in body.get("columns") or []]
    cols = body.get("data") or []                       # column-major: one array per column
    n = max((len(c) for c in cols), default=0)
    return [{names[j].lower(): (cols[j][i] if i < len(cols[j]) else None) for j in range(len(names))} for i in range(n)]


# ── catalog ──────────────────────────────────────────────────────────────────────────────────────────────────────────
def datasource(m: bm.MSTR, name_or_id: str, cache: dict[str, dict] | None = None) -> dict[str, Any]:
    cache = {} if cache is None else cache
    ds_id = bm.resolve_instance_id(m, name_or_id)
    if ds_id not in cache:
        j = m.get(f"/api/datasources/{ds_id}").json()
        cache[ds_id] = {"id": ds_id, "name": j.get("name") or name_or_id, "dbms": (j.get("dbms") or {}).get("name") or ""}
    return cache[ds_id]


def catalog(m: bm.MSTR, refs: list[dict[str, str]], errors: list[dict] | None = None) -> dict[str, Any]:
    """refs: [{datasource (name or id), schema, table}] → {tables: [...]} with exact column names and mapped types"""
    cache: dict[str, dict] = {}
    tables = []
    for ref in refs:
        try:
            ds = datasource(m, ref["datasource"], cache)
            md = bm.fetch_table_metadata(m, ds["id"], ref["schema"], ref["table"])
        except RuntimeError as exc:
            if errors is None:
                raise
            errors.append({"datasource": ref["datasource"], "schema": ref["schema"], "table": ref["table"],
                           "stage": "columns", "error": type(exc).__name__})
            continue
        cols = []
        for c in md["columns"]:
            name = c.get("name") or c.get("columnName")
            dt = c.get("dataType")
            dt = {"type": dt} if isinstance(dt, str) else dt if isinstance(dt, dict) else {"type": "utf8_char"}
            description = c.get("description") or c.get("comment") or c.get("remarks")
            cols.append({"name": name, "dataType": bm.sot.normalize_datatype(dt),
                         **({"description": str(description)[:2000]} if description else {})})
        description = md.get("description") or md.get("comment") or md.get("remarks")
        tables.append({"datasource_id": ds["id"], "datasource": ds["name"], "dbms": ds["dbms"], "schema": ref["schema"],
                       "table": ref["table"], "columns": cols, **({"description": str(description)[:2000]} if description else {})})
    return {"tables": tables}


# ── profile ──────────────────────────────────────────────────────────────────────────────────────────────────────────
def profile(m: bm.MSTR, cat: dict[str, Any], columns: dict[str, list[str]],
            sql: Callable[[bm.MSTR, str, str], list[dict]] = run_sql) -> dict[str, Any]:
    """per table: rows, and for each named column its distinct and null counts. `columns` maps a table name to the
    columns worth measuring (key candidates). One query per table."""
    out: dict[str, Any] = {}
    for t in cat["tables"]:
        want = [c for c in columns.get(t["table"], []) if any(x["name"] == c for x in t["columns"])]
        q = lambda s: quote(t["dbms"], s)  # noqa: E731
        parts = ["COUNT(*) AS n_rows"]
        for i, c in enumerate(want):
            parts += [f"COUNT(DISTINCT {q(c)}) AS d{i}", f"COUNT({q(c)}) AS v{i}"]
        try:
            row = sql(m, t["datasource_id"], f"SELECT {', '.join(parts)} FROM {table_ref(t)}")[0]  # nosec B608  # identifiers go through quote/table_ref; only fixed COUNT projections
            n = int(row["n_rows"])
            out[t["table"]] = {"measured": True, "rows": n,
                               "distinct": {c: int(row[f"d{i}"]) for i, c in enumerate(want)},
                               "nulls": {c: n - int(row[f"v{i}"]) for i, c in enumerate(want)}}
        except (RuntimeError, KeyError, ValueError, IndexError) as e:
            out[t["table"]] = {"measured": False, "reason": str(e)[:300]}
    return out
