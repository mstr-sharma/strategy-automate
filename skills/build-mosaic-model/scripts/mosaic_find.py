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


import mosaic_dialects as dialects

PAGE = dialects.PAGE                                    # Strategy returns at most 1,000 rows per source query
SEP = dialects.SEP


def _flavor(dbms: str) -> str | None:
    return dialects.flavor(dbms)


def _catalog_sql(dbms: str, schema: str | None) -> str | None:
    """the first catalog statement for a source (kept for callers that want one)"""
    q = dialects.catalog_queries(dbms, schema)
    return q[0][1] if q else None


def _paged(dbms: str, sql: str, page: int) -> str:
    return dialects.paged(dbms, sql, page, PAGE)


def catalog_tables(m, live, info: dict[str, Any], schema: str | None, deadline: float | None = None) -> dict[str, list[dict[str, Any]]] | None:
    """{schema: [{table, rows, comment, columns: [{name, comment}]}]} from the source's catalog views, page by page,
    trying each statement its kind of database offers in turn; None when none answers (no catalog we can read)"""
    for kind, sql in dialects.catalog_queries(info["dbms"], schema):
        out: dict[str, dict[str, dict[str, Any]]] = {}
        page, ok = 0, True
        while True:
            try:
                rows = live.run_sql(m, info["id"], _paged(info["dbms"], sql, page))
            except RuntimeError:
                ok = page > 0                           # a later page failing keeps what was read; a first one tries the next statement
                break
            for r in rows:
                t = out.setdefault(r["s"], {}).setdefault(r["t"], {"table": r["t"], "rows": _int(r.get("n")), "comment": r.get("tc") or "", "columns": []})
                if kind == "tables":
                    names = str(r.get("cols") or "").split(SEP)
                    notes = str(r.get("cc") or "").split(SEP) + [""] * len(names)
                    t["columns"] += [{"name": n, "comment": notes[i]} for i, n in enumerate(names) if n]
                    if _int(r.get("k")) and len(t["columns"]) < _int(r.get("k")):
                        ok = False                      # the database cut the joined list short: read one row per column instead
                else:
                    t["columns"].append({"name": r["c"], "comment": r.get("cc") or ""})
            if not ok or len(rows) < PAGE or page >= 199 or (deadline and time.monotonic() > deadline):
                break
            page += 1
        if ok and out:
            return {s_: list(ts.values()) for s_, ts in out.items()}
    return None


def schema_tables(m, live, matrix, info: dict[str, Any], schema: str, deadline: float | None = None) -> tuple[list[dict[str, Any]], str]:
    """one schema's tables with their columns and comments ("catalog views"); for sources with no catalog we can read
    (NoSQL stores, SaaS and file connectors) Strategy's own catalog: the table names, and the columns of up to 40
    tables ("catalog API")"""
    got = catalog_tables(m, live, info, schema, deadline)
    if got:
        # BigQuery names a dataset without its project ("Sales" for "project.Sales")
        return got.get(schema) or next((v for k, v in got.items() if schema.endswith("." + k)), []), "catalog views"
    import build_mosaic as bm
    names = matrix.list_tables(m, info["id"], schema)
    tables = []
    for i, n in enumerate(names):
        cols = []
        if i < 40 and (deadline is None or time.monotonic() < deadline):
            try:
                md = bm.fetch_table_metadata(m, info["id"], schema, n)
                cols = [{"name": c.get("name") or c.get("columnName"), "comment": c.get("description") or ""} for c in md.get("columns", [])]
            except Exception:  # noqa: BLE001 - a table whose columns cannot be listed is judged by its name
                cols = []
        tables.append({"table": n, "rows": None, "comment": "", "columns": [c for c in cols if c["name"]]})
    return tables, "catalog API"


def _bounded(fn, seconds: float):
    """fn() with a time limit: a source that hangs (unreachable, retrying) is given up on, never waited for"""
    import concurrent.futures as cf
    ex = cf.ThreadPoolExecutor(max_workers=1)
    try:
        return ex.submit(fn).result(timeout=seconds)
    except cf.TimeoutError:
        raise RuntimeError("no answer in time") from None
    finally:
        ex.shutdown(wait=False, cancel_futures=True)


def _int(v) -> int | None:
    try:
        return int(float(v)) if v is not None else None
    except (TypeError, ValueError):
        return None


# ── scoring ──────────────────────────────────────────────────────────────────────────────────────────────────────────
def score_table(t: dict[str, Any], want: list[str], usage: dict[str, int], referenced: set[str],
                weights: dict[str, float] | None = None, matched: set[str] | None = None) -> tuple[float, list[str]]:
    """how well a table fits the description: its name (3), its columns (1.5 each word, at most twice, less in a very
    wide table), comments (1), each times the word's weight (a rare word in what was read counts more than a common
    one); a table the references name (+3), tables existing models already use (a little), empty tables (less).
    `matched` collects the words the table matched."""
    weights = weights or {}
    wide = min(1.0, math.sqrt(40 / max(40, len(t["columns"]))))     # 160 columns: column hits count half
    name_w = words(t["table"])
    col_w = [words(c["name"]) for c in t["columns"]]
    text = " ".join([t.get("comment") or ""] + [c.get("comment") or "" for c in t["columns"]]).casefold()
    score, why = 0.0, []
    used_name: set[str] = set()
    used_cols: set[str] = set()                         # a word of a name counts for one term only ("plant" ≈ "production")
    for term in want:
        vs = {term} | SYN.get(term, set())
        w = weights.get(term, 1.0)
        if (name_w - used_name) & vs:
            used_name |= name_w & vs
            score += (3.0 if term in name_w else 2.4) * w
            why.append(f"its name says {term}")
            if matched is not None:
                matched.add(term)
            continue
        cols = [c["name"] for c, w in zip(t["columns"], col_w) if w & vs and c["name"] not in used_cols]
        if cols:
            used_cols.update(cols)
            score += 1.5 * min(2, len(cols)) * (1 if any(term in x for x in col_w) else 0.8) * w * wide
            why.append(f"{', '.join(cols[:2])} {'match' if len(cols) > 1 else 'matches'} {term}")
            if matched is not None:
                matched.add(term)
            continue
        if any(re.search(r"(?<![a-z])" + re.escape(v) + r"[a-z]{0,3}(?![a-z])", text) for v in vs):
            score += 1.0 * w
            why.append(f"its description mentions {term}")
            if matched is not None:
                matched.add(term)
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


# load bookkeeping, not a business key: ETL_BATCH_ID, LOAD_ID, RECORD_SOURCE_ID, ROW_HASH_KEY …
TECHNICAL = mp.TECHNICAL_COLUMN
# scratch and copies: never offered as model tables
SCRATCH = re.compile(r"(?i)(^|_)(snowpark_temp|tmp|temp|scratch|bak|backup|old|copy|test|sandbox|stg_tmp)(_|$|\d)|^(my_first_dbt_model|hold_table)$")


def _keyish(col: str) -> bool:
    return not TECHNICAL.search(col) and (bool(mp.KEYISH.search(col)) or col.casefold().endswith(("_id", "_key", "_code", "_sk")))


def partners(anchored: list[dict[str, Any]], found: list[dict[str, Any]], room: int) -> list[dict[str, Any]]:
    """the tables an anchor joins to, best first: a shared key counts more the rarer it is in what was read (MACHINE_CODE in
    three tables beats EVENT_ID in forty), a table in the anchor's own schema counts most, a dimension or lookup table a
    little more, and the anchor's own identifier (EVENT_ID of an events table) little, since few tables reference it"""
    if room <= 0 or not anchored:
        return []
    holders: dict[str, int] = {}
    for r in found:
        for c in {c.casefold() for c in r["columns"] if _keyish(c)}:
            holders[c] = holders.get(c, 0) + 1
    total = max(2, len(found))
    own = {k for a in anchored for k in {c.casefold() for c in a["columns"] if _keyish(c)}
           if words(k.rsplit("_", 1)[0]) & words(a["table"])}           # EVENT_ID of FACT_DOWNTIME_EVENTS
    keys = {c.casefold() for a in anchored for c in a["columns"] if _keyish(c)}
    places = {(a["datasource_id"], a["schema"]) for a in anchored}
    names = {(a["datasource_id"], a["schema"], a["table"]) for a in anchored}
    def common(cols: set[str]) -> list[str]:
        """keys both tables carry, a qualified name counting too (SOURCE_PLANT_ID carries PLANT_ID)"""
        # the shorter name must itself be qualified: PLANT_ID inside SOURCE_PLANT_ID, never a bare ID inside EVENT_ID
        return sorted({k for k in keys for c in cols if c == k or ("_" in k and c.endswith("_" + k)) or ("_" in c and k.endswith("_" + c))})
    ranked = []
    for r in found:
        if (r["datasource_id"], r["schema"], r["table"]) in names:
            continue
        shared = common({c.casefold() for c in r["columns"] if _keyish(c)})
        if not shared:
            continue
        same = (r["datasource_id"], r["schema"]) in places
        if not same and len(shared) < 2:
            continue                                  # one shared name across schemas is too weak a sign without data checks
        rarity = sum(math.log(total / holders.get(k, 1)) * (0.3 if k in own else 1.0) for k in shared)
        dim = bool(re.match(r"(?i)^(dim|d|lu|lkp|lookup|ref)_", r["table"]))
        score = rarity + (4.0 if same else 0.0) + (1.0 if dim else 0.0)
        if score >= 2.5:
            ranked.append((score, r, shared, same))
    ranked.sort(key=lambda x: -x[0])
    return [dict(r, role="join", score=round(score, 2),
                 why=[f"shares {', '.join(shared[:2])} with {', '.join(a['table'] for a in anchored[:2])}" + ("" if same else f" (in {r['schema']})")] + r["why"])
            for score, r, shared, same in ranked[:room]]


def _group(r: dict[str, Any]) -> tuple[str, str, str]:
    """the dataset a table belongs to: a schema of up to 25 tables is one; in a larger one, a family of related tables
    (a synthetic dataset's prefix, a star schema's DIM_/FACT_ tables, else the first two words of the name)"""
    if r.get("_n", 0) <= 25:
        return (r["datasource_id"], r["schema"], "")
    import mosaic_discover as md
    return (r["datasource_id"], r["schema"], md._family_key(r["table"], r["schema"], r["datasource_id"]))


def pick_datasets(found: list[dict[str, Any]], want: list[str], usage: dict[str, int], referenced: set[str],
                  max_tables: int = 24, groups: int = 5) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """the tables to scan: words weighted by how rare they are in what was read ("churn" in 20 tables counts more than
    "customer" in 600), tables scored with those weights, then the best datasets (a dataset's best tables and how many
    of the words it covers), and from each its matching tables and the tables they join to. Returns (picked, matches)."""
    found = [r for r in found if not SCRATCH.search(r["table"])]
    n = max(2, len(found))
    hits: dict[str, int] = {}
    for r in found:
        got: set[str] = set()
        score_table(r["_t"], want, {}, set(), matched=got)
        r["_terms"] = got
        for term in got:
            hits[term] = hits.get(term, 0) + 1
    weights = {t: min(2.0, max(0.25, math.log(n / (1 + hits.get(t, 0))) / 2)) for t in want}
    for r in found:
        r["score"], r["why"] = score_table(r["_t"], want, usage, referenced, weights)
    top = sorted([r for r in found if r["score"] > 0], key=lambda r: -r["score"])
    if not top:
        return [], []
    by: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for r in found:
        by.setdefault(_group(r), []).append(r)
    ranked = []
    for key, rows in by.items():
        best = sorted((r for r in rows if r["score"] > 0), key=lambda r: -r["score"])
        if not best:
            continue
        covered = set().union(*(r["_terms"] for r in best))
        value = sum(r["score"] for r in best[:3]) + 2.0 * sum(weights.get(t, 1.0) for t in covered) + (1.0 if len(rows) > 1 else -3.0)
        ranked.append((value, key, best, rows))
    ranked.sort(key=lambda x: -x[0])
    floor = ranked[0][0] * 0.3
    picked: list[dict[str, Any]] = []
    per = max(3, max_tables // groups + 2)
    for value, key, best, rows in ranked[:groups]:
        if value < floor or len(picked) >= max_tables:
            break
        lead = best[0]["score"]
        matches = [dict(r, role="match") for r in best if r["score"] >= lead * 0.3][: max(2, per // 2)]
        mates = partners(matches, [r for r in rows if r["score"] < lead * 0.3 or r not in best[: len(matches)]], per - len(matches))
        picked += (matches + mates)[: max_tables - len(picked)]
    return picked, top


def find(m, query: str, scopes: list[dict[str, Any]] | None = None, *, references: list[dict[str, Any]] | None = None,
         usage: dict[str, int] | None = None, budget: float = 120.0, max_tables: int = 24, anchors: list[dict[str, str]] | None = None,
         datasets: int = 5, per_source: float | None = None, log=lambda s: None) -> dict[str, Any]:
    """{picked: [{datasource_id, datasource, dbms, schema, table, score, why, role}], read: [...], left: [...], terms}.

    anchors: tables the model starts from ({datasource, schema, table}); they are always picked (role "anchor"), the
    search words come from their names and keys when there is no description, and the tables that share a key column
    with them in any schema read are their join partners."""
    import mosaic_live as live
    import mosaic_matrix as matrix
    deadline = time.monotonic() + budget
    per_source = per_source or max(10.0, min(60.0, budget / 3))
    unreadable: list[str] = []
    refs = references or []
    want = terms(query + " " + " ".join(r.get("text", "")[:2000] for r in refs if r.get("kind") in ("document", "data", "image")))
    if not want and anchors:
        want = terms(" ".join(a["table"].replace("_", " ") for a in anchors))
    referenced = {str(e).split(".")[-1].strip('"`[] ').casefold() for r in refs for e in (r.get("entities") or [])}
    use = {k.casefold(): v for k, v in (usage or {}).items()}
    anchors = anchors or []
    # where to look: the named scopes, else every source this person can reach
    if scopes:
        targets = scopes
    else:
        rows = m.get("/api/datasources").json()
        targets = [{"datasource": d["id"]} for d in (rows.get("datasources") if isinstance(rows, dict) else rows) or [] if d.get("id")]
    cache: dict[str, dict] = {}
    work: list[tuple[float, dict[str, Any], str, list[str]]] = []
    pre: dict[tuple[str, str], list[dict[str, Any]]] = {}    # schemas already read with their whole source
    skipped_sources: list[str] = []
    for sc in targets:
        if time.monotonic() > deadline:               # listing every source is part of the budget too
            skipped_sources.append(str(sc.get("datasource")))
            continue
        try:
            info = live.datasource(m, sc["datasource"], cache)
        except Exception:  # noqa: BLE001 - a source that cannot be read is left out and said
            log(f"  · {sc['datasource']}: not readable, left out")
            continue
        schemas = [sc["schema"]] if sc.get("schema") else []
        source_deadline = min(deadline, time.monotonic() + per_source)    # one slow or broken source never holds the rest
        if not schemas and time.monotonic() < deadline:
            whole = catalog_tables(m, live, info, None, source_deadline)      # every schema at once, when the source allows it
            if whole is not None:
                log(f"  · {info['name']}: {len(whole)} schemas, {sum(len(x) for x in whole.values())} tables read from its catalog")
                for schema, tables in whole.items():
                    pre[(info["id"], schema)] = tables
                    hint = len(words(schema) & {x for w in want for x in {w} | SYN.get(w, set())}) * 2
                    work.append((hint, info, schema, sc.get("tables") or []))
                continue
        if not schemas:
            try:
                schemas = _bounded(lambda info=info: matrix.list_schemas(m, info["id"]), max(1.0, source_deadline - time.monotonic()))
            except Exception as e:  # noqa: BLE001 - a source that does not answer is said and skipped
                log(f"  · {info['name']}: not readable ({str(e)[:80] or 'no answer in time'}), left out")
                unreadable.append(info["name"])
                continue
        for schema in schemas:
            # schemas whose names fit, or whose tables existing models use, are read first
            hint = len(words(schema) & {x for w in want for x in {w} | SYN.get(w, set())}) * 2 + len(words(info["name"]) & set(want))
            work.append((hint, info, schema, sc.get("tables") or []))
    # the anchors' own schemas are read first, whatever their names
    anchor_ids: set[tuple[str, str]] = set()
    for a in anchors:
        try:
            ai = live.datasource(m, a["datasource"], cache)
        except Exception:  # noqa: BLE001
            continue
        anchor_ids.add((ai["id"], a["schema"]))
        if not any(w[1]["id"] == ai["id"] and w[2] == a["schema"] for w in work):
            work.append((1e6, ai, a["schema"], []))
    work = [(1e6 if (w[1]["id"], w[2]) in anchor_ids else w[0], *w[1:]) for w in work]
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
            tables, how = (pre[(info["id"], schema)], "catalog views") if (info["id"], schema) in pre else \
                _bounded(lambda info=info, schema=schema: schema_tables(m, live, matrix, info, schema, time.monotonic() + per_source), per_source + 5)
        except Exception as e:  # noqa: BLE001 - one schema that cannot be read never ends the search
            log(f"  {info['name']}/{schema}: not readable ({str(e)[:80]})")
            continue
        if patterns:
            tables = [t for t in tables if any(fnmatch.fnmatchcase(t["table"].upper(), p.upper()) for p in patterns)]
        best = None
        for t in tables:
            s, why = score_table(t, want, use, referenced)
            row = {"datasource_id": info["id"], "datasource": info["name"], "dbms": info["dbms"], "schema": schema, "table": t["table"],
                   "score": s, "why": why, "rows": t.get("rows"), "columns": [c["name"] for c in t["columns"]], "read": how, "_t": t, "_n": len(tables)}
            found.append(row)
            if s and (best is None or s > best["score"]):
                best = row
        read.append(f"{info['name']}/{schema}")
        log(f"  {info['name']}/{schema}: {len(tables)} tables" + (f"; best {best['table']} ({best['score']})" if best else "; nothing matches"))
    if skipped_sources:
        log(f"  · time budget reached before {len(skipped_sources)} source{'s' if len(skipped_sources) != 1 else ''} could be listed")
        left += [f"{x} (not listed)" for x in skipped_sources]
    found.sort(key=lambda r: -r["score"])
    is_anchor = lambda r: any(r["datasource_id"] == live.datasource(m, a["datasource"], cache)["id"] and r["schema"] == a["schema"]  # noqa: E731
                              and r["table"].casefold() == a["table"].casefold() for a in anchors)
    anchored = [dict(r, role="anchor", why=["you started from it"]) for r in found if anchors and is_anchor(r)]
    if anchors:
        out = anchored + partners(anchored, found, max_tables - len(anchored))
        return {"terms": want, "picked": [{k: v for k, v in p.items() if not k.startswith("_")} for p in out], "read": read, "left": left,
                "candidates": len(found)}
    picked, top = pick_datasets(found, want, use, referenced, max_tables, datasets)
    return {"terms": want, "picked": [{k: v for k, v in p.items() if not k.startswith("_")} for p in picked], "read": read, "left": left,
            "unreadable": unreadable, "candidates": len(top)}
