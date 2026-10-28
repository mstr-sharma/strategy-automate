"""Discover what is in a database and recommend models to build, mostly from metadata (see StrategyAce
docs/MODEL_RECOMMENDER.md and ../REBUILD.md).

  python3 mosaic_discover.py scan --source "Warehouse:DEMO:SD_EREADER_*" --source "Postgres:public:EREADER_*" --out graph.json
  python3 mosaic_discover.py recommend --graph graph.json [--min-tables 2 --max-tables 8 --cross-store prefer] --out recs.json

scan() reads, without scanning tables: the table list, row counts from statistics, declared primary and foreign keys
(Postgres information schema; Snowflake GET_DDL for the tables that declare keys), and columns from Strategy's catalog
for the tables in scope. infer() turns that into entities (a business thing and the column that identifies it in each
table, in that table's spelling) and links between tables, each with its evidence and a confidence. recommend() ranks
candidate models (a fact table with what it reaches) and drafts a specification for each. All but scan() are pure.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mosaic_plan as mp  # noqa: E402

EVIDENCE = {"declared": 0.95, "primary_key_name": 0.75, "same_name": 0.55, "suffix_name": 0.5, "measured": 0.85, "history": 0.9, "statistics": 0.75, "metadata_conformance": 0.65}
UNRELATED_NAME = 0.35        # the same key name in two unrelated table families, until the data says they match
GENERIC_NAME = 0.45          # a key name two tables share where neither owns it (below the default 0.5 bar)
DEFAULT_OPTIONS = {
    "min_tables": 2, "max_tables": 8, "cross_store": "allow",          # allow | prefer | avoid
    "signals": {"declared": True, "same_name": True, "family": True},
    "weights": {}, "exclude_patterns": ["*_BAK", "*_BACKUP", "TMP_*", "*_TMP", "*_OLD"], "modeled_tables": [],
    "min_confidence": 0.5, "skip_data_check": True,
}


def tkey(t: dict) -> str:
    return f"{t['datasource_id']}/{t['schema']}/{t['table']}"


# ── scan (live) ──────────────────────────────────────────────────────────────────────────────────────────────────────
def _stats_sql(dbms: str, schema: str) -> str | None:
    """the row counts the database keeps for a schema's tables (its catalog, no table counted): see mosaic_dialects"""
    import mosaic_dialects as dialects
    return dialects.row_counts_sql(dbms, schema)


def _declared_keys(m, live, info: dict, schema: str, tables: set[str], errors: list[dict] | None = None) -> tuple[dict, list]:
    """{table: [pk columns]}, [fk {child, child_cols, parent, parent_cols}] for tables in scope"""
    import mosaic_dialects as dialects
    d, pks, fks = info["dbms"].lower(), {}, []
    sqls = dialects.keys_sqls(info["dbms"], schema)
    grouped: dict[tuple, list[dict]] = {}
    try:
        if sqls:
            # every kind of database that lists its keys in catalog views (PostgreSQL, Redshift, SQL Server and Fabric,
            # MySQL family, Databricks Unity Catalog, BigQuery, Oracle, Db2, SAP HANA, Exasol)
            for r in (r for sql in sqls for r in live.run_sql(m, info["id"], sql)):
                if r["t"] not in tables:
                    continue
                if str(r["k"]).upper().startswith("PRIMARY"):
                    if r["c"] not in pks.setdefault(r["t"], []):
                        pks[r["t"]].append(r["c"])
                elif r.get("pt") and r.get("pc"):
                    # One constraint can have several components. Treating each catalog row as a whole FK creates
                    # false single-column joins (tenant_id alone must never join every row in a composite key).
                    key = (r["t"], r.get("ps") or schema, r["pt"], r.get("n") or f"{r['c']}:{r['pc']}")
                    grouped.setdefault(key, []).append(r)
            for (child, parent_schema, parent, name), rows in grouped.items():
                pairs = list(dict.fromkeys((r["c"], r["pc"]) for r in sorted(rows, key=lambda r: (int(r.get("o") or 0), str(r["c"]), str(r["pc"])))))
                # Some ANSI catalogs return a cross product for composite keys. Without an ordinal mapping it is
                # unsafe to invent a pairing; retain the relationship as review evidence rather than single FKs.
                ambiguous = len({c for c, _ in pairs}) != len(pairs) or len({c for _, c in pairs}) != len(pairs)
                fks.append({"child": child, "child_cols": [c for c, _ in pairs], "parent": parent,
                            "parent_schema": parent_schema, "parent_cols": [c for _, c in pairs], "name": name,
                            **({"ambiguous_columns": True} if ambiguous else {})})
        elif "snowflake" in d:
            if not (dialects.safe_name(schema) and all(dialects.safe_name(t) for t in tables)):
                return pks, fks                         # a name that cannot be quoted safely is never pasted into SQL
            have = {r["t"] for r in live.run_sql(m, info["id"], "SELECT DISTINCT TABLE_NAME AS t FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS "  # nosec B608  # identifiers are quoted; literals reject backslashes and double single quotes
                                                 f"WHERE TABLE_SCHEMA={dialects.lit(schema)} AND CONSTRAINT_TYPE IN ('PRIMARY KEY','FOREIGN KEY')")}
            for t in sorted(have & tables):
                ref = live.quote(info["dbms"], schema) + "." + live.quote(info["dbms"], t)
                ddl = live.run_sql(m, info["id"], f"SELECT GET_DDL('TABLE', {dialects.lit(ref)}) AS d")[0]["d"] or ""
                for kind, cols, ref, refcols in re.findall(r"(?i)(primary key|foreign key)\s*\(([^)]*)\)(?:\s*references\s+([\w.\"]+)\s*\(([^)]*)\))?", ddl):
                    cols_l = [c.strip().strip('"') for c in cols.split(",")]
                    if kind.lower() == "primary key":
                        pks[t] = cols_l
                    elif ref:
                        pt = ref.split(".")[-1].strip('"')
                        parts = [x.strip('"') for x in ref.split(".")]
                        fks.append({"child": t, "child_cols": cols_l, "parent": pt, "parent_schema": parts[-2] if len(parts) >= 2 else schema,
                                    "parent_cols": [c.strip().strip('"') for c in refcols.split(",")], "name": ""})
    except RuntimeError as exc:
        if errors is not None:
            errors.append({"datasource": info["id"], "schema": schema, "stage": "keys", "error": type(exc).__name__})
    return pks, fks


def scan(m, scopes: list[dict], options: dict | None = None, log=lambda s: None) -> dict:
    """scopes: [{datasource, schema, patterns:[glob...]}] → the source graph's raw facts"""
    import mosaic_live as live
    import mosaic_matrix as mx
    import mosaic_dialects as dialects
    opts = {**DEFAULT_OPTIONS, **(options or {})}
    graph: dict[str, Any] = {"tables": {}, "fks": [], "scopes": scopes, "selected_tables": list(opts.get("selected_tables") or []), "metadata_only": opts.get("skip_data_check", True), "coverage": [], "errors": []}
    log(f"→ Reading the tables in {len(scopes)} schema{'s' if len(scopes) != 1 else ''}…")
    for sc in scopes:
        coverage = {"datasource": sc["datasource"], "schema": sc["schema"], "listed": 0, "selected": 0, "catalog_tables": 0,
                    "tables": "unavailable", "keys": "unavailable", "statistics": "unavailable", "columns": "unavailable"}
        graph["coverage"].append(coverage)
        try:
            info = live.datasource(m, sc["datasource"])
            log(f"  · listing the tables in {info['name']}/{sc['schema']}")
            names = mx.list_tables(m, info["id"], sc["schema"])
        except RuntimeError as exc:
            graph["errors"].append({"datasource": sc["datasource"], "schema": sc["schema"], "stage": "tables", "error": type(exc).__name__})
            log(f"  · table metadata unavailable for {sc['schema']}; continuing with other sources")
            continue
        coverage.update(datasource_id=info["id"], listed=len(names), tables="available")
        # how big the schema really is, whatever part of it is scanned: a few tables picked out of a large catch-all
        # schema are not one small dataset (infer's small-schema and star rules read this)
        graph.setdefault("schema_sizes", {})[f"{info['id']}/{sc['schema']}"] = len(names)
        pats = sc.get("patterns") or ["*"]
        # A real catalog identifier wins over glob syntax: FACT[1] is not FACT1, and a literal * or ? in a table
        # name is preserved. Patterns remain available when no table has that exact name.
        exact = {p: {n for n in names if n == p} or {n for n in names if n.casefold() == p.casefold()} for p in pats}
        explicit = {str(p).casefold() for p in pats if exact[p] or not any(x in str(p) for x in "*?[")}
        names = [n for n in names if any(n in exact[p] if exact[p] else fnmatch.fnmatchcase(n.upper(), p.upper()) for p in pats)
                 and (n.casefold() in explicit or f"{info['id']}/{sc['schema']}/{n}" in graph["selected_tables"]
                      or not any(fnmatch.fnmatchcase(n.upper(), p.upper()) for p in opts["exclude_patterns"]))]
        graph["selected_tables"] = sorted(set(graph["selected_tables"]) | {f"{info['id']}/{sc['schema']}/{n}" for n in names if n.casefold() in explicit})
        if len(names) > opts.get("max_scan_tables", 200):
            raise ValueError(f"{len(names)} tables match in {info['name']}/{sc['schema']}; narrow the patterns (limit {opts.get('max_scan_tables', 200)})")
        coverage["selected"] = len(names)
        log(f"  · reading catalog row estimates and declared keys for {len(names)} tables")
        rows = {}
        stats = _stats_sql(info["dbms"], sc["schema"])
        if stats:
            try:
                rows = {r["t"]: int(float(r["n"])) for r in live.run_sql(m, info["id"], stats) if r.get("n") is not None and float(r["n"]) >= 0}
                coverage["statistics"] = "available"
            except (RuntimeError, ValueError, TypeError) as exc:
                rows = {}
                graph["errors"].append({"datasource": info["id"], "schema": sc["schema"], "stage": "row_estimates", "error": type(exc).__name__})
        else:
            coverage["statistics"] = "unsupported"
        key_errors: list[dict] = []
        pks, fks = _declared_keys(m, live, info, sc["schema"], set(names), errors=key_errors)
        coverage["keys"] = "unavailable" if key_errors else "available" if dialects.keys_sqls(info["dbms"], sc["schema"]) or "snowflake" in info["dbms"].lower() else "unsupported"
        graph["errors"].extend(key_errors)
        log(f"  · reading the columns of {len(names)} tables")
        cat = live.catalog(m, [{"datasource": info["id"], "schema": sc["schema"], "table": n} for n in names], errors=graph["errors"])
        coverage["catalog_tables"] = len(cat["tables"])
        coverage["columns"] = "complete" if len(cat["tables"]) == len(names) else "partial" if cat["tables"] else "unavailable"
        log(f"  {info['name']}/{sc['schema']}: {len(names)} tables")
        for t in cat["tables"]:
            graph["tables"][tkey(t)] = {**t, "rows": rows.get(t["table"]), "pk": pks.get(t["table"], []), "family": _family_key(t["table"], t["schema"], t["datasource_id"])}
        for fk in fks:
            base = f"{info['id']}/{sc['schema']}/"
            graph["fks"].append({**fk, "child": base + fk["child"], "parent": f"{info['id']}/{fk.get('parent_schema') or sc['schema']}/{fk['parent']}"})
    return graph


def measure_keys(m, graph: dict, options: dict | None = None, budget: int = 80, log=lambda s: None) -> dict:
    """which candidate keys are unique where: one query per table counting rows and the distinct values of the columns
    its entities use (graph['profile'][table key] = {measured, rows, distinct, nulls}, the builder's own profile shape).
    Discovery homes an entity on a table where its key is unique, and the pre-build check judges keys as the build will."""
    import mosaic_live as live
    inferred = infer(graph, options)
    want: dict[str, set[str]] = {}
    for e in inferred["entities"]:
        for k, c in e["members"].items():
            want.setdefault(k, set()).add(c)
    prof = graph.setdefault("profile", {})
    todo = [k for k in want if k not in prof][:budget]
    log(f"→ Measuring which keys are unique where ({len(todo)} table{'s' if len(todo) != 1 else ''})…")
    for k in todo:
        t = graph["tables"][k]
        try:
            got = live.profile(m, {"tables": [t]}, {t["table"]: sorted(want[k])[:12]})
            prof[k] = got.get(t["table"]) or {"measured": False}
            if prof[k].get("measured"):
                uniq = [c for c, d in prof[k]["distinct"].items() if d == prof[k]["rows"]]
                log(f"  {t['table']}: {prof[k]['rows']:,} rows{'; unique: ' + ', '.join(uniq) if uniq else ''}")
            else:
                log(f"  {t['table']}: not measurable; judged from its columns")
        except Exception as e:  # noqa: BLE001 - a table that cannot be measured is judged from its metadata
            prof[k] = {"measured": False, "reason": str(e)[:200]}
            log(f"  {t['table']}: not measurable ({str(e)[:100]})")
    return graph


def confirm(m, graph: dict, options: dict | None = None, budget: int = 40, log=lambda s: None) -> dict:
    """the data check for links only a shared name suggests across unrelated families: up to 100 distinct key values from
    one side, and how many of them the other side has (two small queries per link, any stores). Stored as
    graph['measured'][f'{home}|{other}'] = share found."""
    import mosaic_live as live
    inferred = infer(graph, options)
    measured = graph.setdefault("measured", {})
    todo = [l for l in inferred["links"] if "declared" not in l["evidence"] and "measured" not in l["evidence"] and f"{l['from']}|{l['to']}" not in measured]
    todo.sort(key=lambda l: "family" in l["evidence"])      # links across unrelated tables first, then within a dataset
    todo = todo[:budget]
    log(f"→ Checking links only a shared name suggests, against the data ({len(todo)} link{'s' if len(todo) != 1 else ''})…")
    for l in todo:
        home, other = graph["tables"][l["from"]], graph["tables"][l["to"]]
        hc, oc = l["columns"]
        try:
            vals = [r["v"] for r in live.run_sql(m, other["datasource_id"], f"SELECT DISTINCT {live.quote(other['dbms'], oc)} AS v FROM {live.table_ref(other)} "  # nosec B608  # identifiers are quoted; literals reject backslashes and double single quotes
                                                 f"WHERE {live.quote(other['dbms'], oc)} IS NOT NULL LIMIT 100") if r.get("v") not in (None, "") and "\\" not in str(r["v"])]  # a backslash escapes quotes in some databases
            if not vals:
                log(f"  {l['entity']}: {other['table']} → {home['table']}: no values to compare")
                continue
            listed = ", ".join("'" + str(v).replace("'", "''") + "'" for v in vals)
            found = live.run_sql(m, home["datasource_id"], f"SELECT COUNT(DISTINCT {live.quote(home['dbms'], hc)}) AS n FROM {live.table_ref(home)} "  # nosec B608  # identifiers are quoted; literals reject backslashes and double single quotes
                                                       f"WHERE CAST({live.quote(home['dbms'], hc)} AS VARCHAR(400)) IN ({listed})")[0]["n"]
            measured[f"{l['from']}|{l['to']}"] = round(int(float(found)) / len(vals), 2)
            log(f"  {l['entity']}: {other['table']} → {home['table']}: {int(float(found))}/{len(vals)} values found")
        except (RuntimeError, ValueError, KeyError, IndexError) as e:
            log(f"  {l['entity']}: {other['table']} → {home['table']}: not measurable ({str(e)[:100]})")
    return graph


def apply_references(graph: dict, refs: list[dict]) -> dict:
    """what the person's references say about the scanned tables (ERDs, data dictionaries, documents, data catalog and
    MDM exports, API descriptions, as Ace's reference reader extracts them): their relationships between scanned tables
    become declared keys, the tables they name or describe are marked as referenced, and their dictionaries are kept to
    name and describe the drafts. A reference that names a table found in more than one scanned schema is not guessed."""
    g = {**graph, "fks": list(graph.get("fks", [])), "referenced": {}, "dictionary": {"attributes": {}, "metrics": {}}}
    by_name: dict[str, list[str]] = {}
    for k, t in graph["tables"].items():
        by_name.setdefault(t["table"].casefold(), []).append(k)

    def one(name: str) -> str | None:
        raw = str(name).strip()
        direct = [k for k in graph["tables"] if k.casefold() == raw.casefold()]
        if len(direct) == 1:
            return direct[0]
        parts = [x.strip('"`[] ').casefold() for x in raw.split(".")]
        ks = by_name.get(parts[-1], [])
        if len(parts) >= 2:
            ks = [k for k in ks if graph["tables"][k]["schema"].casefold() == parts[-2]]
        if len(parts) >= 3:
            ks = [k for k in ks if parts[-3] in {str(graph["tables"][k].get("datasource") or "").casefold(),
                                                str(graph["tables"][k].get("datasource_id") or "").casefold()}]
        return ks[0] if len(ks) == 1 else None

    def column(key: str, name: str) -> str | None:
        return next((c["name"] for c in graph["tables"][key]["columns"] if c["name"].casefold() == name.strip('"`[] ').casefold()), None)

    def note(key: str | None, ref: str) -> None:
        if key and ref not in g["referenced"].setdefault(key, []):
            g["referenced"][key].append(ref)
    names = sorted(by_name, key=len, reverse=True)
    for r in refs or []:
        ref = str(r.get("name") or "reference")
        for rel in r.get("relationships") or []:
            parent, child = str(rel.get("parent") or ""), str(rel.get("child") or "")
            if "." in parent and "." in child:
                (pt, pc), (ct, cc) = parent.rsplit(".", 1), child.rsplit(".", 1)
                pk, ck = one(pt), one(ct)
                if pk and ck and pk != ck and column(pk, pc) and column(ck, cc):
                    g["fks"].append({"child": ck, "child_cols": [column(ck, cc)], "parent": pk, "parent_cols": [column(pk, pc)], "name": "reference: " + ref})
                note(pk, ref); note(ck, ref)
            else:
                note(one(parent), ref); note(one(child), ref)
        for e in r.get("entities") or []:
            note(one(e), ref)
        text = (r.get("text") or "")[:20000].casefold()
        for n in names:
            if len(n) >= 4 and re.search(r"(?<![a-z0-9_])" + re.escape(n) + r"(?![a-z0-9_])", text):
                for k in by_name[n] if len(by_name[n]) == 1 else []:
                    note(k, ref)
        for kind in ("attributes", "metrics"):
            for key, v in ((r.get("dictionary") or {}).get(kind) or {}).items():
                if isinstance(v, dict):
                    g["dictionary"][kind][str(key).casefold()] = v
                    note(one(str(key).rsplit(".", 1)[0]) if "." in str(key) else None, ref)
    return g


def _with_references(rec: dict, referenced: dict, dictionary: dict) -> None:
    """a recommendation the references support ranks higher and says so; the dictionaries name and describe its draft"""
    named = [(k, referenced[k]) for k in rec["table_keys"] if k in referenced]
    if named:
        refs = sorted({x for _, rs in named for x in rs})
        rec["score"] = round(rec["score"] + 0.05 * min(len(named), 4), 3)
        rec["references"] = refs
        rec["reasons"].append(f"{len(named)} of its tables {'is' if len(named) == 1 else 'are'} described in your references ({', '.join(refs[:3])})")
    taken = {a["name"] for a in rec["spec"]["attributes"]} | {m["name"] for m in rec["spec"]["metrics"]}
    for a in rec["spec"]["attributes"]:
        for f in a.get("forms", []):
            v = dictionary.get("attributes", {}).get(f"{f.get('table')}.{f.get('column')}".casefold())
            if v:
                if v.get("description") and not a.get("description"):
                    a["description"] = str(v["description"])[:500]
                if v.get("name") and f.get("category") == "ID" and v["name"] not in taken:
                    taken.discard(a["name"]); a["name"] = str(v["name"])[:120]; taken.add(a["name"])
                break
    for m in rec["spec"]["metrics"]:
        v = dictionary.get("metrics", {}).get(f"{m.get('table')}.{m.get('column')}".casefold()) or dictionary.get("attributes", {}).get(f"{m.get('table')}.{m.get('column')}".casefold())
        if v:
            if v.get("description") and not m.get("description"):
                m["description"] = str(v["description"])[:500]
            if v.get("name") and v["name"] not in taken:
                taken.discard(m["name"]); m["name"] = str(v["name"])[:120]; taken.add(m["name"])


def _pg_array(text: str | None) -> list[str]:
    """PostgreSQL's array text ({a,"b c",d}) as strings"""
    if not text or not text.startswith("{"):
        return []
    import csv
    import io
    return next(csv.reader(io.StringIO(text[1:-1]), quotechar='"', escapechar="\\"), [])


def catalog_stats(m, graph: dict, log=lambda s: None) -> dict:
    """the column statistics each database keeps for its query planner (PostgreSQL pg_stats, Oracle, Db2, MySQL),
    read from its catalog, never from a table: graph['stats'][table key][column] = {rows, distinct, nulls, values,
    low, high}. They say whether a key is unique and, for PostgreSQL, whether two columns hold the same kind of values."""
    import mosaic_dialects as dialects
    import mosaic_live as live
    stats = graph.setdefault("stats", {})
    by_schema: dict[tuple[str, str], list[str]] = {}
    for k, t in graph["tables"].items():
        by_schema.setdefault((t["datasource_id"], t["schema"]), []).append(k)
    for (ds, schema), keys in by_schema.items():
        t0 = graph["tables"][keys[0]]
        sql = dialects.column_stats_sql(t0.get("dbms", ""), schema)
        coverage = next((x for x in graph.get("coverage", []) if x.get("datasource_id") == ds and x.get("schema") == schema), None)
        if coverage is not None:
            coverage["column_statistics"] = "unavailable" if sql else "unsupported"
        if not sql:
            continue
        try:
            rows = live.run_sql(m, ds, sql)
        except RuntimeError as exc:
            graph.setdefault("errors", []).append({"datasource": ds, "schema": schema, "stage": "column_statistics", "error": type(exc).__name__})
            continue                                    # statistics are one signal among several
        if coverage is not None:
            coverage["column_statistics"] = "available"
        names = {graph["tables"][k]["table"]: k for k in keys}
        n = 0
        for r in rows:
            k = names.get(r.get("t"))
            if not k:
                continue
            total = float(r.get("rows_n") or 0)
            d = float(r.get("ndv") or 0)
            distinct = -d * total if d < 0 else d       # PostgreSQL: a negative n_distinct is a fraction of the rows
            nulls = float(r.get("nulls") or 0)
            nulls = nulls * total if nulls <= 1 and "mcv" in r else nulls
            hist = _pg_array(r.get("hist"))
            stats.setdefault(k, {})[r["c"]] = {"rows": total, "distinct": distinct, "nulls": nulls, "values": _pg_array(r.get("mcv"))[:100],
                                               "low": hist[0] if hist else None, "high": hist[-1] if hist else None}
            n += 1
        if n:
            log(f"  · {t0['datasource']}/{schema}: statistics for {n} columns")
    return graph


HISTORY_COLUMN = re.compile(r"(?i)^(valid|effective|eff|row|record|version|scd)_?(from|to|start|end|begin|until|thru)(_?(date|dt|ts|time|timestamp))?$|^(is_current|current_flag|curr_flag|is_latest|active_flag|dw_current)$")


def _history(t: dict) -> bool:
    """a dimension that keeps history (type 2): validity columns, or a current-row flag; its business key repeats"""
    names = [c["name"] for c in t.get("columns", [])]
    return sum(1 for n in names if HISTORY_COLUMN.search(n)) >= 2 or any(re.match(r"(?i)^(is_current|current_flag)$", n) for n in names)


def _stats_unique(st: dict | None) -> bool:
    return bool(st) and st["rows"] > 0 and st["distinct"] >= 0.99 * st["rows"] and st["nulls"] < 0.01 * st["rows"]


def _stats_overlap(a: dict | None, b: dict | None) -> float | None:
    """how much two columns' statistics agree: the share of one's common values found in the other's, else whether
    their value ranges overlap at all (1 or 0); None when the statistics cannot say"""
    if not a or not b:
        return None
    if a["values"] and b["values"]:
        small, big = (a, b) if len(a["values"]) <= len(b["values"]) else (b, a)
        inside = set(big["values"])
        if big["low"] is not None and big["high"] is not None:
            def within(v):
                try:
                    return float(big["low"]) <= float(v) <= float(big["high"])
                except ValueError:
                    return str(big["low"]) <= str(v) <= str(big["high"])
            return sum(1 for v in small["values"] if v in inside or within(v)) / len(small["values"])
        return sum(1 for v in small["values"] if v in inside) / len(small["values"])
    if None not in (a["low"], a["high"], b["low"], b["high"]):
        try:
            return 1.0 if float(a["low"]) <= float(b["high"]) and float(b["low"]) <= float(a["high"]) else 0.0
        except ValueError:
            return 1.0 if str(a["low"]) <= str(b["high"]) and str(b["low"]) <= str(a["high"]) else 0.0
    return None


def view_copies(tables: dict) -> set:
    """Explicitly named copies with the same columns. An arbitrary suffix or a numbered sibling is NOT proof of a copy:
    FACT_ORDERS_RETURNS and FACT_ORDERS_2026 may be separate processes or partitions with identical schemas."""
    norm = lambda n: re.sub(r"[^a-z0-9]", "", n.casefold())  # noqa: E731
    by_name = {(t["datasource_id"], t.get("schema"), t["table"].casefold()): k for k, t in tables.items()}
    cols_of: dict[str, set] = {}
    cols = lambda k: cols_of.setdefault(k, {norm(c["name"]) for c in tables[k]["columns"]})  # noqa: E731
    out = set()
    for k, t in tables.items():
        name = t["table"].casefold()
        for cut in range(1, len(name)):
            kk = by_name.get((t["datasource_id"], t.get("schema"), name[:cut]))
            if kk is None or kk == k or not re.fullmatch(r"_(v|vw|view|copy|backup|bak|raw|raw_upload|upload|stg|staging)", name[cut:]):
                continue
            if cols(k) and cols(k) == cols(kk):
                out.add(k)
                break
    return out


STAR_ROLE = re.compile(r"^(dim|dimension|d|fact|fct|f|lkp|lookup|lu|ref|rel|bridge|brg|agg|xref)_", re.I)


def _prefix_datasets(tables: dict[str, dict]) -> set[str]:
    """name prefixes that mark a self-contained dataset: three or more tables of one schema share the prefix and one of
    them is the lookup for a key its siblings carry (KEYSIGHT_PRODUCTS for PRODUCT_ID on KEYSIGHT_ORDER_LINES). Facts
    that only share a prefix (TXN_BOOKING4, TXN_BOOKING6) and look their keys up in LU_ tables are not one"""
    groups: dict[tuple, list[dict]] = {}
    for t in tables.values():
        parts = t["table"].split("_")
        if len(parts) < 2 or STAR_ROLE.match(t["table"]) or re.match(r"^SD_[A-Z]+_[A-Z0-9]+_\d{8}_\d{4}_", t["table"], re.I):
            continue
        groups.setdefault((t.get("datasource_id"), t.get("schema"), parts[0].casefold()), []).append(t)
    out = set()
    for (_, _, tok), members in groups.items():
        if len(members) < 3 or len(tok) < 3:
            continue
        def stem(x: str) -> str:
            x = x.casefold()
            return x[:-3] if x.endswith("ies") else x[:-1] if x.endswith("s") and not x.endswith("ss") else x
        subjects = {stem("_".join(t["table"].split("_")[1:])): t for t in members}
        for t in members:
            keys = {stem(re.sub(mp.KEY_COLUMN, "", c["name"]).strip("_")) for c in t["columns"] if mp.KEY_COLUMN.search(c["name"])}
            if any(s in keys and subjects[s] is not t for s in subjects):
                out.add(tok)
                break
    return out


def _family_key(name: str, schema: str = "", datasource: str = "") -> str:
    """related tables: a synthetic dataset's prefix; tables named by their star-schema role (DIM_, FACT_, LKP_, REF_,
    BRIDGE_…) in one schema are one family; else the first two words of the name"""
    m = re.match(r"^(SD_[A-Z]+_[A-Z0-9]+_\d{8}_\d{4})_", name, re.I)
    if m:
        return m.group(1)
    if STAR_ROLE.match(name):
        return f"{datasource}/{schema}#star"
    return "_".join(name.split("_")[:2])


# ── infer (pure) ─────────────────────────────────────────────────────────────────────────────────────────────────────
def infer(graph: dict, options: dict | None = None, curation: dict | None = None) -> dict:
    """entities and links with evidence. curation: {rejected_links:[[a,b]], confirmed_links:[[a,b]], names:{entity_key: name},
    excluded_tables:[key]} wins over evidence.

    An entity is one business thing inside one table family: the declared keys of a dataset, or a key name its tables
    share. Each has a home (the table whose primary key it is, else the table named after it, else the smallest). Links
    run from a home to every other table carrying it. The same key name in two families is a separate, weak link between
    their homes until the data agrees (confirm())."""
    opts = {**DEFAULT_OPTIONS, **(options or {})}
    sig, cur = opts["signals"], curation or {}
    tables = {k: t for k, t in graph["tables"].items() if k not in set(cur.get("excluded_tables", []))}
    # families are worked out again from the names, so a graph scanned before a rule changed reads the same as a new one
    tables = {k: {**t, "family": _family_key(t["table"], t.get("schema", ""), t.get("datasource_id", ""))} for k, t in tables.items()}
    # a system prefix three or more tables of a schema share (FSI_CUSTOMER, FSI_DEPOSIT_ACCOUNTS, FSI_FACILITIES) makes
    # them one family; a synthetic dataset's prefix and star-schema role names keep their own rule
    first: dict[tuple, int] = {}
    for t in tables.values():
        if "_" in t["table"]:
            first[(t.get("datasource_id"), t.get("schema"), t["table"].split("_")[0].casefold())] = first.get((t.get("datasource_id"), t.get("schema"), t["table"].split("_")[0].casefold()), 0) + 1
    per_schema: dict[tuple, int] = {}
    for t in tables.values():
        per_schema[(t.get("datasource_id"), t.get("schema"))] = per_schema.get((t.get("datasource_id"), t.get("schema")), 0) + 1
    for (ds, schema), n in list(per_schema.items()):
        per_schema[(ds, schema)] = max(n, (graph.get("schema_sizes") or {}).get(f"{ds}/{schema}", 0))
    star_schema = {(t.get("datasource_id"), t.get("schema")) for t in tables.values() if mp.STAR_DIM.match(t["table"])}
    datasets = _prefix_datasets(tables)
    for t in tables.values():
        # a named dataset (KEYSIGHT_ORDER_LINES, KEYSIGHT_PRODUCTS, KEYSIGHT_CUSTOMERS) is one family wherever its tables
        # live, so a schema holding several datasets beside a few DIM_/LU_ tables is not read as one star, and the same
        # dataset's tables in another schema or database join it
        tok = t["table"].split("_")[0].casefold() if "_" in t["table"] else ""
        if tok in datasets and not re.match(r"^SD_[A-Z]+_[A-Z0-9]+_\d{8}_\d{4}_", t["table"], re.I):
            t["family"] = f"dataset#{tok}"
            continue
        # a schema with dimension or lookup tables (DIM_, LU_) and up to 60 tables is one star: its facts join its
        # lookups whatever they are called (TXN_BOOKING with LU_RESIDENCY)
        if (t.get("datasource_id"), t.get("schema")) in star_schema and per_schema[(t.get("datasource_id"), t.get("schema"))] <= opts.get("star_schema", 60) \
                and not re.match(r"^SD_[A-Z]+_[A-Z0-9]+_\d{8}_\d{4}_", t["table"], re.I):
            t["family"] = f"{t.get('datasource_id')}/{t.get('schema')}#star"
            continue
        # a small schema (up to 20 tables, no synthetic datasets) is one dataset
        if per_schema[(t.get("datasource_id"), t.get("schema"))] <= opts.get("small_schema", 20) and not re.match(r"^SD_[A-Z]+_[A-Z0-9]+_\d{8}_\d{4}_", t["table"], re.I):
            t["family"] = f"{t.get('datasource_id')}/{t.get('schema')}#schema"
            continue
        tok = (t.get("datasource_id"), t.get("schema"), t["table"].split("_")[0].casefold())
        if "_" in t["table"] and first.get(tok, 0) >= 3 and not t["family"].endswith("#star") and not re.match(r"^SD_[A-Z]+_[A-Z0-9]+_\d{8}_\d{4}_", t["table"], re.I):
            t["family"] = f"{tok[0]}/{tok[1]}#{tok[2]}"
    selected = set(opts.get("selected_tables") or graph.get("selected_tables") or [])
    copies = view_copies(tables) - selected
    tables = {k: t for k, t in tables.items() if k not in copies}
    entities: dict[str, dict] = {}
    declared: set[tuple[str, str, str, str]] = set()
    composite_fks: list[dict] = []
    roles: dict[tuple[str, str, str], list[str]] = {}
    for fk in graph.get("fks", []):
        if fk.get("parent") in tables and fk.get("child") in tables and len(fk.get("parent_cols") or []) == len(fk.get("child_cols") or []) == 1:
            roles.setdefault((fk["parent"], fk["child"], fk["parent_cols"][0].casefold()), []).append(fk["child_cols"][0])

    def entity(key: str, name: str) -> dict:
        return entities.setdefault(key, {"key": key, "name": cur.get("names", {}).get(key, name), "members": {}, "home": None, "why": {}})

    def member(e: dict, k: str, col: str, why: str) -> None:
        e["members"].setdefault(k, col)
        e["why"].setdefault(k, set()).add(why)
    if sig.get("declared", True):
        for fk in graph.get("fks", []):
            if fk["child"] not in tables or fk["parent"] not in tables:
                continue
            if not fk.get("parent_cols") or len(fk["parent_cols"]) != len(fk.get("child_cols") or []):
                continue
            if len(fk["parent_cols"]) > 1 or fk.get("ambiguous_columns"):
                composite_fks.append(fk)
                continue
            pc, cc = fk["parent_cols"][0], fk["child_cols"][0]
            if not any(c["name"] == pc for c in tables[fk["parent"]]["columns"]) or not any(c["name"] == cc for c in tables[fk["child"]]["columns"]):
                continue
            role = len(set(roles.get((fk["parent"], fk["child"], pc.casefold()), []))) > 1
            e = entity(f"{fk['parent']}#{pc.casefold()}" + (f"#role:{cc.casefold()}" if role else ""),
                       mp._friendly(re.sub(mp.KEY_COLUMN, "", cc if role else pc).strip("_") or mp._short_table(tables[fk["parent"]]["table"])))
            if role:
                e["role_playing"] = True
            member(e, fk["parent"], pc, "declared"); member(e, fk["child"], cc, "declared")
            e["home"] = fk["parent"]
            declared.add((fk["parent"], fk["child"], pc, cc))
    if sig.get("same_name", True):
        clusters: dict[tuple[str, str], list[tuple[str, str]]] = {}
        # beyond …_ID/_KEY/_CODE names, a join key in a star: a column a dimension shares by name with another table
        # (SNAPSHOT_DATE in DIM_DATE and a fact), or one named for a table's subject (LOAN for DIM_LOAN)
        subjects = {(t["family"], mp.subject(t["table"]).replace(" ", "_").casefold()) for t in tables.values()}
        on_dim: dict[tuple[str, str], int] = {}
        anywhere: dict[tuple[str, str], int] = {}
        for t in tables.values():
            for c in t["columns"]:
                kk = (c["name"].casefold(), t["family"])
                anywhere[kk] = anywhere.get(kk, 0) + 1
                if mp.STAR_DIM.match(t["table"]):
                    on_dim[kk] = on_dim.get(kk, 0) + 1
        def joins(c, fam):
            n = c["name"].casefold()
            return (mp.KEY_COLUMN.search(c["name"]) or (fam, n) in subjects or (on_dim.get((n, fam)) and anywhere.get((n, fam), 0) >= 2)) \
                and n != "id" and not mp.TECHNICAL_COLUMN.search(c["name"]) and mp._family(c.get("dataType")) in ("number", "text", "time")
        for k, t in tables.items():
            for c in t["columns"]:
                if joins(c, t["family"]):
                    clusters.setdefault((c["name"].casefold(), t["family"]), []).append((k, c["name"]))
        for (name, fam), occ in clusters.items():
            existing = next((e for e in entities.values() if not e.get("role_playing") and any(e["members"].get(k, "").casefold() == name for k, _ in occ)), None)
            e = existing or entity(f"name#{name}#{fam}", mp._friendly(re.sub(mp.KEY_COLUMN, "", occ[0][1]).strip("_") or occ[0][1]))
            for k, c in occ:
                member(e, k, c, "primary_key_name" if [x.casefold() for x in tables[k].get("pk", [])] == [name] else "same_name")

    if sig.get("same_name", True):
        # one key named with a qualifier in another table of the family (SOURCE_PLANT_ID / PLANT_ID) is the same thing:
        # the qualified one's tables join the plain one's entity; the data check confirms or drops each such link
        def col(e):
            return next(iter(e["members"].values())).casefold()
        def fam(e):
            return tables[next(iter(e["members"]))]["family"]
        for a_ in list(entities.values()):
            for b_ in list(entities.values()):
                if a_ is b_ or a_["key"] not in entities or b_["key"] not in entities or fam(a_) != fam(b_) or a_.get("role_playing") or b_.get("role_playing"):
                    continue
                plain, qual = col(a_), col(b_)
                if qual.endswith("_" + plain) and mp.KEY_COLUMN.search(plain) and not any(k in a_["members"] for k in b_["members"]):
                    for k, c in b_["members"].items():
                        member(a_, k, c, "suffix_name")
                    if b_.get("home") and not a_.get("home"):
                        a_["home"] = b_["home"]
                    del entities[b_["key"]]
        # two entities called the same: the one keyed by a surrogate (…_KEY) says so
        names: dict[tuple[str, str], list[dict]] = {}
        for e in entities.values():
            names.setdefault((e["name"].casefold(), fam(e)), []).append(e)
        for same in names.values():
            if len(same) > 1:
                for e in same:
                    if col(e).endswith("_key") and e["key"] not in cur.get("names", {}):
                        e["name"] = e["name"] + " Key"

    def home_of(e: dict) -> str:
        if e["home"]:
            return e["home"]
        stem = re.sub(mp.KEY_COLUMN, "", next(iter(e["members"].values()))).strip("_").casefold().rstrip("s")
        def measures(k):       # a table of measures is a fact: an entity without a table of its own lives on a dimension
            return sum(1 for c in tables[k]["columns"] if mp._family(c.get("dataType")) == "number" and mp.MEASURE_NUMBER.search(c["name"])
                       and not mp.KEY_COLUMN.search(c["name"]))
        prof = graph.get("profile") or {}
        def unique(k):           # measured, or the database's own statistics say so: the key is unique (and present) here
            p = prof.get(k) or {}
            if bool(p.get("measured")) and p.get("rows", 0) > 0 and (p.get("distinct") or {}).get(e["members"][k]) == p.get("rows") \
                    and not (p.get("nulls") or {}).get(e["members"][k]):
                return True
            return _stats_unique((graph.get("stats") or {}).get(k, {}).get(e["members"][k]))
        return max(e["members"], key=lambda k: ([x.casefold() for x in tables[k].get("pk", [])] == [e["members"][k].casefold()], unique(k),
                                                bool(stem) and stem in tables[k]["table"].casefold(), not FACT_ROLE.match(tables[k]["table"]) and measures(k) == 0,
                                                -measures(k), -(tables[k].get("rows") or 0)))

    def link(home: str, k: str, e_name: str, keys: list[str], cols: list[str], ev: set[str]) -> dict | None:
        same_family = tables[k]["family"] == tables[home]["family"]
        ev = set(ev) | ({"family"} if sig.get("family", True) and same_family else set())
        base = max([opts["weights"].get(x, EVIDENCE.get(x, 0.5)) for x in ev if x != "family"] or [0.5])
        c = min(1.0, base + (0.05 if "family" in ev else 0))
        if not ev & {"declared", "metadata_conformance"} and not same_family:
            c = min(c, opts.get("unrelated_name", UNRELATED_NAME))   # a shared name across unrelated families needs the data to agree
        # the two columns' types must be able to hold the same values: a number never joins a date; a number and text
        # might (a cast), and two text keys of very different lengths (a 36-character id and a 5-character code) do not
        hc, kc = (next((x for x in tables[home]["columns"] if x["name"] == cols[0]), None), next((x for x in tables[k]["columns"] if x["name"] == cols[-1]), None))
        if hc and kc and opts.get("type_check", True):
            fa, fb = mp._family(hc.get("dataType")), mp._family(kc.get("dataType"))
            if {fa, fb} == {"number", "time"} or {fa, fb} == {"text", "time"}:
                return None
            if fa != fb and "declared" not in ev:
                c -= 0.15
            la, lb = ((x.get("dataType") or {}).get("precision") or 0 for x in (hc, kc))
            if fa == fb == "text" and la and lb and max(la, lb) >= opts.get("length_ratio", 4) * min(la, lb) and max(la, lb) - min(la, lb) > 8 and "declared" not in ev:
                return None
        # a history (type 2) dimension repeats its business key once per version: joining on it multiplies rows unless
        # the key is its surrogate key, or the database declares or its statistics show it unique
        if opts.get("history", True) and _history(tables[home]) and not re.search(r"(?i)(_sk|_skey|surrogate|_dwh_id)$", cols[0]) and "declared" not in ev \
                and not _stats_unique(((graph.get("stats") or {}).get(home) or {}).get(cols[0])):
            c = min(c, opts.get("generic_name", GENERIC_NAME))
        # the database's statistics, where it keeps them: values that agree are evidence, disjoint values end the link
        st = graph.get("stats") or {}
        agree = _stats_overlap((st.get(home) or {}).get(cols[0]), (st.get(k) or {}).get(cols[-1])) if opts.get("statistics", True) else None
        if agree is not None and "declared" not in ev:
            if agree < opts.get("stats_apart", 0.1):
                return None
            if agree >= opts.get("stats_agree", 0.6):
                c, ev = max(c, opts["weights"].get("statistics", EVIDENCE["statistics"])), ev | {"statistics"}
        # a key two tables share by name only, where neither holds it as its own (no declared or measured key, no
        # dimension or lookup, not named for it) is a weak sign: two facts both carrying ACCOUNT_ID do not join each other
        if ev <= {"same_name", "family"} and same_family:
            stem = re.sub(mp.KEY_COLUMN, "", cols[0]).strip("_").casefold().rstrip("s")
            owned = (bool(stem) and stem in tables[home]["table"].casefold()) or bool(mp.STAR_DIM.match(tables[home]["table"])) \
                or [x.casefold() for x in tables[home].get("pk", [])] == [cols[0].casefold()] \
                or _stats_unique((st.get(home) or {}).get(cols[0]))
            if not owned:
                c = min(c, opts.get("generic_name", GENERIC_NAME))
        measured = (graph.get("measured") or {}).get(f"{home}|{k}")
        if measured is not None:
            if measured < 0.2:
                return None                                 # the values do not match: not a link
            if measured >= 0.8:
                c, ev = max(c, opts["weights"].get("measured", EVIDENCE["measured"])), ev | {"measured"}
        pair = [home, k]
        if pair in cur.get("rejected_links", []) or pair[::-1] in cur.get("rejected_links", []):
            return None
        if pair in cur.get("confirmed_links", []) or pair[::-1] in cur.get("confirmed_links", []):
            c, ev = 1.0, ev | {"confirmed"}
        # Confidence boosts cannot turn a known nonunique parent or part of a compound PK into a safe lookup.
        hp = (graph.get("profile") or {}).get(home) or {}
        hd = (hp.get("distinct") or {}).get(cols[0])
        if hp.get("measured") and hd is not None and (hd != hp.get("rows") or (hp.get("nulls") or {}).get(cols[0])):
            c = min(c, opts.get("generic_name", GENERIC_NAME))
        pk = [x.casefold() for x in tables[home].get("pk", [])]
        if "declared" not in ev and len(pk) > 1 and cols[0].casefold() in pk:
            c = min(c, opts.get("generic_name", GENERIC_NAME))
        if "declared" not in ev and opts.get("history", True) and _history(tables[home]) and pk != [cols[0].casefold()] \
                and not re.search(r"(?i)(_sk|_skey|surrogate|_dwh_id)$", cols[0]):
            c = min(c, opts.get("generic_name", GENERIC_NAME))
        return {"from": home, "to": k, "entity": e_name, "entity_keys": keys, "columns": cols, "evidence": sorted(ev), "confidence": round(c, 2),
                "cross_store": tables[home]["datasource_id"] != tables[k]["datasource_id"]}
    out_entities, links = [], []
    for e in entities.values():
        e["home"] = home_of(e)
        for k in e["members"]:
            if k == e["home"]:
                continue
            ev = {"declared"} if (e["home"], k, e["members"][e["home"]], e["members"][k]) in declared else {x for x in e["why"][k] if x != "declared"} or {"same_name"}
            if "declared" not in ev and e["members"][e["home"]].casefold() != e["members"][k].casefold():
                ev = (ev - {"same_name", "primary_key_name"}) | {"suffix_name"}     # joined by a qualified name, not the same one
            l = link(e["home"], k, e["name"], [e["key"]], [e["members"][e["home"]], e["members"][k]], ev)
            if l:
                if e.get("role_playing"):
                    l["role_playing"] = True
                links.append(l)
    # Composite joins remain visible as one relationship, never promoted into independent component joins.
    for fk in composite_fks:
        pairs = list(zip(fk["parent_cols"], fk["child_cols"]))
        links = [l for l in links if not (l["from"] == fk["parent"] and l["to"] == fk["child"] and tuple(l["columns"]) in pairs)]
        if [fk["parent"], fk["child"]] in cur.get("rejected_links", []) or [fk["child"], fk["parent"]] in cur.get("rejected_links", []):
            continue
        if all(any(c["name"] == pc for c in tables[fk["parent"]]["columns"]) and any(c["name"] == cc for c in tables[fk["child"]]["columns"]) for pc, cc in pairs):
            links.append({"from": fk["parent"], "to": fk["child"], "entity": mp.subject(tables[fk["parent"]]["table"]),
                          "entity_keys": [], "columns": list(pairs[0]), "column_pairs": [list(p) for p in pairs],
                          "evidence": ["declared"], "confidence": 0.95, "composite": True,
                          "ambiguous_columns": bool(fk.get("ambiguous_columns")),
                          "cross_store": tables[fk["parent"]]["datasource_id"] != tables[fk["child"]]["datasource_id"]})
    # the same key in two families: one weak link between their homes, from the side that defines it
    by_col: dict[str, list[dict]] = {}
    for e in entities.values():
        by_col.setdefault(e["members"][e["home"]].casefold(), []).append(e)
    def metadata_owner(e: dict, col: str) -> bool:
        t = tables[e["home"]]
        stem = re.sub(mp.KEY_COLUMN, "", col).strip("_").casefold()
        if not stem or stem in {"id", "key", "code", "type", "status", "tenant", "source_system"}:
            return False
        pk = [x.casefold() for x in t.get("pk", [])]
        declared_owner = pk == [col] and not _is_fact(t, {col}, True)
        dimension_owner = bool(mp.STAR_DIM.match(t["table"])) and stem.rstrip("s") in t["table"].casefold()
        return (declared_owner or dimension_owner) and not (_history(t) and pk != [col])

    def domain(t: dict) -> str:
        # Preserve independently named datasets. Generic DIM_/FACT_ tables have no domain prefix; a named
        # SAAS_DIM_ACCOUNT must not be conformed to BANK_FACT_PAYMENTS just because both carry ACCOUNT_ID.
        name = t["table"].casefold()
        synthetic = re.match(r"^(sd_[a-z]+_[a-z0-9]+_\d{8}_\d{4})_", name)
        if synthetic:
            return synthetic.group(1)
        match = re.match(r"^(.+?)_(?:dim|dimension|fact|fct|lookup|lkp|lu)_", name)
        return match.group(1) if match else ""

    for col, group in by_col.items():
        owners = {e["home"] for e in group if metadata_owner(e, col)}
        ranked = sorted(group, key=lambda e: (e["home"] in owners, [x.casefold() for x in tables[e["home"]].get("pk", [])] == [col], -(tables[e["home"]].get("rows") or 0)), reverse=True)
        for i, parent in enumerate(ranked):
            for child in ranked[i + 1:]:
                if tables[parent["home"]]["family"] == tables[child["home"]]["family"]:
                    continue
                ev = {"same_name"}
                pt, ct = tables[parent["home"]], tables[child["home"]]
                if len(owners) == 1 and parent["home"] in owners and pt["datasource_id"] != ct["datasource_id"] \
                        and not (domain(pt) and domain(ct) and domain(pt) != domain(ct)):
                    ev.add("metadata_conformance")
                l = link(parent["home"], child["home"], parent["name"], [parent["key"], child["key"]],
                         [parent["members"][parent["home"]], child["members"][child["home"]]], ev)
                if l:
                    links.append(l)
    for e in entities.values():
        if len(e["members"]) >= 2 or any(e["key"] in l["entity_keys"] for l in links):
            out_entities.append({"key": e["key"], "name": e["name"], "home": e["home"], "members": e["members"],
                                 "evidence": sorted(set().union(*e["why"].values())), **({"role_playing": True} if e.get("role_playing") else {})})
    return {"tables": tables, "entities": out_entities, "links": links, "profile": graph.get("profile") or {},
            "selected_tables": sorted(selected), "excluded_tables": [{"table_key": k, "reason": "duplicate_copy"} for k in sorted(copies)]}


# ── recommend (pure) ─────────────────────────────────────────────────────────────────────────────────────────────────
FACT_ROLE = re.compile(r"^(fact|fct|f)_", re.I)
NOT_FACT = re.compile(r"(?:^|_)(map|mapping|xref|bridge|brg|lookup|lkp|lu|ref|rel|names?|crosswalk)(?:_|$)", re.I)


def _is_fact(t: dict, keyed: set[str], home: bool = False) -> bool:
    """a table of numbers to measure: named as a fact, or carrying measures. Dimensions, mappings and lookups are not;
    a table other tables point to (an entity's home) is a fact only when it carries measures, not just descriptive
    numbers (a date view, a provider list, a lane with its distance)"""
    name = t["table"]
    if mp.STAR_DIM.match(name) or NOT_FACT.search(name):
        return False
    nums = [c["name"] for c in t["columns"] if mp._family(c.get("dataType")) == "number" and c["name"] not in keyed
            and not mp.KEY_COLUMN.search(c["name"]) and not mp.DESCRIPTIVE_NUMBER.search(c["name"])]
    if FACT_ROLE.match(name):
        return bool(nums)
    measures = [n for n in nums if mp.MEASURE_NUMBER.search(n)]
    return bool(measures) if home else bool(nums)



def _semantic_review(st: dict, tables: dict, spec: dict) -> tuple[list[str], list[dict]]:
    """Metadata can identify aggregation hazards, not certify totals or invent numerator/denominator contracts."""
    warnings: list[str] = []
    metrics: list[dict] = []
    for l in st["used"]:
        ev = set(l["evidence"])
        if l.get("composite"):
            warnings.append(f"{tables[l['to']]['table']} → {tables[l['from']]['table']}: composite join requires {len(l.get('column_pairs') or [])} key components together.")
        elif l.get("role_playing"):
            warnings.append(f"{l['entity']}: preserve this foreign-key role with its own lookup alias.")
        elif not ev & {"declared", "confirmed"}:
            warnings.append(f"{l['entity']}: the join is inferred from metadata; confirm key meaning and parent uniqueness.")
        home = tables[l["from"]]
        if _history(home) and not l.get("composite") and [c.casefold() for c in home.get("pk", [])] != [l["columns"][0].casefold()]:
            warnings.append(f"{home['table']}: history rows require a unique version key or an explicit effective-date join.")
        if NOT_FACT.search(home["table"]) and re.search(r"(?:^|_)(bridge|brg|xref|crosswalk|map|mapping)(?:_|$)", home["table"], re.I):
            warnings.append(f"{home['table']}: a bridge may fan out metrics; define allocation or distinct-count semantics.")
    for m in spec["metrics"]:
        metadata = next((c for t in tables.values() if t["table"] == m["table"] for c in t["columns"] if c["name"] == m["column"]), {})
        column = re.sub(r"([a-z])([A-Z])", r"\1_\2", m["column"] + " " + str(metadata.get("description") or "")).replace(" ", "_")
        table = m["table"]
        snapshot = re.search(r"(?:^|_)(snapshot|balance|balances|inventory|backlog|stock|holdings)(?:_|$)", table, re.I)
        semi = re.search(r"(?:^|_)(balance|on_hand|onhand|backlog|stock|inventory|headcount|capacity|mrr|arr)(?:_|$)", column, re.I)
        cumulative = re.search(r"(?:^|_)(ytd|mtd|qtd|running|cumulative|lifetime)(?:_|$)", column, re.I)
        ratio = bool(mp.AVERAGED.search(column))
        if semi or cumulative or snapshot and re.search(r"(?:^|_)(qty|quantity|amount|units|total)(?:_|$)", column, re.I):
            kind = "semi-additive"
            reason = "Snapshot/cumulative values must not sum across time; define the time grain and end-of-period rule."
        elif ratio:
            kind = "non-additive"
            reason = "A row average is not a weighted aggregate; define the numerator, denominator or weighting contract."
        else:
            kind = "additive-candidate"
            reason = "SUM is a metadata inference; verify row grain, units and currency before relying on totals."
        metrics.append({"table": table, "column": m["column"], "additivity": kind, "reason": reason})
        if kind != "additive-candidate":
            warnings.append(f"{m['name']}: {reason}")
    if len(st["facts"]) > 1:
        warnings.append("Multiple fact grains: aggregate each fact before combining on conformed dimensions; never join raw fact rows together.")
    return list(dict.fromkeys(warnings)), metrics

def recommend(inferred: dict, options: dict | None = None) -> list[dict]:
    """candidate models: each fact table with the tables it reaches through links (dimensions, and other facts sharing
    them), within the table limits; ranked; each with its reasons and a drafted specification"""
    opts = {**DEFAULT_OPTIONS, **(options or {})}
    tables, links = inferred["tables"], [l for l in inferred["links"] if l["confidence"] >= opts["min_confidence"]]
    views = view_copies(tables) - set(inferred.get("selected_tables") or opts.get("selected_tables") or [])
    tables = {k: t for k, t in tables.items() if k not in views}
    links = [l for l in links if l["from"] not in views and l["to"] not in views]
    adj: dict[str, list[dict]] = {}
    for l in links:
        adj.setdefault(l["from"], []).append(l)
        adj.setdefault(l["to"], []).append(l)
    keyed: dict[str, set] = {k: set() for k in tables}                 # each table's key columns, one pass over entities
    for e in inferred["entities"]:
        for kk, c in e["members"].items():
            if kk in keyed:
                keyed[kk].add(c)
    homes = {e["home"] for e in inferred["entities"] if len(e["members"]) >= 2}
    pointed_to = {l["to"] for l in links}
    facts = [k for k, t in tables.items() if _is_fact(t, keyed[k], k in homes) and k in pointed_to]
    seen, out = set(), []
    stars: dict[frozenset, dict] = {}
    for f in facts:
        # a star (or snowflake): the fact and what it points to, and what those point to in turn, never back down to
        # other facts that happen to share a dimension
        group, used, frontier = {f}, [], [f]
        while frontier:
            cur = frontier.pop(0)
            for l in sorted(adj.get(cur, []), key=lambda x: -x["confidence"]):
                if l["to"] != cur:
                    continue
                other = l["from"]
                if opts["cross_store"] == "avoid" and l["cross_store"]:
                    continue
                if other in group:
                    if l not in used:
                        used.append(l)      # retain alternate keys and distinct roles on the same pair of tables
                    continue
                if len(group) >= opts["max_tables"]:
                    continue
                group.add(other); used.append(l); frontier.append(other)
        # Keep each fact's star even if another fact has exactly the same dimensions. A combined candidate is
        # offered separately, with all of its joins, rather than replacing the individual models.
        stars[frozenset(group)] = {"group": set(group), "facts": [f], "used": used}
    # a galaxy: facts that share a conformed dimension (the same Date, Plant or Machine) also make one model together,
    # offered beside each fact's own star while it stays within the table limit
    galaxies, pool = [], [st for st in stars.values() if len(st["group"]) >= opts["min_tables"]]
    dims_of = {id(st): st["group"] - set(st["facts"]) for st in pool}
    seen_comp: set[frozenset] = set()
    for i, st in enumerate(pool):
        # sharing a dimension with any star in the group = sharing one with the union of their dimensions
        comp, grew = [st], True
        in_comp, comp_dims, comp_group = {id(st)}, set(dims_of[id(st)]), set(st["group"])
        while grew:
            grew = False
            for other in pool:
                if id(other) not in in_comp and not dims_of[id(other)].isdisjoint(comp_dims) and len(comp_group | other["group"]) <= opts["max_tables"]:
                    comp.append(other); in_comp.add(id(other)); comp_dims |= dims_of[id(other)]; comp_group |= other["group"]; grew = True
        if len(comp) > 1:
            key = frozenset(id(c) for c in comp)
            if key not in seen_comp:
                seen_comp.add(key)
                used_all = list({(l["from"], l["to"], tuple(l["columns"])): l for c in comp for l in c["used"]}.values())
                galaxies.append({"group": set().union(*(c["group"] for c in comp)), "facts": [f for c in comp for f in c["facts"]], "used": used_all, "kind": "combined"})
    # a wide flat table (its own measures and descriptions, nothing it joins) is a model on its own
    in_group = set().union(*(st["group"] for st in stars.values() if len(st["group"]) >= opts["min_tables"]), set())
    flats = []
    for k, t in tables.items():
        if k in in_group:
            continue
        cols = t.get("columns", [])
        measures = sum(1 for c in cols if mp._family(c.get("dataType")) == "number" and mp.MEASURE_NUMBER.search(c["name"]) and not mp.KEY_COLUMN.search(c["name"]))
        described = sum(1 for c in cols if mp._family(c.get("dataType")) in ("text", "time"))
        if opts.get("flat", True) and len(cols) >= opts.get("flat_min_columns", 8) and measures >= 1 and described >= 3:
            flats.append({"group": {k}, "facts": [k], "used": [], "kind": "flat"})
    for st in [*stars.values(), *galaxies, *flats]:
        f, group, used = st["facts"][0], st["group"], st["used"]
        sig = frozenset(group)
        if (len(group) < opts["min_tables"] and st.get("kind") != "flat") or sig in seen:
            continue
        seen.add(sig)
        stores = sorted({tables[k]["dbms"] for k in group})
        datasource_ids = {tables[k]["datasource_id"] for k in group}
        modeled_names = {str(x).casefold() for x in opts["modeled_tables"]}
        modeled = sum(1 for k in group if k in opts["modeled_tables"] or tables[k]["table"].casefold() in modeled_names) / len(group)
        conf = sum(l["confidence"] for l in used) / max(1, len(used))
        n_facts = sum(1 for k in group if _is_fact(tables[k], keyed[k], k in homes))
        # confidence, then a well-formed size (3–6 tables), cross-store when preferred, a bonus for several facts sharing
        # dimensions, and a penalty for what is already modeled
        size = min(1.0, len(group) / 3) * (1.0 if len(group) <= 6 else 0.9)
        score = round(conf * size * (1 - 0.6 * modeled) * (1.15 if len(datasource_ids) > 1 and opts["cross_store"] == "prefer" else 1)
                      * (1 + 0.05 * (len(st["facts"]) - 1)), 3)
        # named for what it measures: its fact tables, then (with one fact) what describes it
        subjects = [mp.subject(tables[x]["table"]) for x in st["facts"]]
        by = list(dict.fromkeys(l["entity"] for l in used if not l["entity"].endswith(" Key")))[:2]
        name = (", ".join(subjects[:-1]) + " and " + subjects[-1] if len(subjects) > 1 else
                f"{subjects[0]} by {' and '.join(by)}" if subjects and by else subjects[0] if subjects else mp.subject(tables[f]["table"]))
        lead = ", ".join(subjects)
        n_dims = len(group) - len(st['facts'])
        reasons = [f"{lead} {'has' if len(st['facts']) == 1 else 'have'} numbers to measure"
                   + (f", described by {n_dims} related table{'s' if n_dims != 1 else ''}" if n_dims else "")]
        words = {"declared": "declared key", "primary_key_name": "primary key name", "same_name": "same column name", "suffix_name": "matching key name",
                 "family": "same dataset", "measured": "values match", "confirmed": "confirmed by you", "history": "joined in queries",
                 "statistics": "database statistics agree", "metadata_conformance": "unambiguous dimension key in the selected metadata"}
        reasons += [f"{l['entity']} links {mp.subject(tables[l['from']]['table'])} and {mp.subject(tables[l['to']]['table'])} ({', '.join(words.get(x, x.replace('_', ' ')) for x in l['evidence'] if x != 'family')})" for l in used[:4]]
        if len(datasource_ids) > 1:
            reasons.append(f"combines {len(datasource_ids)} data sources ({' and '.join(stores)}); the draft uses in-memory serving")
        if modeled:
            reasons.append(f"{int(modeled * 100)}% of these tables are already in a model")
        cat = {"tables": [tables[k] for k in sorted(group, key=lambda k: (k != f, k))]}
        # entities joined by a link this model uses (the same customer in two families) become one attribute
        parent = {e["key"]: e["key"] for e in inferred["entities"]}
        def root(x):
            while parent[x] != x:
                x = parent[x]
            return x
        for l in used:
            if len(l["entity_keys"]) == 2 and all(k in parent for k in l["entity_keys"]):
                parent[root(l["entity_keys"][1])] = root(l["entity_keys"][0])
        allowed: dict[str, set[tuple[str, str]]] = {}
        for l in used:
            if l.get("composite"):
                continue
            for ek in l["entity_keys"]:
                allowed.setdefault(ek, set()).update(zip((l["from"], l["to"]), l["columns"]))
        merged: dict[str, dict] = {}
        for e in inferred["entities"]:
            r = merged.setdefault(root(e["key"]), {"name": None, "members": [], "home": None, "role_playing": False})
            r["role_playing"] = r["role_playing"] or e.get("role_playing", False)
            if e["key"] == root(e["key"]):
                r["name"], r["home"] = e["name"], tables[e["home"]]["table"] if e["home"] in group else None
            r["members"] += [(tables[k]["table"], c) for k, c in e["members"].items() if k in group and (k, c) in allowed.get(e["key"], set())]
        dims_named = list(dict.fromkeys(l["entity"] for l in used if not l["entity"].endswith(" Key")))[:4]
        where = sorted({f"{tables[k]['datasource']} / {tables[k]['schema']}" for k in group})
        description = (f"{' and '.join(subjects) if len(subjects) < 3 else ', '.join(subjects[:-1]) + ' and ' + subjects[-1]}"
                       + (f", by {', '.join(dims_named[:-1]) + ' and ' + dims_named[-1] if len(dims_named) > 1 else dims_named[0]}" if dims_named else "")
                       + f". From {', '.join(where)}.")[:250]
        spec = mp.spec_from_tables(cat, {}, name,
                                   entities=[{"name": r["name"], "members": list(dict.fromkeys(r["members"])), "home": r["home"], "role_playing": r["role_playing"]}
                                             for r in merged.values() if len(set(r["members"])) >= 2], strict_entities=True,
                                   metric_tables={tables[k]["table"] for k in st["facts"]})
        spec["description"] = description
        # every draft is checked as the builder would check it; one the check refuses is offered for a decision, not a build
        sub = {"tables": [tables[k] for k in group]}
        measured_prof = {tables[k]["table"]: (inferred.get("profile") or {})[k] for k in group if k in (inferred.get("profile") or {})}
        try:
            findings = mp.check(mp.from_spec(spec, sub, measured_prof))
            orphans = [x for x in findings if x["level"] == "error" and x["code"] == "attribute_reaches_no_metric"]
            if orphans and opts.get("prune_unreachable", True) and not any(l.get("composite") or l.get("role_playing") for l in used) and len(orphans) == sum(1 for x in findings if x["level"] == "error"):
                # attributes that reach no numbers in this model are left out (and named), rather than holding the model back
                gone = {x["text"].split(" reaches ")[0] for x in orphans}
                spec["attributes"] = [a for a in spec["attributes"] if a["name"] not in gone]
                reasons.append(f"left out {', '.join(sorted(gone))}: {'they reach' if len(gone) > 1 else 'it reaches'} no numbers in this model")
                findings = mp.check(mp.from_spec(spec, sub, measured_prof))
        except mp.PlanError as e:
            findings = [{"level": "error", "code": "plan", "text": str(e)}]
        # A structural check cannot prove numeric correctness. Keep each uncertainty attached to the candidate,
        # and refuse unsupported joins instead of producing a plausible-looking draft with a partial key.
        semantic_warnings, metric_semantics = _semantic_review(st, tables, spec)
        spec["notes"] = ["Recommended from metadata only; numeric validation is pending.", *semantic_warnings]
        if any(l.get("composite") for l in used):
            findings.insert(0, {"level": "error", "code": "composite_key", "text": "A join requires every component of a composite key; this draft needs an explicit composite-key design before building."})
        if any(l.get("role_playing") for l in used):
            findings.insert(0, {"level": "error", "code": "role_playing", "text": "Several foreign-key roles share one lookup table; define separate role aliases before building."})
        problems = [x["text"] for x in findings if x["level"] == "error"]
        omitted = sorted({l["from"] for k in group for l in adj.get(k, []) if l["to"] == k and l["from"] not in group
                          and not (opts["cross_store"] == "avoid" and l["cross_store"])})
        if omitted:
            reasons.append(f"{len(omitted)} related table{'s' if len(omitted) != 1 else ''} could not fit the {opts['max_tables']}-table limit")
        # how each join is known: declared by the database (or confirmed by a person), checked against the data or the
        # database's statistics, or only by a shared name (to judge before building)
        joins = {"declared": 0, "data": 0, "statistics": 0, "name": 0}
        for l in used:
            ev_ = set(l["evidence"])
            joins["declared" if ev_ & {"declared", "confirmed"} else "data" if ev_ & {"measured", "history"} else "statistics" if "statistics" in ev_ else "name"] += 1
        hist = [mp.subject(tables[k]["table"]) for k in group if _history(tables[k])]
        if hist:
            reasons.append(f"{', '.join(hist[:2])} {'keeps' if len(hist) == 1 else 'keep'} history (a row per version): join on the surrogate key or filter to current rows")
        if st.get("kind") == "flat":
            reasons.append("one wide table with its own measures and descriptions: a model on its own")
        if joins["name"]:
            reasons.append(f"{joins['name']} of its {len(used)} join{'s' if len(used) != 1 else ''} rest{'s' if joins['name'] == 1 else ''} on a shared column name only: "
                           "confirm the key meaning and uniqueness from the model contract before building")
        out.append({"checked": not problems, "problems": problems[:3], "kind": st.get("kind", "star"), "joins": joins,
                    "semantic_status": "needs_review" if semantic_warnings or problems else "validation_pending",
                    "semantic_warnings": semantic_warnings, "metric_semantics": metric_semantics,
                    "omitted_related_tables": [{"table_key": k, "table": tables[k]["table"], "reason": "table_limit"} for k in omitted],
                    "name": name, "fact": tables[f]["table"], "fact_tables": [tables[x]["table"] for x in st["facts"]], "tables": [t["table"] for t in cat["tables"]], "table_keys": [tkey(t) for t in cat["tables"]],
                    "stores": stores, "cross_store": len(datasource_ids) > 1, "facts": n_facts, "score": score, "confidence": round(conf, 2), "modeled": round(modeled, 2), "reasons": reasons, "spec": spec})
    if opts.get("referenced") or opts.get("dictionary"):
        for rec in out:
            _with_references(rec, opts.get("referenced") or {}, opts.get("dictionary") or {})
    return sorted(out, key=lambda r: (not r["checked"], -r["score"]))      # ready to build first



def _json_scopes(value: Any, anchors: bool = False) -> list[dict]:
    """Structured CLI boundary: delimiters belong to identifiers, not to a home-grown serialization format."""
    if not isinstance(value, list) or any(not isinstance(sc, dict) for sc in value):
        raise ValueError("sources/anchors must be a JSON list of objects")
    for sc in value:
        required = ("datasource", "schema", "table") if anchors else ("datasource",)
        if any(not isinstance(sc.get(k), str) or not sc[k] for k in required):
            raise ValueError("Each source/anchor must name its datasource" + (", schema and table" if anchors else ""))
        if sc.get("schema") is not None and not isinstance(sc["schema"], str):
            raise ValueError("Source schema must be a string")
        for field in ("tables", "patterns"):
            if field in sc and (not isinstance(sc[field], list) or any(not isinstance(x, str) or not x for x in sc[field])):
                raise ValueError(f"Source {field} must be a list of nonempty strings")
    return value

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scan")
    s.add_argument("--source", action="append", default=[], help="DATASOURCE:SCHEMA[:PATTERN,PATTERN]")
    s.add_argument("--sources-json", help="JSON file of scope objects; preserves colons and commas in identifiers")
    s.add_argument("--out", required=True)
    s.add_argument("--options", help="JSON options")
    r = sub.add_parser("recommend")
    r.add_argument("--graph", required=True)
    r.add_argument("--options", help="JSON options")
    r.add_argument("--curation", help="JSON curation")
    r.add_argument("--out", required=True)
    r.add_argument("--references", help="JSON file: the references as Ace's reader extracted them")
    f = sub.add_parser("find", help="the tables that fit a description, from metadata only (no table is read)")
    f.add_argument("--query", default="")
    f.add_argument("--source", action="append", default=[], help="DATASOURCE[:SCHEMA[:PATTERN,PATTERN]]; none = every source")
    f.add_argument("--sources-json", help="JSON file of scope objects; preserves colons and commas in identifiers")
    f.add_argument("--anchors-json", help="JSON file of {datasource,schema,table} anchors with exact identifiers")
    f.add_argument("--references", help="JSON file: the references as Ace's reader extracted them")
    f.add_argument("--search-options", help="JSON file: approved metadata vocabulary aliases and domain groups")
    f.add_argument("--usage", help="JSON file: {table name: number of models using it}")
    f.add_argument("--budget", type=float, default=120.0)
    f.add_argument("--max-tables", type=int, default=24)
    f.add_argument("--anchor", action="append", default=[], help="DATASOURCE:SCHEMA:TABLE the model starts from")
    f.add_argument("--datasets", type=int, default=5, help="datasets to pick at most")
    f.add_argument("--per-source", type=float, default=45.0, help="seconds one source may take")
    f.add_argument("--out", required=True)
    a = ap.parse_args()
    opts = json.loads(a.options) if getattr(a, "options", None) else {}
    if a.cmd == "find":
        import mosaic_find
        import mosaic_live as live
        m = live.sign_in_from_env()
        scopes = []
        for src in a.source:
            ds, *rest = src.split(":")
            scopes.append({"datasource": ds, **({"schema": rest[0]} if rest and rest[0] else {}), **({"tables": rest[1].split(",")} if len(rest) > 1 and rest[1] else {})})
        if a.sources_json:
            scopes = _json_scopes(live.load_json(a.sources_json, "sources"))
        anchors = _json_scopes(live.load_json(a.anchors_json, "anchors"), anchors=True) if a.anchors_json else [dict(zip(("datasource", "schema", "table"), x.split(":", 2))) for x in a.anchor]
        found = mosaic_find.find(m, a.query, scopes or None, references=live.load_json(a.references, "references") if a.references else None,
                                 usage=live.load_json(a.usage, "usage") if a.usage else None,
                                 search_options=live.load_json(a.search_options, "search options") if a.search_options else None, budget=a.budget, max_tables=a.max_tables,
                                 anchors=anchors, datasets=a.datasets,
                                 per_source=a.per_source, log=lambda x: print(x, flush=True))
        with open(a.out, "w") as handle:
            json.dump(found, handle, default=str)
        print(f"found {len(found['picked'])} tables of {found['candidates']} matching, in {len(found['read'])} schemas read" + (f"; {len(found['left'])} left" if found["left"] else ""))
        return 0
    if a.cmd == "scan":
        import mosaic_live as live
        m = live.sign_in_from_env()
        scopes = []
        for src in a.source:
            ds, schema, *rest = src.split(":")
            scopes.append({"datasource": ds, "schema": schema, "patterns": rest[0].split(",") if rest else ["*"]})
        if a.sources_json:
            scopes = _json_scopes(live.load_json(a.sources_json, "sources"))
            scopes = [{**sc, "patterns": sc.get("patterns") or sc.get("tables") or ["*"]} for sc in scopes]
        if not scopes or any(not sc.get("schema") for sc in scopes):
            ap.error("scan requires a datasource and schema in --source or --sources-json")
        g = scan(m, scopes, opts, log=lambda x: print(x, flush=True))
        catalog_stats(m, g, log=lambda x: print(x, flush=True))        # the databases' own statistics: metadata, always
        if opts.get("skip_data_check", True) is False:
            measure_keys(m, g, opts, log=lambda x: print(x, flush=True))
            confirm(m, g, opts, budget=int(opts.get("data_check_budget", 40)), log=lambda x: print(x, flush=True))
        with open(a.out, "w") as handle:
            json.dump(g, handle, default=str)
        print(f"graph written: {len(g['tables'])} tables, {len(g['fks'])} declared foreign keys → {a.out}")
        return 0
    import mosaic_live as live
    graph = live.load_json(a.graph, "graph")
    if not isinstance(graph, dict) or not isinstance(graph.get("tables"), dict):
        raise SystemExit(f"graph: {a.graph} is not a scan graph (write one with: mosaic_discover.py scan … --out)")
    if a.references:
        graph = apply_references(graph, live.load_json(a.references, "references"))
        opts = {**opts, "referenced": graph["referenced"], "dictionary": graph["dictionary"]}
    inf = infer(graph, opts, json.loads(a.curation) if a.curation else None)
    recs = recommend(inf, opts)
    with open(a.out, "w") as handle:
        json.dump({"entities": inf["entities"], "links": inf["links"], "recommendations": recs}, handle, default=str)
    for rec in recs[:10]:
        print(f"{rec['score']:.2f}  {rec['name']}: {len(rec['tables'])} tables, {'/'.join(rec['stores'])} — " + "; ".join(rec["reasons"][:3]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
