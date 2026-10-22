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

EVIDENCE = {"declared": 0.95, "primary_key_name": 0.75, "same_name": 0.55, "suffix_name": 0.5, "measured": 0.85, "history": 0.9}
UNRELATED_NAME = 0.35        # the same key name in two unrelated table families, until the data says they match
DEFAULT_OPTIONS = {
    "min_tables": 2, "max_tables": 8, "cross_store": "allow",          # allow | prefer | avoid
    "signals": {"declared": True, "same_name": True, "family": True},
    "weights": {}, "exclude_patterns": ["*_BAK", "*_BACKUP", "TMP_*", "*_TMP", "*_OLD"], "modeled_tables": [],
    "min_confidence": 0.5,
}


def tkey(t: dict) -> str:
    return f"{t['datasource_id']}/{t['schema']}/{t['table']}"


# ── scan (live) ──────────────────────────────────────────────────────────────────────────────────────────────────────
def _stats_sql(dbms: str, schema: str) -> str | None:
    d = dbms.lower()
    if "snowflake" in d:
        return f"SELECT TABLE_NAME AS t, ROW_COUNT AS n FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA='{schema}' AND TABLE_TYPE='BASE TABLE'"
    if "postgres" in d:
        return ("SELECT c.relname AS t, GREATEST(c.reltuples,0)::bigint AS n FROM pg_class c JOIN pg_namespace s ON s.oid=c.relnamespace "
                f"WHERE s.nspname='{schema}' AND c.relkind='r'")
    return None


def _declared_keys(m, live, info: dict, schema: str, tables: set[str]) -> tuple[dict, list]:
    """{table: [pk columns]}, [fk {child, child_cols, parent, parent_cols}] for tables in scope"""
    d, pks, fks = info["dbms"].lower(), {}, []
    try:
        if "postgres" in d:
            for r in live.run_sql(m, info["id"], "SELECT tc.table_name AS t, kcu.column_name AS c, tc.constraint_type AS k, ccu.table_name AS pt, ccu.column_name AS pc, "
                                  "tc.constraint_name AS n FROM information_schema.table_constraints tc JOIN information_schema.key_column_usage kcu "
                                  "ON kcu.constraint_name=tc.constraint_name AND kcu.table_schema=tc.table_schema LEFT JOIN information_schema.constraint_column_usage ccu "
                                  f"ON ccu.constraint_name=tc.constraint_name AND ccu.table_schema=tc.table_schema WHERE tc.table_schema='{schema}' "
                                  "AND tc.constraint_type IN ('PRIMARY KEY','FOREIGN KEY')"):
                if r["t"] not in tables:
                    continue
                if r["k"] == "PRIMARY KEY":
                    pks.setdefault(r["t"], []).append(r["c"])
                elif r.get("pt") in tables:
                    fks.append({"child": r["t"], "child_cols": [r["c"]], "parent": r["pt"], "parent_cols": [r["pc"]], "name": r["n"]})
        elif "snowflake" in d:
            have = {r["t"] for r in live.run_sql(m, info["id"], "SELECT DISTINCT TABLE_NAME AS t FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS "
                                                 f"WHERE TABLE_SCHEMA='{schema}' AND CONSTRAINT_TYPE IN ('PRIMARY KEY','FOREIGN KEY')")}
            for t in sorted(have & tables):
                ddl = live.run_sql(m, info["id"], f"SELECT GET_DDL('TABLE', '{schema}.{t}') AS d")[0]["d"] or ""
                for kind, cols, ref, refcols in re.findall(r"(?i)(primary key|foreign key)\s*\(([^)]*)\)(?:\s*references\s+([\w.\"]+)\s*\(([^)]*)\))?", ddl):
                    cols_l = [c.strip().strip('"') for c in cols.split(",")]
                    if kind.lower() == "primary key":
                        pks[t] = cols_l
                    elif ref:
                        pt = ref.split(".")[-1].strip('"')
                        if pt in tables:
                            fks.append({"child": t, "child_cols": cols_l, "parent": pt, "parent_cols": [c.strip().strip('"') for c in refcols.split(",")], "name": ""})
    except RuntimeError:
        pass                                    # declared keys are one signal among several
    return pks, fks


def scan(m, scopes: list[dict], options: dict | None = None, log=lambda s: None) -> dict:
    """scopes: [{datasource, schema, patterns:[glob...]}] → the source graph's raw facts"""
    import mosaic_live as live
    import mosaic_matrix as mx
    opts = {**DEFAULT_OPTIONS, **(options or {})}
    graph: dict[str, Any] = {"tables": {}, "fks": [], "scopes": scopes}
    for sc in scopes:
        info = live.datasource(m, sc["datasource"])
        names = mx.list_tables(m, info["id"], sc["schema"])
        pats = sc.get("patterns") or ["*"]
        names = [n for n in names if any(fnmatch.fnmatchcase(n.upper(), p.upper()) for p in pats)
                 and not any(fnmatch.fnmatchcase(n.upper(), p.upper()) for p in opts["exclude_patterns"])]
        if len(names) > opts.get("max_scan_tables", 200):
            raise ValueError(f"{len(names)} tables match in {info['name']}/{sc['schema']}; narrow the patterns (limit {opts.get('max_scan_tables', 200)})")
        log(f"  {info['name']}/{sc['schema']}: {len(names)} tables")
        rows = {}
        stats = _stats_sql(info["dbms"], sc["schema"])
        if stats:
            try:
                rows = {r["t"]: int(float(r["n"] or 0)) for r in live.run_sql(m, info["id"], stats)}
            except RuntimeError:
                rows = {}
        pks, fks = _declared_keys(m, live, info, sc["schema"], set(names))
        cat = live.catalog(m, [{"datasource": info["id"], "schema": sc["schema"], "table": n} for n in names])
        for t in cat["tables"]:
            graph["tables"][tkey(t)] = {**t, "rows": rows.get(t["table"]), "pk": pks.get(t["table"], []), "family": _family_key(t["table"], t["schema"], t["datasource_id"])}
        for fk in fks:
            base = f"{info['id']}/{sc['schema']}/"
            graph["fks"].append({**fk, "child": base + fk["child"], "parent": base + fk["parent"]})
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
    for k in [k for k in want if k not in prof][:budget]:
        t = graph["tables"][k]
        try:
            got = live.profile(m, {"tables": [t]}, {t["table"]: sorted(want[k])[:12]})
            prof[k] = got.get(t["table"]) or {"measured": False}
            if prof[k].get("measured"):
                uniq = [c for c, d in prof[k]["distinct"].items() if d == prof[k]["rows"]]
                log(f"  {t['table']}: {prof[k]['rows']:,} rows{'; unique: ' + ', '.join(uniq) if uniq else ''}")
        except Exception as e:  # noqa: BLE001 - a table that cannot be measured is judged from its metadata
            prof[k] = {"measured": False, "reason": str(e)[:200]}
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
    for l in todo[:budget]:
        home, other = graph["tables"][l["from"]], graph["tables"][l["to"]]
        hc, oc = l["columns"]
        try:
            vals = [r["v"] for r in live.run_sql(m, other["datasource_id"], f"SELECT DISTINCT {live.quote(other['dbms'], oc)} AS v FROM {live.table_ref(other)} "
                                                 f"WHERE {live.quote(other['dbms'], oc)} IS NOT NULL LIMIT 100") if r.get("v") not in (None, "")]
            if not vals:
                continue
            listed = ", ".join("'" + str(v).replace("'", "''") + "'" for v in vals)
            found = live.run_sql(m, home["datasource_id"], f"SELECT COUNT(DISTINCT {live.quote(home['dbms'], hc)}) AS n FROM {live.table_ref(home)} "
                                                       f"WHERE CAST({live.quote(home['dbms'], hc)} AS VARCHAR(400)) IN ({listed})")[0]["n"]
            measured[f"{l['from']}|{l['to']}"] = round(int(float(found)) / len(vals), 2)
            log(f"  {l['entity']}: {other['table']} → {home['table']}: {int(float(found))}/{len(vals)} values found")
        except (RuntimeError, ValueError, KeyError, IndexError) as e:
            log(f"  {l['entity']}: {other['table']} → {home['table']}: not measurable ({str(e)[:100]})")
    return graph


def view_copies(tables: dict) -> set:
    """views and copies of another scanned table: FACT_X_V, FACT_X2, FACT_X_COPY or FACT_X_NEW beside FACT_X with
    (nearly) the same columns repeat it, so the base table is used and they are left out"""
    norm = lambda n: re.sub(r"[^a-z0-9]", "", n.casefold())  # noqa: E731
    out = set()
    for k, t in tables.items():
        cols = {norm(c["name"]) for c in t["columns"]}
        for kk, other in tables.items():
            if kk == k or other["datasource_id"] != t["datasource_id"] or other.get("schema") != t.get("schema"):
                continue
            base = other["table"].casefold()
            name = t["table"].casefold()
            # the copy's name is the base's plus a suffix: digits, or _v/_vw/_view, or _<word>
            if not (name != base and name.startswith(base) and re.fullmatch(r"_?(\d+|v|vw|view|[a-z]+)", name[len(base):])):
                continue
            ocols = {norm(c["name"]) for c in other["columns"]}
            suffix = name[len(base):].lstrip("_")
            need = 0.8 if re.fullmatch(r"\d+|v|vw|view", suffix) else 0.9
            if len(cols & ocols) >= need * max(len(cols), 1):
                out.add(k)
    return out


STAR_ROLE = re.compile(r"^(dim|dimension|d|fact|fct|f|lkp|lookup|lu|ref|rel|bridge|brg|agg|xref)_", re.I)


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
    star_schema = {(t.get("datasource_id"), t.get("schema")) for t in tables.values() if mp.STAR_DIM.match(t["table"])}
    for t in tables.values():
        # a schema with dimension or lookup tables (DIM_, LU_) and up to 60 tables is one star: its facts join its
        # lookups whatever they are called (TXN_BOOKING with LU_RESIDENCY)
        if (t.get("datasource_id"), t.get("schema")) in star_schema and per_schema[(t.get("datasource_id"), t.get("schema"))] <= 60 \
                and not re.match(r"^SD_[A-Z]+_[A-Z0-9]+_\d{8}_\d{4}_", t["table"], re.I):
            t["family"] = f"{t.get('datasource_id')}/{t.get('schema')}#star"
            continue
        # a small schema (up to 20 tables, no synthetic datasets) is one dataset
        if per_schema[(t.get("datasource_id"), t.get("schema"))] <= 20 and not re.match(r"^SD_[A-Z]+_[A-Z0-9]+_\d{8}_\d{4}_", t["table"], re.I):
            t["family"] = f"{t.get('datasource_id')}/{t.get('schema')}#schema"
            continue
        tok = (t.get("datasource_id"), t.get("schema"), t["table"].split("_")[0].casefold())
        if "_" in t["table"] and first.get(tok, 0) >= 3 and not t["family"].endswith("#star") and not re.match(r"^SD_[A-Z]+_[A-Z0-9]+_\d{8}_\d{4}_", t["table"], re.I):
            t["family"] = f"{tok[0]}/{tok[1]}#{tok[2]}"
    tables = {k: t for k, t in tables.items() if k not in view_copies(tables)}
    entities: dict[str, dict] = {}
    declared: set[tuple[str, str]] = set()

    def entity(key: str, name: str) -> dict:
        return entities.setdefault(key, {"key": key, "name": cur.get("names", {}).get(key, name), "members": {}, "home": None, "why": {}})

    def member(e: dict, k: str, col: str, why: str) -> None:
        e["members"].setdefault(k, col)
        e["why"].setdefault(k, set()).add(why)
    if sig.get("declared", True):
        for fk in graph.get("fks", []):
            if fk["child"] not in tables or fk["parent"] not in tables or len(fk["parent_cols"]) != 1:
                continue
            pc, cc = fk["parent_cols"][0], fk["child_cols"][0]
            e = entity(f"{fk['parent']}#{pc.casefold()}", mp._friendly(re.sub(mp.KEY_COLUMN, "", pc).strip("_") or mp._short_table(tables[fk["parent"]]["table"])))
            member(e, fk["parent"], pc, "declared"); member(e, fk["child"], cc, "declared")
            e["home"] = fk["parent"]
            declared.add((fk["parent"], fk["child"]))
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
                and n != "id" and mp._family(c.get("dataType")) in ("number", "text", "time")
        for k, t in tables.items():
            for c in t["columns"]:
                if joins(c, t["family"]):
                    clusters.setdefault((c["name"].casefold(), t["family"]), []).append((k, c["name"]))
        for (name, fam), occ in clusters.items():
            existing = next((e for e in entities.values() if any(e["members"].get(k, "").casefold() == name for k, _ in occ)), None)
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
                if a_ is b_ or a_["key"] not in entities or b_["key"] not in entities or fam(a_) != fam(b_):
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
        def unique(k):           # measured: the key is unique (and present) on this table
            p = prof.get(k) or {}
            return bool(p.get("measured")) and p.get("rows", 0) > 0 and (p.get("distinct") or {}).get(e["members"][k]) == p.get("rows") \
                and not (p.get("nulls") or {}).get(e["members"][k])
        return max(e["members"], key=lambda k: ([x.casefold() for x in tables[k].get("pk", [])] == [e["members"][k].casefold()], unique(k),
                                                bool(stem) and stem in tables[k]["table"].casefold(), not FACT_ROLE.match(tables[k]["table"]) and measures(k) == 0,
                                                -measures(k), -(tables[k].get("rows") or 0)))

    def link(home: str, k: str, e_name: str, keys: list[str], cols: list[str], ev: set[str]) -> dict | None:
        same_family = tables[k]["family"] == tables[home]["family"]
        ev = set(ev) | ({"family"} if sig.get("family", True) and same_family else set())
        base = max([opts["weights"].get(x, EVIDENCE.get(x, 0.5)) for x in ev if x != "family"] or [0.5])
        c = min(1.0, base + (0.05 if "family" in ev else 0))
        if "declared" not in ev and not same_family:
            c = min(c, UNRELATED_NAME)                      # a shared name across unrelated families needs the data to agree
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
        return {"from": home, "to": k, "entity": e_name, "entity_keys": keys, "columns": cols, "evidence": sorted(ev), "confidence": round(c, 2),
                "cross_store": tables[home]["datasource_id"] != tables[k]["datasource_id"]}
    out_entities, links = [], []
    for e in entities.values():
        e["home"] = home_of(e)
        for k in e["members"]:
            if k == e["home"]:
                continue
            ev = {"declared"} if (e["home"], k) in declared else {x for x in e["why"][k] if x != "declared"} or {"same_name"}
            if "declared" not in ev and e["members"][e["home"]].casefold() != e["members"][k].casefold():
                ev = (ev - {"same_name", "primary_key_name"}) | {"suffix_name"}     # joined by a qualified name, not the same one
            l = link(e["home"], k, e["name"], [e["key"]], [e["members"][e["home"]], e["members"][k]], ev)
            if l:
                links.append(l)
    # the same key in two families: one weak link between their homes, from the side that defines it
    by_col: dict[str, list[dict]] = {}
    for e in entities.values():
        by_col.setdefault(e["members"][e["home"]].casefold(), []).append(e)
    for col, group in by_col.items():
        ranked = sorted(group, key=lambda e: ([x.casefold() for x in tables[e["home"]].get("pk", [])] == [col], -(tables[e["home"]].get("rows") or 0)), reverse=True)
        for i, parent in enumerate(ranked):
            for child in ranked[i + 1:]:
                if tables[parent["home"]]["family"] == tables[child["home"]]["family"]:
                    continue
                l = link(parent["home"], child["home"], parent["name"], [parent["key"], child["key"]],
                         [parent["members"][parent["home"]], child["members"][child["home"]]], {"same_name"})
                if l:
                    links.append(l)
    for e in entities.values():
        if len(e["members"]) >= 2 or any(e["key"] in l["entity_keys"] for l in links):
            out_entities.append({"key": e["key"], "name": e["name"], "home": e["home"], "members": e["members"],
                                 "evidence": sorted(set().union(*e["why"].values()))})
    return {"tables": tables, "entities": out_entities, "links": links, "profile": graph.get("profile") or {}}


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


def recommend(inferred: dict, options: dict | None = None) -> list[dict]:
    """candidate models: each fact table with the tables it reaches through links (dimensions, and other facts sharing
    them), within the table limits; ranked; each with its reasons and a drafted specification"""
    opts = {**DEFAULT_OPTIONS, **(options or {})}
    tables, links = inferred["tables"], [l for l in inferred["links"] if l["confidence"] >= opts["min_confidence"]]
    views = view_copies(tables)
    tables = {k: t for k, t in tables.items() if k not in views}
    links = [l for l in links if l["from"] not in views and l["to"] not in views]
    adj: dict[str, list[dict]] = {}
    for l in links:
        adj.setdefault(l["from"], []).append(l)
        adj.setdefault(l["to"], []).append(l)
    keyed = {k: {c for e in inferred["entities"] for kk, c in e["members"].items() if kk == k} for k in tables}
    homes = {e["home"] for e in inferred["entities"] if len(e["members"]) >= 2}
    facts = [k for k, t in tables.items() if _is_fact(t, keyed[k], k in homes) and any(l["to"] == k for l in links)]
    seen, out = set(), []
    stars: dict[frozenset, dict] = {}
    for f in facts:
        # a star (or snowflake): the fact and what it points to, and what those point to in turn, never back down to
        # other facts that happen to share a dimension
        group, used, frontier = {f}, [], [f]
        while frontier and len(group) < opts["max_tables"]:
            cur = frontier.pop(0)
            for l in sorted(adj.get(cur, []), key=lambda x: -x["confidence"]):
                if l["to"] != cur:
                    continue
                other = l["from"]
                if other in group or len(group) >= opts["max_tables"]:
                    continue
                if opts["cross_store"] == "avoid" and l["cross_store"]:
                    continue
                group.add(other); used.append(l); frontier.append(other)
        dims = frozenset(group - {f})
        if dims in stars and len(stars[dims]["group"]) < opts["max_tables"]:
            stars[dims]["group"].add(f); stars[dims]["facts"].append(f)
            continue
        stars[dims] = {"group": set(group), "facts": [f], "used": used}
    # a galaxy: facts that share a conformed dimension (the same Date, Plant or Machine) also make one model together,
    # offered beside each fact's own star while it stays within the table limit
    galaxies, pool = [], [st for st in stars.values() if len(st["group"]) >= opts["min_tables"]]
    shared = lambda a, b: (a["group"] - set(a["facts"])) & (b["group"] - set(b["facts"]))  # noqa: E731
    seen_comp: set[frozenset] = set()
    for i, st in enumerate(pool):
        comp, grew = [st], True
        while grew:
            grew = False
            for other in pool:
                if other not in comp and any(shared(other, c) for c in comp) and len(set().union(*(c["group"] for c in comp)) | other["group"]) <= opts["max_tables"]:
                    comp.append(other); grew = True
        if len(comp) > 1:
            key = frozenset(id(c) for c in comp)
            if key not in seen_comp:
                seen_comp.add(key)
                used_all = list({(l["from"], l["to"]): l for c in comp for l in c["used"]}.values())
                galaxies.append({"group": set().union(*(c["group"] for c in comp)), "facts": [f for c in comp for f in c["facts"]], "used": used_all, "kind": "combined"})
    for st in [*stars.values(), *galaxies]:
        f, group, used = st["facts"][0], st["group"], st["used"]
        sig = frozenset(group)
        if len(group) < opts["min_tables"] or sig in seen:
            continue
        seen.add(sig)
        stores = sorted({tables[k]["dbms"] for k in group})
        modeled_names = {str(x).casefold() for x in opts["modeled_tables"]}
        modeled = sum(1 for k in group if k in opts["modeled_tables"] or tables[k]["table"].casefold() in modeled_names) / len(group)
        conf = sum(l["confidence"] for l in used) / max(1, len(used))
        n_facts = sum(1 for k in group if _is_fact(tables[k], keyed[k], k in homes))
        # confidence, then a well-formed size (3–6 tables), cross-store when preferred, a bonus for several facts sharing
        # dimensions, and a penalty for what is already modeled
        size = min(1.0, len(group) / 3) * (1.0 if len(group) <= 6 else 0.9)
        score = round(conf * size * (1 - 0.6 * modeled) * (1.15 if len(stores) > 1 and opts["cross_store"] == "prefer" else 1)
                      * (1 + 0.05 * (len(st["facts"]) - 1)), 3)
        # named for what it measures: its fact tables, then (with one fact) what describes it
        subjects = [mp.subject(tables[x]["table"]) for x in st["facts"]]
        by = list(dict.fromkeys(l["entity"] for l in used if not l["entity"].endswith(" Key")))[:2]
        name = (", ".join(subjects[:-1]) + " and " + subjects[-1] if len(subjects) > 1 else
                f"{subjects[0]} by {' and '.join(by)}" if subjects and by else subjects[0] if subjects else mp.subject(tables[f]["table"]))
        lead = ", ".join(subjects)
        reasons = [f"{lead} {'has' if len(st['facts']) == 1 else 'have'} numbers to measure, described by {len(group) - len(st['facts'])} related table{'s' if len(group) - len(st['facts']) != 1 else ''}"]
        words = {"declared": "declared key", "primary_key_name": "primary key name", "same_name": "same column name", "suffix_name": "matching key name",
                 "family": "same dataset", "measured": "values match", "confirmed": "confirmed by you", "history": "joined in queries"}
        reasons += [f"{l['entity']} links {mp.subject(tables[l['from']]['table'])} and {mp.subject(tables[l['to']]['table'])} ({', '.join(words.get(x, x.replace('_', ' ')) for x in l['evidence'] if x != 'family')})" for l in used[:4]]
        if len(stores) > 1:
            reasons.append(f"joins {' and '.join(stores)} without moving data")
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
        merged: dict[str, dict] = {}
        for e in inferred["entities"]:
            r = merged.setdefault(root(e["key"]), {"name": None, "members": [], "home": None})
            if e["key"] == root(e["key"]):
                r["name"], r["home"] = e["name"], tables[e["home"]]["table"] if e["home"] in group else None
            r["members"] += [(tables[k]["table"], c) for k, c in e["members"].items() if k in group]
        dims_named = list(dict.fromkeys(l["entity"] for l in used if not l["entity"].endswith(" Key")))[:4]
        where = sorted({f"{tables[k]['datasource']} / {tables[k]['schema']}" for k in group})
        description = (f"{' and '.join(subjects) if len(subjects) < 3 else ', '.join(subjects[:-1]) + ' and ' + subjects[-1]}"
                       + (f", by {', '.join(dims_named[:-1]) + ' and ' + dims_named[-1] if len(dims_named) > 1 else dims_named[0]}" if dims_named else "")
                       + f". From {', '.join(where)}.")[:250]
        spec = mp.spec_from_tables(cat, {}, name,
                                   entities=[{"name": r["name"], "members": r["members"], "home": r["home"]} for r in merged.values() if len(r["members"]) >= 2])
        spec["description"] = description
        # every draft is checked as the builder would check it; one the check refuses is offered for a decision, not a build
        sub = {"tables": [tables[k] for k in group]}
        measured_prof = {tables[k]["table"]: (inferred.get("profile") or {})[k] for k in group if k in (inferred.get("profile") or {})}
        try:
            findings = mp.check(mp.from_spec(spec, sub, measured_prof))
            orphans = [x for x in findings if x["level"] == "error" and x["code"] == "attribute_reaches_no_metric"]
            if orphans and opts.get("prune_unreachable", True) and len(orphans) == sum(1 for x in findings if x["level"] == "error"):
                # attributes that reach no numbers in this model are left out (and named), rather than holding the model back
                gone = {x["text"].split(" reaches ")[0] for x in orphans}
                spec["attributes"] = [a for a in spec["attributes"] if a["name"] not in gone]
                reasons.append(f"left out {', '.join(sorted(gone))}: {'they reach' if len(gone) > 1 else 'it reaches'} no numbers in this model")
                findings = mp.check(mp.from_spec(spec, sub, measured_prof))
        except mp.PlanError as e:
            findings = [{"level": "error", "code": "plan", "text": str(e)}]
        problems = [x["text"] for x in findings if x["level"] == "error"]
        out.append({"checked": not problems, "problems": problems[:3], "kind": st.get("kind", "star"),
                    "name": name, "fact": tables[f]["table"], "fact_tables": [tables[x]["table"] for x in st["facts"]], "tables": [t["table"] for t in cat["tables"]], "table_keys": [tkey(t) for t in cat["tables"]],
                    "stores": stores, "facts": n_facts, "score": score, "confidence": round(conf, 2), "modeled": round(modeled, 2), "reasons": reasons, "spec": spec})
    return sorted(out, key=lambda r: (not r["checked"], -r["score"]))      # ready to build first


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scan")
    s.add_argument("--source", action="append", required=True, help="DATASOURCE:SCHEMA[:PATTERN,PATTERN]")
    s.add_argument("--out", required=True)
    s.add_argument("--options", help="JSON options")
    r = sub.add_parser("recommend")
    r.add_argument("--graph", required=True)
    r.add_argument("--options", help="JSON options")
    r.add_argument("--curation", help="JSON curation")
    r.add_argument("--out", required=True)
    a = ap.parse_args()
    opts = json.loads(a.options) if a.options else {}
    if a.cmd == "scan":
        import mosaic_live as live
        m = live.sign_in_from_env()
        scopes = []
        for src in a.source:
            ds, schema, *rest = src.split(":")
            scopes.append({"datasource": ds, "schema": schema, "patterns": rest[0].split(",") if rest else ["*"]})
        g = scan(m, scopes, opts, log=lambda x: print(x, flush=True))
        if not opts.get("skip_data_check"):
            print("→ Measuring which keys are unique where…", flush=True)
            measure_keys(m, g, opts, log=lambda x: print(x, flush=True))
            print("→ Checking links only a shared name suggests, against the data…", flush=True)
            confirm(m, g, opts, budget=int(opts.get("data_check_budget", 40)), log=lambda x: print(x, flush=True))
        json.dump(g, open(a.out, "w"), default=str)
        print(f"graph written: {len(g['tables'])} tables, {len(g['fks'])} declared foreign keys → {a.out}")
        return 0
    graph = json.load(open(a.graph))
    inf = infer(graph, opts, json.loads(a.curation) if a.curation else None)
    recs = recommend(inf, opts)
    json.dump({"entities": inf["entities"], "links": inf["links"], "recommendations": recs}, open(a.out, "w"), default=str)
    for rec in recs[:10]:
        print(f"{rec['score']:.2f}  {rec['name']}: {len(rec['tables'])} tables, {'/'.join(rec['stores'])} — " + "; ".join(rec["reasons"][:3]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
