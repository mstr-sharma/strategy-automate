"""Find the tables that fit a description, from metadata only: table and column names, comments and descriptions, the
catalog's row counts, the tables existing models already use, and what the person's references name. No table is read:
each schema costs one query on its own catalog views (information_schema / pg_catalog), or a listing from Strategy's
catalog when the database has none we can read.

  find(m, "downtime by plant and shift", scopes=None)  → every source the person can reach, best schemas first
  find(m, "…", scopes=[{"datasource": "Snowflake-SE"}])                 → every schema of one source
  find(m, "…", scopes=[{"datasource": "…", "schema": "SALES"}])         → one schema
  find(m, "…", scopes=[{"datasource": "…", "schema": "…", "tables": ["FACT_*"]}])

The search stops at its time budget and reports incomplete catalogs and omitted requested tables. Explicit names
and selected patterns are seeds, not a filter on related metadata. Related tables are candidates for a scan, not
proof of a safe join: names alone cannot establish uniqueness, cardinality or metric additivity.
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
    for raw in re.findall(r"[A-Za-z][A-Za-z0-9']+", _split_camel(text or "")):
        if raw.casefold() in STOP or len(raw) < 3:
            continue
        w = _stem(raw)
        if w not in STOP and w not in out:
            out.append(w)
    return out


def words(name: str) -> set[str]:
    """a name's words: SNAKE_CASE, camelCase, spaces"""
    return {_stem(w) for w in re.findall(r"[A-Za-z][A-Za-z0-9]+", _split_camel(name or "").replace("_", " ")) if len(w) >= 2}


def _split_camel(value: str) -> str:
    return re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", value))


_IDENTIFIER = r'(?:"(?:[^"]|"")+"|`(?:[^`]|``)+`|\[(?:[^\]]|\]\])+\]|[\w$*?%]+)'


def _normal_name(value: str) -> str:
    """Normalize identifier quoting without treating a SQL-style [name] as a glob character class."""
    return ".".join(p.strip().strip('"`[]').casefold() for p in re.split(r"\s*\.\s*", str(value).strip()))


def _name_patterns(query: str) -> list[str]:
    return list(dict.fromkeys(_normal_name(m.group()) for m in re.finditer(_IDENTIFIER + r'(?:\s*\.\s*' + _IDENTIFIER + r')*', query or "")
                             if len(_normal_name(m.group())) >= 3 and _normal_name(m.group()) not in STOP))


def _matches(pattern: str, table: str, schema: str = "", source: str = "", source_id: str = "") -> bool:
    """A qualified selection must match its qualifiers; a bare selection matches only the table name."""
    pattern = _normal_name(pattern).replace("%", "*")
    names = [_normal_name(table)] if "." not in pattern else [
        _normal_name(f"{schema}.{table}"), _normal_name(f"{source}.{schema}.{table}"), _normal_name(f"{source_id}.{schema}.{table}")]
    return any(fnmatch.fnmatchcase(name, pattern) for name in names)


def _name_intent(query: str, table: str, schema: str = "", source: str = "", source_id: str = "") -> bool:
    patterns = _name_patterns(query)
    if any(_matches(p, table, schema, source, source_id) for p in patterns):
        return True
    # A single supplied prefix is a request for that family, including concatenated/camel-case names.
    return len(patterns) == 1 and len(patterns[0]) >= 4 and "." not in patterns[0] and _normal_name(table).startswith(patterns[0])


def _identity(row: dict[str, Any]) -> tuple[str, str, str]:
    return row["datasource_id"], row["schema"], row["table"]


def _partial(items: list[dict[str, Any]] | None, info: dict[str, Any], schema: str | None, reason: str, tables: int) -> None:
    if items is not None:
        item = {"datasource_id": info["id"], "datasource": info["name"], "schema": schema, "reason": reason, "tables": tables}
        if item not in items:
            items.append(item)


def _vocabulary(query: str, options: dict[str, Any] | None, *, limits: list[str] | None = None) -> tuple[bool, list[dict[str, str]]]:
    """One-hop, request-local vocabulary expansion. A domain activates only through its name, never its members."""
    options = options or {}
    builtin = options.get("builtin_synonyms", True) is not False
    text = " " + " ".join(re.findall(r"[a-z0-9]+", _split_camel(query).casefold().replace("_", " "))) + " "
    def mentions(label):
        phrase = " ".join(re.findall(r"[a-z0-9]+", _split_camel(label).casefold().replace("_", " ")))
        return bool(phrase) and " " + phrase + " " in text
    expanded: list[dict[str, str]] = []
    if builtin:
        for term in terms(query):
            for group in THESAURUS:
                if term in {_stem(v) for v in group}:
                    expanded += [{"kind": "builtin", "from": term, "to": v} for v in sorted(group) if _stem(v) != term]
    for group in (options.get("aliases") or [])[:128]:
        if not isinstance(group, list):
            continue
        labels = [v for v in group[:16] if isinstance(v, str) and 0 < len(v) <= 120]
        active = next((v for v in labels if mentions(v)), None)
        if active:
            expanded += [{"kind": "alias", "from": active, "to": v} for v in labels if not mentions(v)]
    for domain in (options.get("domains") or [])[:32]:
        if not isinstance(domain, dict) or not isinstance(domain.get("name"), str) or len(domain["name"]) > 120:
            continue
        if mentions(domain["name"]):
            expanded += [{"kind": "domain", "from": domain["name"], "to": v} for v in (domain.get("terms") or [])[:40]
                         if isinstance(v, str) and 0 < len(v) <= 120 and not mentions(v)]
    unique = {(e["kind"], e["from"], e["to"]): e for e in expanded}
    if len(unique) > 256 and limits is not None:
        limits.append("search vocabulary (256-expansion limit reached)")
    return builtin, list(unique.values())[:256]


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


def catalog_tables(m, live, info: dict[str, Any], schema: str | None, deadline: float | None = None,
                   *, partial: list[dict[str, Any]] | None = None) -> dict[str, list[dict[str, Any]]] | None:
    """Read catalog pages only. A successful empty catalog is {}, an unreadable catalog is None.
    Incomplete pages are retained with explicit coverage diagnostics, never represented as a complete source."""
    for kind, sql in dialects.catalog_queries(info["dbms"], schema):
        out: dict[str, dict[str, dict[str, Any]]] = {}
        page, ok, reason = 0, True, ""
        while True:
            if deadline is not None and time.monotonic() >= deadline:
                reason = "time_budget"
                break
            try:
                call = lambda sql=sql, page=page: live.run_sql(m, info["id"], _paged(info["dbms"], sql, page))
                rows = _bounded(call, deadline - time.monotonic()) if deadline is not None else call()
            except RuntimeError:
                ok = page > 0
                reason = "time_budget" if deadline is not None and time.monotonic() >= deadline else "catalog_page_failed"
                break
            for r in rows:
                t = out.setdefault(r["s"], {}).setdefault(r["t"], {"table": r["t"], "rows": _int(r.get("n")), "comment": r.get("tc") or "", "columns": []})
                if kind == "tables":
                    names = str(r.get("cols") or "").split(SEP)
                    notes = str(r.get("cc") or "").split(SEP) + [""] * len(names)
                    t["columns"] += [{"name": n, "comment": notes[i]} for i, n in enumerate(names) if n]
                    if _int(r.get("k")) and len(t["columns"]) < _int(r.get("k")):
                        ok = False
                else:
                    t["columns"].append({"name": r["c"], "comment": r.get("cc") or ""})
            if not ok or len(rows) < PAGE:
                break
            if page >= 199:
                reason = "page_limit"
                break
            page += 1
        if ok:
            result = {s_: list(ts.values()) for s_, ts in out.items()}
            if reason:
                _partial(partial, info, schema, reason, sum(len(ts) for ts in result.values()))
            return result
        if reason == "time_budget":
            _partial(partial, info, schema, reason, 0)
            return None
    return None


def schema_tables(m, live, matrix, info: dict[str, Any], schema: str, deadline: float | None = None, *,
                  query: str = "", preferred: list[str] | None = None, partial: list[dict[str, Any]] | None = None,
                  expansions: list[dict[str, str]] | None = None, builtin_synonyms: bool = True) -> tuple[list[dict[str, Any]], str]:
    """Catalog metadata; unsupported connectors use Strategy's table/column catalog. Column fetches are bounded
    and prioritize requested names and relevant names, rather than the first forty alphabetic tables."""
    got = catalog_tables(m, live, info, schema, deadline, partial=partial)
    if got:                                                 # an empty catalog (privileges, name case) falls back to Strategy's
        # BigQuery catalogs omit the project qualifier. Prefer the exact namespace, then an unambiguous alias.
        if schema in got:
            return got[schema], "catalog views"
        aliases = [v for k, v in got.items() if _normal_name(k) == _normal_name(schema) or _normal_name(schema).endswith("." + _normal_name(k))]
        return (aliases[0] if len(aliases) == 1 else []), "catalog views"
    if deadline is not None and time.monotonic() >= deadline:
        return [], "catalog API"
    import build_mosaic as bm
    names = matrix.list_tables(m, info["id"], schema)
    want = terms(query)
    def priority(name):
        selected = any(_matches(p, name, schema, info["name"], info["id"]) for p in preferred or [])
        exact = _name_intent(query, name, schema, info["name"], info["id"])
        score, _ = score_table({"table": name, "columns": [], "comment": ""}, want, {}, set(), expansions=expansions, builtin_synonyms=builtin_synonyms)
        return (-int(selected), -int(exact), -score, name.casefold())
    ordered = sorted(set(names), key=priority)
    ranks = {name: priority(name) for name in ordered}
    name_words = {name: words(name) for name in ordered}
    pending, metadata, entities = set(ordered), {}, set()
    for _ in range(min(40, len(ordered))):
        if deadline is not None and time.monotonic() >= deadline:
            break
        # After reading a seed, its named keys prioritize possible dimension/lookup names for the next description.
        name = min(pending, key=lambda n: (*ranks[n][:2], -len(name_words[n] & entities), *ranks[n][2:]))
        pending.remove(name)
        try:
            md = bm.fetch_table_metadata(m, info["id"], schema, name, required=False) or {}
            cols = [{"name": c.get("name") or c.get("columnName"), "comment": c.get("description") or ""} for c in md.get("columns", [])]
            metadata[name] = [c for c in cols if c["name"]]
            entities.update(word for c in metadata[name] if _keyish(c["name"]) for word in words(_key_name(c["name"]).rsplit("_", 1)[0]))
        except Exception:  # noqa: BLE001 - the table remains discoverable by its name
            metadata[name] = []
    tables = [{"table": name, "rows": None, "comment": "", "columns": metadata.get(name, [])} for name in ordered]
    if sum(bool(cols) for cols in metadata.values()) < len(tables):
        _partial(partial, info, schema, "column_metadata_limit", len(tables))
    return tables, "catalog API"


def _bounded(fn, seconds: float):
    """fn() with a time limit: a source that hangs (unreachable, retrying) is given up on, never waited for"""
    import concurrent.futures as cf
    if seconds <= 0:
        raise RuntimeError("metadata time budget reached")
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
                weights: dict[str, float] | None = None, matched: set[str] | None = None, *,
                expansions: list[dict[str, str]] | None = None, builtin_synonyms: bool = True) -> tuple[float, list[str]]:
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
        vs = {term} | (SYN.get(term, set()) if builtin_synonyms else set())
        w = weights.get(term, 1.0)
        if (name_w - used_name) & vs:
            used_name |= name_w & vs
            score += (3.0 if term in name_w else 2.4) * w
            why.append(f"its name says {term}" if term in name_w else f"its name uses a related term for {term}")
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
    aliases: dict[tuple[str, str], tuple[float, str]] = {}
    for expansion in expansions or []:
        if expansion["kind"] == "builtin":
            continue  # the weighted built-in synonyms were handled in the ordinary scoring pass
        variant = words(expansion["to"])
        if not variant:
            continue
        bonus, location = 0.0, ""
        if variant <= name_w and not variant <= used_name:
            bonus, location = 1.8, "its name"
        elif any(variant <= tokens and c["name"] not in used_cols for c, tokens in zip(t["columns"], col_w)):
            bonus, location = 0.9 * wide, "its columns"
        elif any(variant <= words(note or "") for note in [t.get("comment")] + [c.get("comment") for c in t["columns"]]):
            bonus, location = 0.5, "its description"
        if expansion["kind"] == "domain":
            bonus *= 0.75
        key = expansion["kind"], expansion["from"]
        if bonus and (key not in aliases or bonus > aliases[key][0]):
            aliases[key] = (bonus, f"{location} matches {expansion['to']} through configured {expansion['kind']} {expansion['from']}")
            if matched is not None:
                matched.update(terms(expansion["from"]))
    score += min(6.0, sum(value[0] for value in aliases.values()))
    why.extend(value[1] for value in aliases.values())
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


def _key_name(col: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", _split_camel(col).casefold()).strip("_")


def _keyish(col: str) -> bool:
    normalized = _key_name(col)
    return not TECHNICAL.search(normalized) and bool(mp.KEYISH.search(normalized))


def _key_forms(col: str) -> set[str]:
    """Retain qualified key names and their qualified suffixes; never turn CUSTOMER_ID into bare ID."""
    name = _key_name(col)
    bits = name.split("_")
    if len(bits) < 2:
        return set()
    return {"_".join(bits[i:]) for i in range(len(bits) - 1)}


def _dimension(row: dict[str, Any]) -> bool:
    if re.search(r"(?i)(^|_)(dim|d|lu|lkp|lookup|ref)(_|$)", _key_name(row["table"])):
        return True
    if re.search(r"(?i)(^|_)(fact|fct|factless)(_|$)", _key_name(row["table"])):
        return False
    columns = row["columns"]
    owns = any(words(_key_name(c).rsplit("_", 1)[0]) & words(row["table"]) for c in columns if _keyish(c))
    descriptors = [c for c in columns if not _keyish(c) and not TECHNICAL.search(_key_name(c))]
    return owns and bool(descriptors) and not any(mp.MEASURE_NUMBER.search(c) for c in descriptors)


def partners(anchored: list[dict[str, Any]], found: list[dict[str, Any]], room: int) -> list[dict[str, Any]]:
    """Bounded metadata candidate closure across the searched sources. Named keys identify possible neighbors,
    not validated joins. Clear dimension ownership permits single-key cross-store candidates; generic keys alone
    do not. Up to three hops retain snowflake parents without expanding through arbitrary unrelated facts."""
    if room <= 0 or not anchored:
        return []
    rows = {_identity(r): r for r in found if not SCRATCH.search(r["table"]) or r.get("_selection")}
    rows.update({_identity(r): r for r in anchored})
    forms: dict[tuple[str, str, str], set[str]] = {}
    index: dict[str, set[tuple[str, str, str]]] = {}
    for identity, row in rows.items():
        keys = {form for col in row["columns"] if _keyish(col) for form in _key_forms(col)}
        forms[identity] = keys
        for key in keys:
            index.setdefault(key, set()).add(identity)
    chosen = {_identity(a) for a in anchored}
    frontier = list(chosen)
    output: list[dict[str, Any]] = []
    total = max(2, len(rows))
    generic = {"id", "key", "code", "type", "status", "reason", "record", "event", "date", "time"}
    for depth in range(1, 4):
        ranked: dict[tuple[str, str, str], tuple[float, list[str], tuple[str, str, str], bool]] = {}
        for origin in frontier:
            anchor = rows[origin]
            candidates = set().union(*(index[k] for k in forms[origin])) if forms[origin] else set()
            own = {k for k in forms[origin] if words(k.rsplit("_", 1)[0]) & words(anchor["table"])}
            for identity in candidates - chosen:
                row = rows[identity]
                shared = forms[origin] & forms[identity]
                # A suffix and its qualified form describe one signal, not two independent keys.
                shared = {k for k in shared if not any(other != k and other.endswith("_" + k) for other in shared)}
                same = identity[:2] == origin[:2]
                owned = any((words(k.rsplit("_", 1)[0]) - generic) & words(row["table"]) for k in shared)
                if not same and len(shared) < 2 and not (_dimension(row) and owned):
                    continue
                rarity = sum(math.log(total / max(1, len(index[k]))) * (0.3 if k in own else 1.0) for k in shared)
                score = rarity + (4.0 if same else 0.0) + (1.0 if _dimension(row) else 0.0) + (2.0 if owned else 0.0) - (depth - 1) * 0.5
                if score < 2.5:
                    continue
                old = ranked.get(identity)
                if old is None or score > old[0]:
                    ranked[identity] = (score, sorted(shared), origin, same)
        if not ranked:
            break
        frontier = []
        for identity, (score, shared, origin, same) in sorted(ranked.items(), key=lambda pair: (-pair[1][0], pair[0]))[:room - len(output)]:
            row, anchor = rows[identity], rows[origin]
            chosen.add(identity)
            output.append(dict(row, role="join", selection="relationship_candidate", score=round(score, 2),
                               relationship={"evidence": "shared_key_metadata", "verified": False,
                                             "via": {"datasource_id": origin[0], "schema": origin[1], "table": origin[2]}, "depth": depth},
                               why=[f"shares {', '.join(shared[:2])} with {anchor['table']}" +
                                    ("" if same else f" (across {row['schema']})") + "; candidate relationship, not validated"] + row["why"]))
            # Only dimensions/lookup-like tables can extend the search beyond its immediate neighborhood.
            if _dimension(row) or any(words(k.rsplit("_", 1)[0]) & words(row["table"]) for k in forms[identity]):
                frontier.append(identity)
        if len(output) >= room or not frontier:
            break
    return output


def _group(r: dict[str, Any]) -> tuple[str, str, str]:
    """the dataset a table belongs to: a schema of up to 25 tables is one; in a larger one, a family of related tables
    (a synthetic dataset's prefix, a star schema's DIM_/FACT_ tables, else the first two words of the name)"""
    if r.get("_n", 0) <= 25:
        return (r["datasource_id"], r["schema"], "")
    import mosaic_discover as md
    return (r["datasource_id"], r["schema"], md._family_key(r["table"], r["schema"], r["datasource_id"]))


def _spread_selections(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """When a broad selected prefix exceeds the cap, give each selected source/schema a share before its next turn."""
    buckets: dict[tuple[int, str, str], list[dict[str, Any]]] = {}
    for row in sorted(rows, key=_identity):
        priority = 0 if row.get("_selection") == "anchor" else row.get("_selection_priority", 1)
        buckets.setdefault((priority, row["datasource_id"], row["schema"]), []).append(row)
    result = []
    for priority in sorted({k[0] for k in buckets}):
        groups = [iter(rows) for key, rows in sorted(buckets.items()) if key[0] == priority]
        while groups:
            remaining = []
            for group in groups:
                row = next(group, None)
                if row is not None:
                    result.append(row)
                    remaining.append(group)
            groups = remaining
    return result


def pick_datasets(found: list[dict[str, Any]], want: list[str], usage: dict[str, int], referenced: set[str],
                  max_tables: int = 24, groups: int = 5, *, expansions: list[dict[str, str]] | None = None,
                  builtin_synonyms: bool = True) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Preserve supplied names first, then select relevant dataset seeds and their global metadata neighbors.
    Dataset families guide ranking; they are never a wall that hides cross-schema or cross-source dimensions."""
    found = [r for r in found if not SCRATCH.search(r["table"]) or r.get("_selection")]
    max_tables = max(0, max_tables)
    groups = max(1, groups)
    n = max(2, len(found))
    hits: dict[str, int] = {}
    for r in found:
        got: set[str] = set()
        score_table(r["_t"], want, {}, set(), matched=got, expansions=expansions, builtin_synonyms=builtin_synonyms)
        r["_terms"] = got
        for term in got:
            hits[term] = hits.get(term, 0) + 1
    weights = {t: min(2.0, max(0.25, math.log(n / (1 + hits.get(t, 0))) / 2)) for t in want}
    for r in found:
        r["score"], r["why"] = score_table(r["_t"], want, usage, referenced, weights, expansions=expansions, builtin_synonyms=builtin_synonyms)
        if r.get("_selection"):
            r["score"] += 20.0
            r["why"].insert(0, "you started from it" if r["_selection"] == "anchor" else "matches your selected table name or pattern")
        elif not want:
            # Browsing an explicit source/schema still yields useful, reviewable candidates without query prose.
            r["score"] += 1.0 + min(2.0, math.log2(1 + usage.get(r["table"].casefold(), 0)))
            if _dimension(r) or re.search(r"(?i)(^|_)(fact|fct)(_|$)", r["table"]):
                r["score"] += 1.0
            r["why"].append("metadata candidate in the selected area")
    top = sorted([r for r in found if r["score"] > 0], key=lambda r: (-r["score"], _identity(r)))
    if not top:
        return [], []
    explicit = _spread_selections([r for r in found if r.get("_selection")])
    picked = [dict(r, role="anchor" if r["_selection"] == "anchor" else "match", selection=r["_selection"]) for r in explicit[:max_tables]]
    if explicit:
        picked += partners(picked, found, max_tables - len(picked))
        present = {_identity(r) for r in picked}
        for row in top:
            if len(picked) >= max_tables:
                break
            if _identity(row) not in present and any("configured " in why or "related term" in why for why in row["why"]):
                picked.append(dict(row, role="match", selection="metadata_match"))
                present.add(_identity(row))
        return picked, top
    by: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for r in found:
        by.setdefault(_group(r), []).append(r)
    ranked = []
    for key, rows in by.items():
        best = sorted((r for r in rows if r["score"] > 0), key=lambda r: (-r["score"], _identity(r)))
        if not best:
            continue
        covered = set().union(*(r["_terms"] for r in best))
        value = sum(r["score"] for r in best[:3]) + 2.0 * sum(weights.get(t, 1.0) for t in covered) + (1.0 if len(rows) > 1 else -3.0)
        ranked.append((value, key, best))
    ranked.sort(key=lambda x: (-x[0], x[1]))
    floor = (ranked[0][0] * 0.3 if ranked[0][0] > 0 else ranked[0][0]) if want else float("-inf")
    eligible = [item for item in ranked if item[0] >= floor][:groups]
    per = max(3, max_tables // max(1, len(eligible)) + 2)
    seen: set[tuple[str, str, str]] = set()
    for _value, _key, best in eligible:
        lead = best[0]["score"]
        matches = [dict(r, role="match", selection="metadata_match") for r in best
                   if r["score"] >= lead * 0.3 and _identity(r) not in seen][:max(2, per // 2)]
        available = [r for r in found if _identity(r) not in seen]
        mates = partners(matches, available, per - len(matches))
        for row in (matches + mates)[:max_tables - len(picked)]:
            if _identity(row) not in seen:
                picked.append(row)
                seen.add(_identity(row))
    # Fill remaining room with connected parents that fell outside an individual dataset's share.
    picked += partners(picked, [r for r in found if _identity(r) not in seen], max_tables - len(picked))
    return picked, top


def find(m, query: str, scopes: list[dict[str, Any]] | None = None, *, references: list[dict[str, Any]] | None = None,
         usage: dict[str, int] | None = None, budget: float = 120.0, max_tables: int = 24, anchors: list[dict[str, str]] | None = None,
         datasets: int = 5, per_source: float | None = None, log=lambda s: None,
         search_options: dict[str, Any] | None = None) -> dict[str, Any]:
    """Find metadata candidates within the requested source/schema boundaries. Selected names/patterns and anchors
    get first claim on max_tables; related candidates may use any searched schema/source. `partial` records
    incomplete metadata and `omitted` distinguishes limits, missing tables and unreadable/unvisited areas."""
    import mosaic_live as live
    import mosaic_matrix as matrix
    deadline = time.monotonic() + budget
    per_source = per_source or max(10.0, min(60.0, budget / 3))
    refs, anchors = references or [], anchors or []
    if not query.strip() and not scopes and not anchors:
        raise ValueError("Describe what to find, select a source or schema, or name starting tables")
    vocabulary_limits: list[str] = []
    builtin_synonyms, expansions = _vocabulary(query, search_options, limits=vocabulary_limits)
    want = terms(query + " " + " ".join(r.get("text", "")[:2000] for r in refs if r.get("kind") in ("document", "data", "image")))
    if not want and anchors:
        want = terms(" ".join(a["table"] for a in anchors))
    referenced = {_normal_name(str(e)).split(".")[-1] for r in refs for e in (r.get("entities") or [])}
    use = {k.casefold(): v for k, v in (usage or {}).items()}
    partial: list[dict[str, Any]] = []
    omitted: list[dict[str, Any]] = []
    read: list[str] = []
    left: list[str] = list(vocabulary_limits)
    unreadable: list[str] = []
    cache: dict[str, dict] = {}
    resolved: dict[str, dict[str, Any]] = {}
    namespace_cache: dict[str, list[str]] = {}
    seen_schemas: set[tuple[str, str]] = set()
    found_by_id: dict[tuple[str, str, str], dict[str, Any]] = {}
    if scopes:
        targets = list(scopes)
    elif time.monotonic() < deadline:
        rows = _bounded(lambda: m.get("/api/datasources").json(), deadline - time.monotonic())
        targets = [{"datasource": d["id"]} for d in (rows.get("datasources") if isinstance(rows, dict) else rows) or [] if d.get("id")]
    else:
        targets = []
        left.append("data sources (not listed)")
    # Read explicitly chosen anchors before enumerating whole sources, so broad catalogs cannot consume their budget.
    targets = [{"datasource": a["datasource"], "schema": a["schema"], "tables": [a["table"]]} for a in anchors] + targets

    def canonical_schema(info, requested, until):
        if info["id"] not in namespace_cache and time.monotonic() < until:
            try:
                namespace_cache[info["id"]] = _bounded(lambda: matrix.list_schemas(m, info["id"]), until - time.monotonic())
            except Exception:  # noqa: BLE001 - the SQL catalog may still work
                return requested
        names = namespace_cache.get(info["id"], [])
        if requested in names:
            return requested
        matches = [n for n in names if _normal_name(n) == _normal_name(requested)]
        return matches[0] if len(matches) == 1 else requested

    def add_tables(info, schema, tables, how):
        seen_schemas.add((info["id"], schema))
        label = f"{info['name']}/{schema}"
        if label not in read:
            read.append(label)
        for table in tables:
            score, why = score_table(table, want, use, referenced, expansions=expansions, builtin_synonyms=builtin_synonyms)
            row = {"datasource_id": info["id"], "datasource": info["name"], "dbms": info["dbms"], "schema": schema,
                   "table": table["table"], "score": score, "why": why, "rows": table.get("rows"),
                   "columns": [c["name"] for c in table["columns"]], "read": how, "_t": table, "_n": len(tables)}
            previous = found_by_id.get(_identity(row))
            if previous is None or len(row["columns"]) > len(previous["columns"]):
                found_by_id[_identity(row)] = row
        log(f"  {label}: {len(tables)} tables of metadata")

    for number, scope in enumerate(targets):
        source = str(scope["datasource"])
        label = source + ("/" + scope["schema"] if scope.get("schema") else "")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            left.append(label + " (not read)")
            continue
        until = time.monotonic() + min(per_source, remaining / max(1, len(targets) - number))
        try:
            info = resolved.get(source)
            if info is None:
                info = _bounded(lambda source=source: live.datasource(m, source, cache), until - time.monotonic())
                resolved[source] = info
        except (Exception, SystemExit):  # noqa: BLE001 - an unavailable source never suppresses the remaining sources
            unreadable.append(label)
            log(f"  · {label}: source metadata is not readable")
            continue
        preferred = scope.get("tables") or scope.get("patterns") or []
        if scope.get("schema"):
            schemas = [canonical_schema(info, scope["schema"], until)]
            whole = None
        else:
            local_partial: list[dict[str, Any]] = []
            try:
                whole = _bounded(lambda info=info, until=until, local_partial=local_partial:
                                 catalog_tables(m, live, info, None, until, partial=local_partial), until - time.monotonic())
                partial.extend(local_partial)
            except Exception:  # noqa: BLE001 - try the connector's metadata API while this source has budget
                whole = None
                reason = "time_budget" if time.monotonic() >= until else "catalog_page_failed"
                _partial(partial, info, None, reason, 0)
            if whole:                                       # empty: list the schemas through Strategy instead
                for schema, tables in whole.items():
                    add_tables(info, schema, tables, "catalog views")
                continue
            try:
                schemas = namespace_cache.get(info["id"])
                if schemas is None:
                    if time.monotonic() >= until:
                        raise RuntimeError("metadata time budget reached")
                    schemas = _bounded(lambda info=info: matrix.list_schemas(m, info["id"]), until - time.monotonic())
                    namespace_cache[info["id"]] = schemas
            except Exception:  # noqa: BLE001
                unreadable.append(info["name"])
                continue
        expanded_terms = {x for w in want for x in {w} | (SYN.get(w, set()) if builtin_synonyms else set())}
        expanded_terms.update(token for e in expansions for token in words(e["to"]))
        schemas = sorted(schemas, key=lambda schema: (-len(words(schema) & expanded_terms), schema))
        for schema in schemas:
            if (info["id"], schema) in seen_schemas:
                continue
            if time.monotonic() >= until:
                left.append(f"{info['name']}/{schema}")
                continue
            try:
                local_partial: list[dict[str, Any]] = []
                tables, how = _bounded(lambda info=info, schema=schema, until=until, preferred=preferred, local_partial=local_partial: schema_tables(
                    m, live, matrix, info, schema, until, query=query, preferred=preferred, partial=local_partial,
                    expansions=expansions, builtin_synonyms=builtin_synonyms), until - time.monotonic())
                partial.extend(local_partial)
                add_tables(info, schema, tables, how)
            except Exception:  # noqa: BLE001
                if time.monotonic() >= until:
                    left.append(f"{info['name']}/{schema}")
                else:
                    unreadable.append(f"{info['name']}/{schema}")
                log(f"  · {info['name']}/{schema}: table metadata was not read")

    found = list(found_by_id.values())
    requests: list[tuple[dict[str, Any], str, str]] = []
    for scope in scopes or []:
        for pattern in scope.get("tables") or scope.get("patterns") or []:
            requests.append((scope, pattern, "scope_pattern"))
    requests += [(a, a["table"], "anchor") for a in anchors]
    for row in found:
        if _name_intent(query, row["table"], row["schema"], row["datasource"], row["datasource_id"]):
            row["_selection"] = "explicit_name"
            literal = any(not any(mark in p for mark in "*?%") and _matches(p, row["table"], row["schema"], row["datasource"], row["datasource_id"])
                          for p in _name_patterns(query))
            row["_selection_priority"] = 1 if literal else 2
    for scope, pattern, selection in requests:
        info = resolved.get(str(scope["datasource"]))
        matches = [r for r in found if info and r["datasource_id"] == info["id"]
                   and (not scope.get("schema") or _normal_name(r["schema"]) == _normal_name(scope["schema"]))
                   and _matches(pattern, r["table"], r["schema"], r["datasource"], r["datasource_id"])]
        for row in matches:
            if selection == "anchor" or row.get("_selection") != "anchor":
                row["_selection"] = selection
                priority = 1 if not any(mark in pattern for mark in "*?%") else 2
                row["_selection_priority"] = min(priority, row.get("_selection_priority", priority))
        if not matches:
            source_name = info["name"] if info else str(scope["datasource"])
            relevant = [p for p in partial if info and p["datasource_id"] == info["id"] and p["reason"] != "column_metadata_limit" and
                        (not scope.get("schema") or p["schema"] is None or _normal_name(p["schema"]) == _normal_name(scope["schema"]))]
            was_read = any(info and ds == info["id"] and (not scope.get("schema") or _normal_name(sc) == _normal_name(scope["schema"]))
                           for ds, sc in seen_schemas)
            reason = "not_read" if relevant or not was_read else "not_found"
            if any(label == source_name or label == str(scope["datasource"]) or label.startswith(source_name + "/") for label in unreadable):
                reason = "unreadable"
            omitted.append({"datasource": source_name, "schema": scope.get("schema"), "table": pattern, "reason": reason})
    picked, top = pick_datasets(found, want, use, referenced, max_tables, datasets, expansions=expansions, builtin_synonyms=builtin_synonyms)
    selected_ids = {_identity(p) for p in picked}
    for row in found:
        if row.get("_selection") and _identity(row) not in selected_ids:
            omitted.append({"datasource_id": row["datasource_id"], "datasource": row["datasource"], "schema": row["schema"],
                            "table": row["table"], "reason": "table_limit"})
    log(f"→ Selected {len(picked)} tables; {len(omitted)} requested selections omitted; {len(partial)} incomplete metadata areas")
    return {"terms": want, "picked": [{k: v for k, v in p.items() if not k.startswith("_")} for p in picked],
            "read": list(dict.fromkeys(read)), "left": list(dict.fromkeys(left)), "unreadable": list(dict.fromkeys(unreadable)),
            "partial": partial, "omitted": omitted, "expansions": expansions, "expansions_truncated": bool(vocabulary_limits), "candidates": len(top)}
