"""The plan and its check, for the plan → check → apply → prove builder (see ../REBUILD.md). Pure: no Strategy calls.

A plan is the whole model as data: tables, attributes (forms with one expression per table, in that table's own column
spelling), fact metrics, relationships (each with the table that holds both ends), derived and conditional metrics.
`from_spec` turns a model specification (Ace's draft shape) into a plan without re-deciding anything the specification
says; it only adds what the specification leaves implicit — the relationship from every attribute to the key of each
table it sits on — using the data profile to find each table's key. `check` refuses a plan Strategy would refuse or
that could not answer questions, before anything is written.
"""
from __future__ import annotations

import copy
import re
from typing import Any

FUNCS = {"sum", "avg", "count", "count_distinct", "min", "max", "first", "last", "median"}
NUMERIC = {"integer", "int32", "int64", "big_decimal", "decimal", "double", "float", "real", "numeric", "fixed_length_number", "number"}
TEXT = {"utf8_char", "char", "varchar", "fixed_length_string", "string", "nvarchar", "nchar", "text", "variable_length_string"}
TIME = {"date", "time", "timestamp", "datetime"}
KEYISH = re.compile(r"(?:^|_)(?:id|key|number|num|no|code)$", re.I)


class PlanError(ValueError):
    """the specification cannot become a plan (names a column or table that is not there)"""


def _family(dtype: dict | str | None) -> str:
    t = (dtype.get("type") if isinstance(dtype, dict) else dtype or "").lower()
    return "number" if t in NUMERIC else "text" if t in TEXT else "time" if t in TIME else t or "unknown"


# ── catalog lookups ──────────────────────────────────────────────────────────────────────────────────────────────────
class Catalog:
    def __init__(self, cat: dict[str, Any]):
        self.tables = {t["table"]: t for t in cat["tables"]}
        self._fold = {t.casefold(): t for t in self.tables}

    def table(self, name: str) -> str:
        real = self._fold.get(name.casefold())
        if not real:
            raise PlanError(f"table {name} is not among the selected tables")
        return real

    def column(self, table: str, name: str) -> dict[str, Any]:
        t = self.tables[self.table(table)]
        hit = [c for c in t["columns"] if c["name"].casefold() == name.casefold()]
        if not hit:
            raise PlanError(f"column {name} is not on {t['table']}")
        return hit[0]


# ── from a specification ─────────────────────────────────────────────────────────────────────────────────────────────
def from_spec(spec: dict[str, Any], cat: dict[str, Any], prof: dict[str, Any] | None = None) -> dict[str, Any]:
    c = Catalog(cat)
    prof = prof or {}
    plan: dict[str, Any] = {
        "name": spec["name"], "description": spec.get("description", ""), "serve_mode": spec.get("serve_mode", "in_memory"),
        "tables": [], "attributes": [], "metrics": [], "relationships": [], "derived": copy.deepcopy(spec.get("derived", [])),
        "conditional": copy.deepcopy(spec.get("conditional", [])), "notes": [], "keys": {},
    }
    for s in spec["sources"]:
        t = c.tables[c.table(s["table"])]
        plan["tables"].append({k: t[k] for k in ("datasource_id", "datasource", "dbms", "schema", "table", "columns")})

    for a in spec["attributes"]:
        id_exprs, descs = [], []
        for f in a["forms"]:
            tname = c.table(f["table"])
            col = c.column(tname, f["column"])["name"]          # the table's own spelling
            if f.get("category", "DESC") == "ID":
                id_exprs.append({"table": tname, "column": col})
            else:
                descs.append({"name": f["name"], "table": tname, "column": col})
        if not id_exprs:
            raise PlanError(f"attribute {a['name']} has no ID form")
        lookup = c.table(a["lookup_table"]) if a.get("lookup_table") else id_exprs[0]["table"]
        forms = [{"name": next((f["name"] for f in a["forms"] if f.get("category") == "ID"), "ID"), "category": "ID", "expressions": id_exprs}]
        forms += [{"name": d["name"], "category": "DESC", "expressions": [{"table": d["table"], "column": d["column"]}]} for d in descs]
        plan["attributes"].append({"name": a["name"], "description": a.get("description", ""), "lookup": lookup, "forms": forms, "time": bool(a.get("time"))})

    for mt in spec["metrics"]:
        tname = c.table(mt["table"])
        plan["metrics"].append({"name": mt["name"], "description": mt.get("description", ""), "table": tname,
                                "column": c.column(tname, mt["column"])["name"], "function": (mt.get("function") or "sum").lower(),
                                "format": mt.get("format", "fixed2")})

    keys = _table_keys(plan, prof)
    plan["keys"] = {t: k["attribute"] for t, k in keys.items() if k.get("attribute")}
    plan["notes"] += [k["note"] for k in keys.values() if k.get("note")]
    plan["relationships"] = _relationships(plan, keys, prof)
    _explicit(plan, spec.get("relationships", []), c)
    return plan


def _id_columns(attr: dict) -> dict[str, str]:
    return {e["table"]: e["column"] for e in attr["forms"][0]["expressions"]}


def _unique(prof: dict, table: str, column: str) -> bool | None:
    p = prof.get(table) or {}
    if not p.get("measured"):
        return None
    d = (p.get("distinct") or {}).get(column)
    return None if d is None else d == p.get("rows") and not (p.get("nulls") or {}).get(column)


def _table_keys(plan: dict, prof: dict) -> dict[str, dict]:
    """each table's key attribute: unique on the table (measured) and designated by the specification (its lookup is
    this table, it is shared with other tables, it has name forms). Ties are refused, not guessed."""
    out: dict[str, dict] = {}
    for t in (x["table"] for x in plan["tables"]):
        scored = []
        for a in plan["attributes"]:
            ids = _id_columns(a)
            if t not in ids:
                continue
            uniq = _unique(prof, t, ids[t])
            if uniq is False:
                continue
            score = (4 if a["lookup"] == t else 0) + (2 if len(ids) > 1 else 0) + (1 if len(a["forms"]) > 1 else 0) + (1 if KEYISH.search(ids[t]) else 0)
            scored.append((score, uniq, a["name"]))
        if not scored:
            out[t] = {"attribute": None, "note": f"{t} has no single-column key among its attributes; its attributes relate to the rest of the model only through the attributes it shares."}
            continue
        scored.sort(reverse=True)
        best = scored[0]
        if len(scored) > 1 and scored[1][0] == best[0]:
            out[t] = {"attribute": None, "ambiguous": [s[2] for s in scored if s[0] == best[0]],
                      "note": f"{t}: {' and '.join(s[2] for s in scored if s[0] == best[0])} could each be its key; name the table's key in the specification."}
            continue
        out[t] = {"attribute": best[2], "measured": best[1] is True,
                  "note": None if best[1] else f"{t}: the key {best[2]} is taken from the specification; its uniqueness could not be measured on this source."}
    return out


def _relationships(plan: dict, keys: dict[str, dict], prof: dict) -> list[dict]:
    """every attribute on a table relates to that table's key, on that table"""
    rels = []
    for t, k in keys.items():
        key = k.get("attribute")
        if not key:
            continue
        for a in plan["attributes"]:
            ids = _id_columns(a)
            if a["name"] == key or t not in ids:
                continue
            # one-to-one only between two keys (a shipment and its one invoice); a descriptor that happens to be unique
            # in a small table (4 carriers, 4 service levels) is still one-to-many
            one = _unique(prof, t, ids[t]) is True and any(o.get("attribute") == a["name"] for o in keys.values())
            rels.append({"parent": a["name"], "child": key, "table": t, "type": "one_to_one" if one else "one_to_many", "source": "key"})
    # Strategy keeps one relationship per pair of attributes, on one table: two fact tables keyed the same way (telemetry
    # and usage snapshots, both by usage) would give the pair twice, and the second is refused (HTTP 400). Keep the one
    # on the child's lookup table, else the first.
    lookup = {a["name"]: a["lookup"] for a in plan["attributes"]}
    best: dict[tuple[str, str], dict] = {}
    for r in rels:
        pair = (r["parent"], r["child"])
        if pair not in best or (r["table"] == lookup.get(r["child"]) and best[pair]["table"] != lookup.get(r["child"])):
            best[pair] = r
    return list(best.values())


def _explicit(plan: dict, explicit: list[dict], c: Catalog) -> None:
    """specification relationships (TABLE.COLUMN ends) join the plan; one between two attributes the plan already
    relates replaces that one. A relationship whose two ends are the same attribute (a key and the same key on another
    table) is the shared attribute itself, which the key relationships already cover."""
    by_col = {}
    for a in plan["attributes"]:
        for f in a["forms"]:
            for e in f["expressions"]:
                by_col[(e["table"].casefold(), e["column"].casefold())] = a["name"]

    def attr(ref: str) -> str | None:
        t, _, col = ref.partition(".")
        return by_col.get((t.casefold(), col.casefold()))
    for r in explicit:
        p, ch = attr(r["parent"]), attr(r["child"])
        if not p or not ch:
            plan["notes"].append(f"Relationship {r['parent']} → {r['child']} names a column that is not an attribute form; left out.")
            continue
        if p == ch:
            continue
        table = c.table(r.get("relationship_table") or r["child"].partition(".")[0])
        plan["relationships"] = [x for x in plan["relationships"] if {x["parent"], x["child"]} != {p, ch}]
        plan["relationships"].append({"parent": p, "child": ch, "table": table, "type": r.get("type", "one_to_many"), "source": "specification"})


# ── check ────────────────────────────────────────────────────────────────────────────────────────────────────────────
def check(plan: dict[str, Any]) -> list[dict[str, str]]:
    """[{level: error|warn|info, code, text}] — any error means do not build"""
    out: list[dict[str, str]] = []
    add = lambda level, code, text: out.append({"level": level, "code": code, "text": text})  # noqa: E731
    tables = {t["table"]: {c["name"]: c for c in t["columns"]} for t in plan["tables"]}
    attrs = {a["name"]: a for a in plan["attributes"]}

    for kind, items in (("attribute", plan["attributes"]), ("metric", plan["metrics"] + plan["derived"] + plan["conditional"])):
        seen: dict[str, str] = {}
        for x in items:
            k = x["name"].casefold()
            if k in seen:
                add("error", "duplicate_name", f"Two {kind}s are named {x['name']}.")
            seen[k] = x["name"]
    if {a.casefold() for a in attrs} & {m["name"].casefold() for m in plan["metrics"] + plan["derived"]}:
        add("error", "duplicate_name", "An attribute and a metric share a name.")

    for a in plan["attributes"]:
        for f in a["forms"]:
            for e in f["expressions"]:
                if e["column"] not in tables.get(e["table"], {}):
                    add("error", "missing_column", f"{a['name']} reads {e['table']}.{e['column']}, which is not in the catalog.")
        if a["lookup"] not in _id_columns(a):
            add("error", "lookup_without_key", f"{a['name']}'s lookup table {a['lookup']} does not carry its ID.")
        for f in a["forms"][1:]:
            if any(e["table"] != a["lookup"] for e in f["expressions"]):
                add("warn", "form_off_lookup", f"{a['name']}'s {f['name']} form is read from a table other than its lookup table.")
        fams = {_family(tables.get(e["table"], {}).get(e["column"], {}).get("dataType")) for e in a["forms"][0]["expressions"]}
        if len(fams) > 1:
            add("error", "key_types_differ", f"{a['name']} joins columns of different kinds ({', '.join(sorted(fams))}); rows will not match across tables.")

    for r in plan["relationships"]:
        for end in ("parent", "child"):
            a = attrs.get(r[end])
            if not a:
                add("error", "relationship_unknown_attribute", f"Relationship {r['parent']} → {r['child']} names {r[end]}, which is not an attribute.")
            elif r["table"] not in _id_columns(a):
                add("error", "relationship_end_off_table", f"{r['parent']} → {r['child']} is set on {r['table']}, but {r[end]} is not on that table.")
    pairs = {}
    for r in plan["relationships"]:
        key = frozenset((r["parent"], r["child"]))
        if key in pairs and pairs[key] != (r["parent"], r["child"]):
            add("error", "relationship_both_ways", f"{r['parent']} and {r['child']} are related in both directions.")
        elif key in pairs:
            add("error", "relationship_twice", f"{r['parent']} → {r['child']} is set on more than one table; Strategy keeps one.")
        pairs[key] = (r["parent"], r["child"])
    cycle = _cycle(plan["relationships"])
    if cycle:
        add("error", "relationship_cycle", "Relationships form a loop: " + " → ".join(cycle) + ".")

    for mt in plan["metrics"]:
        col = tables.get(mt["table"], {}).get(mt["column"])
        if not col:
            add("error", "missing_column", f"Metric {mt['name']} reads {mt['table']}.{mt['column']}, which is not in the catalog.")
            continue
        fam = _family(col.get("dataType"))
        if mt["function"] not in FUNCS:
            add("error", "unknown_aggregation", f"Metric {mt['name']} uses {mt['function']}.")
        elif mt["function"] in ("sum", "avg", "median") and fam != "number":
            add("error", "aggregation_type", f"Metric {mt['name']} takes the {mt['function']} of {mt['column']}, which is {fam}, not a number.")
        if mt["function"] == "sum" and any(mt["table"] in _id_columns(a) and _id_columns(a)[mt["table"]] == mt["column"] for a in plan["attributes"]):
            add("error", "sum_of_key", f"Metric {mt['name']} sums {mt['column']}, which is an attribute's ID.")

    # every attribute must reach the facts: a metric on table M answers by attribute A when A, or an attribute A rolls
    # up to, is on M
    fact_tables = sorted({m["table"] for m in plan["metrics"]})
    reach = _reach(plan)
    for a in plan["attributes"]:
        tabs = reach[a["name"]]
        missing = [t for t in fact_tables if t not in tabs]
        if fact_tables and len(missing) == len(fact_tables):
            add("error", "attribute_reaches_no_metric", f"{a['name']} reaches no table with metrics; questions by {a['name']} cannot be answered.")
        elif missing:
            add("info", "attribute_partial_reach", f"{a['name']} does not reach {', '.join(missing)}.")
    for note in plan.get("notes", []):
        add("warn", "note", note)
    return out


def _cycle(rels: list[dict]) -> list[str] | None:
    graph: dict[str, set[str]] = {}
    for r in rels:
        graph.setdefault(r["parent"], set()).add(r["child"])
    state: dict[str, int] = {}
    path: list[str] = []

    def visit(n: str) -> list[str] | None:
        state[n] = 1
        path.append(n)
        for nxt in sorted(graph.get(n, ())):
            if state.get(nxt) == 1:
                return path[path.index(nxt):] + [nxt]
            if not state.get(nxt):
                found = visit(nxt)
                if found:
                    return found
        state[n] = 2
        path.pop()
        return None
    for n in sorted(graph):
        if not state.get(n):
            found = visit(n)
            if found:
                return found
    return None


def _reach(plan: dict) -> dict[str, set[str]]:
    """for each attribute, the tables it can be joined to: its own ID tables and those of every attribute below it"""
    children: dict[str, set[str]] = {}
    for r in plan["relationships"]:
        children.setdefault(r["parent"], set()).add(r["child"])
    on = {a["name"]: set(_id_columns(a)) for a in plan["attributes"]}
    out = {}
    for a in on:
        seen, stack, tabs = set(), [a], set()
        while stack:
            n = stack.pop()
            if n in seen:
                continue
            seen.add(n)
            tabs |= on.get(n, set())
            stack += list(children.get(n, ()))
        out[a] = tabs
    return out


def errors(findings: list[dict]) -> list[dict]:
    return [f for f in findings if f["level"] == "error"]
