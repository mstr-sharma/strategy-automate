"""Apply, read back, publish and prove a checked plan (see ../REBUILD.md and mosaic_plan.py).

apply()    writes the plan through the Model REST API: the model, its tables, attributes with every form, fact metrics
           (one changeset), then relationships (a second changeset, each child written once with its whole set).
readback() reads the model from Strategy and lists every difference from the plan. "Built" means none.
publish()  loads an in-memory model and waits on Strategy's own status, with a deadline scaled to the rows.
prove()    asks the model real questions on its SQL surface and compares them with what each source says itself:
           metric totals against SUM(column) on the source table; a grouping on the metric's own table against the
           source's GROUP BY; a grouping reached through relationships must add up to the total (nothing lost or
           double counted) and must not repeat the total in every group (a cross join).
"""
from __future__ import annotations

import json
import re
import os
import sys
import time
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_mosaic as bm  # noqa: E402
import mosaic_live as live  # noqa: E402
import mosaic_plan as mp  # noqa: E402

DESC_FORM_ID = "CCFBE2A5EADB4F50941FB879CCF1721C"     # system DESC form, every tenant (REST samples; field study)
TOLERANCE = 1e-6


class ApplyError(RuntimeError):
    def __init__(self, message: str, model_id: str | None = None):
        super().__init__(message)
        self.model_id = model_id


def _tables_ref(tid: str, name: str) -> dict:
    return {"objectId": tid, "subType": "logical_table", "name": name}


def _expr(column: str, tid: str, tname: str) -> dict:
    return {"expression": {"tokens": [{"type": "column_reference", "value": column}]}, "tables": [_tables_ref(tid, tname)]}


def _table_body(t: dict) -> dict:
    import json
    outer, pipe = [], []
    for c in t["columns"]:
        dt = bm.sot.normalize_datatype(dict(c["dataType"]))
        outer.append({"information": {"name": c["name"]}, "dataType": dt, "columnName": c["name"]})
        pipe.append({"id": bm.new_uuid(), "name": c["name"], "dataType": dt, "sourceDataType": dt})
    pipeline = {"id": bm.new_uuid(), "rootTable": {"id": bm.new_uuid(), "type": "root", "children": [{
        "id": bm.new_uuid(), "name": t["table"], "type": "source", "columns": pipe,
        "importSource": {"type": "single_table", "dataSourceId": t["datasource_id"], "namespace": t["schema"], "tableName": t["table"], "sql": ""}}]}}
    return {"information": {"name": t["table"]}, "physicalTable": {"columns": outer, "type": "pipeline", "pipeline": json.dumps(pipeline)}}


def _attribute_body(a: dict, tid: dict[str, str]) -> dict:
    forms = []
    for i, f in enumerate(a["forms"]):
        exprs = [_expr(e["column"], tid[e["table"]], e["table"]) for e in f["expressions"]]
        lookup = a["lookup"] if f["category"] == "ID" else f["expressions"][0]["table"]
        form = {"category": f["category"] if f["category"] in ("ID", "DESC") else f["name"], "displayFormat": "text", "name": f["name"],
                "expressions": exprs, "lookupTable": _tables_ref(tid[lookup], lookup)}
        if f["category"] == "ID":
            form.update(id=bm.FORM_ID, type="system")
        elif f["category"] == "DESC" and not any(x["category"] == "DESC" for x in a["forms"][1:i]):
            form.update(id=DESC_FORM_ID, type="system")
        else:
            form.update(category=f["name"], type="custom")
        forms.append(form)
    return {"information": {"name": a["name"], "description": a.get("description") or a["name"]}, "forms": forms,
            "keyForm": {"id": bm.FORM_ID}, "attributeLookupTable": _tables_ref(tid[a["lookup"]], a["lookup"])}


def _metric_body(mt: dict, col: dict, tid: str) -> dict:
    dt = bm.sot.normalize_datatype(dict(col["dataType"]))
    fmt = bm._resolve_metric_format(mt["format"]) if mt.get("format") else bm._default_metric_format(mt["name"], dt, mt["function"])
    return {"information": {"name": mt["name"], "description": mt.get("description") or mt["name"]},
            "fact": {"dataType": dt, "expressions": [_expr(mt["column"], tid, mt["table"])], "extensions": [], "entryLevel": []},
            "function": mt["function"],
            "functionProperties": [{"name": "UseLookupForAttributes", "value": {"type": "boolean", "value": "false"}}],
            "dimty": {"dimtyUnits": [{"dimtyUnitType": "report_base_level", "aggregation": "normal", "filtering": "apply", "groupBy": True}],
                      "excludeAttribute": False, "allowAddingUnit": True},
            "format": {"header": [], "values": fmt}}


def _ok(r, what: str, model_id: str | None) -> dict:
    if not r.ok:
        raise ApplyError(f"{what}: {bm.format_mstr_error(r)}", model_id)
    return bm._json_or(r, {}) or {}


def apply(m: bm.MSTR, plan: dict, dest_folder_id: str, log=print) -> dict[str, Any]:
    """write a checked plan; raises ApplyError (with the model id once one exists) on the first refusal"""
    if mp.errors(mp.check(plan)):
        raise ApplyError("the plan has check errors; nothing was written")
    m.login(identity=True)
    cs = bm.open_cs(m)
    model_id = None
    try:
        body = _ok(m.post("/api/model/dataModels", json={"information": {"name": plan["name"], "destinationFolderId": dest_folder_id,
                                                                                   "description": plan.get("description", "")[:250]},
                                                             "dataServeMode": plan["serve_mode"]}), "create model", None)
        model_id = body["information"]["objectId"]
        log(f"  model_id={model_id}")
        tid: dict[str, str] = {}
        for t in plan["tables"]:
            tid[t["table"]] = _ok(m.post(f"/api/model/dataModels/{model_id}/tables", json=_table_body(t)), f"table {t['table']}", model_id)["information"]["objectId"]
            log(f"  + table {t['table']}")
        aid: dict[str, str] = {}
        for a in plan["attributes"]:
            resp = _ok(m.post(f"/api/model/dataModels/{model_id}/attributes", json=_attribute_body(a, tid)), f"attribute {a['name']}", model_id)
            aid[a["name"]] = resp["information"]["objectId"]
            forms = {f.get("category"): f.get("id") for f in resp.get("forms", [])}
            show = [forms["DESC"]] if forms.get("DESC") else [forms.get("ID") or bm.FORM_ID]     # names, not ids, on reports
            _ok(m.patch(f"/api/model/dataModels/{model_id}/attributes/{aid[a['name']]}",
                        json={"displays": {"reportDisplays": [{"id": f} for f in show], "browseDisplays": [{"id": f} for f in show]}}),
                f"displays of {a['name']}", model_id)
            log(f"  + attribute {a['name']} ({len(a['forms'])} form{'s' if len(a['forms']) > 1 else ''}, on {len(a['forms'][0]['expressions'])} table{'s' if len(a['forms'][0]['expressions']) > 1 else ''})")
        cols = {t["table"]: {c["name"]: c for c in t["columns"]} for t in plan["tables"]}
        for mt in plan["metrics"]:
            _ok(m.post(f"/api/model/dataModels/{model_id}/factMetrics", json=_metric_body(mt, cols[mt["table"]][mt["column"]], tid[mt["table"]])),
                f"metric {mt['name']}", model_id)
            log(f"  + metric {mt['name']} ({mt['function']})")
        bm.commit_cs(m, cs)
        cs = None
        if plan["relationships"]:
            cs = bm.open_cs(m)
            by_child: dict[str, list[dict]] = {}
            for r in plan["relationships"]:
                by_child.setdefault(r["child"], []).append({"parent": {"objectId": aid[r["parent"]], "subType": "attribute"},
                                                            "child": {"objectId": aid[r["child"]], "subType": "attribute"},
                                                            "relationshipType": r["type"], "relationshipTable": {"objectId": tid[r["table"]], "subType": "logical_table"}})
            for child, rels in by_child.items():
                ok, _, _, err = bm.put_relationships_merged(m, model_id, aid[child], rels, cs)
                if not ok:
                    raise ApplyError(f"relationships into {child}: {err}", model_id)
                log(f"  + {len(rels)} relationship{'s' if len(rels) > 1 else ''} into {child}")
            bm.commit_cs(m, cs)
            cs = None
        return {"model_id": model_id, "tables": tid, "attributes": aid}
    finally:
        if cs:
            try:
                bm.discard_cs(m, cs)
            except Exception:  # noqa: BLE001 - the error being raised matters more
                pass


# ── read back ────────────────────────────────────────────────────────────────────────────────────────────────────────
def readback(m: bm.MSTR, plan: dict, model_id: str) -> list[str]:
    """every difference between the model in Strategy and the plan (empty = Strategy holds exactly the plan)"""
    diffs: list[str] = []
    tables = {t["information"]["objectId"]: t["information"]["name"] for t in m.get(f"/api/model/dataModels/{model_id}/tables").json().get("tables", [])}
    if sorted(tables.values()) != sorted(t["table"] for t in plan["tables"]):
        diffs.append(f"tables: Strategy has {sorted(tables.values())}")
    have = {}
    for a in m.get(f"/api/model/dataModels/{model_id}/attributes").json().get("attributes", []):
        info = a["information"]
        full = m.get(f"/api/model/dataModels/{model_id}/attributes/{info['objectId']}", params={"showExpressionAs": "tokens"}).json()
        have[info["name"]] = (info["objectId"], full)
    names = {}
    for a in plan["attributes"]:
        if a["name"] not in have:
            diffs.append(f"attribute {a['name']} is missing")
            continue
        aid, full = have[a["name"]]
        names[aid] = a["name"]
        got_forms = full.get("forms", [])
        if len(got_forms) != len(a["forms"]):
            diffs.append(f"{a['name']}: {len(got_forms)} forms in Strategy, {len(a['forms'])} planned")
        want = {(e["table"], e["column"]) for e in a["forms"][0]["expressions"]}
        idf = next((f for f in got_forms if f.get("id") == bm.FORM_ID or f.get("category") == "ID"), {})
        got = set()
        for e in idf.get("expressions", []):
            col = next((t.get("value") for t in (e.get("expression") or {}).get("tokens", []) if t.get("type") == "column_reference"), None)
            for t in e.get("tables", []):
                got.add((tables.get(t.get("objectId"), t.get("name")), col))
        if got != want:
            diffs.append(f"{a['name']}: ID form on {sorted(got)} in Strategy, {sorted(want)} planned")
    extra = set(have) - {a["name"] for a in plan["attributes"]}
    if extra:
        diffs.append(f"attributes not in the plan: {sorted(extra)}")
    rels = set()
    for aid, name in names.items():
        for r in bm.get_attribute_relationships(m, model_id, aid) or []:
            p, c = names.get((r.get("parent") or {}).get("objectId")), names.get((r.get("child") or {}).get("objectId"))
            t = tables.get((r.get("relationshipTable") or {}).get("objectId"))
            if p and c:
                rels.add((p, c, t))
    want_rels = {(r["parent"], r["child"], r["table"]) for r in plan["relationships"]}
    for r in sorted(want_rels - rels):
        diffs.append(f"relationship {r[0]} → {r[1]} on {r[2]} is missing")
    for r in sorted(rels - want_rels):
        diffs.append(f"relationship {r[0]} → {r[1]} on {r[2]} is not in the plan")
    mets = {x["information"]["name"] for x in m.get(f"/api/model/dataModels/{model_id}/factMetrics").json().get("factMetrics", [])}
    for mt in plan["metrics"]:
        if mt["name"] not in mets:
            diffs.append(f"metric {mt['name']} is missing")
    return diffs


# ── publish ──────────────────────────────────────────────────────────────────────────────────────────────────────────
def publish(m: bm.MSTR, model_id: str, rows: int) -> None:
    """in-memory models only. Strategy's own status decides; the ceiling is long (20 minutes, plus a minute per million
    rows, up to an hour) because a warehouse waking up takes minutes even for a few thousand rows."""
    wait = int(min(3600, 1200 + rows / 1_000_000 * 60))
    try:
        bm._publish(m, model_id, poll_seconds=wait, skip_classify=True)
    except SystemExit as e:
        # the reason as Strategy gave it: a timeout says so itself; a refused request is not a timeout
        why = str(e)
        raise ApplyError(why if re.search(r"(?i)timed? ?out|did not (finish|complete)|within \d+", why) else f"publish failed: {why}", model_id) from None


# ── prove ────────────────────────────────────────────────────────────────────────────────────────────────────────────
def _num(v) -> float | None:
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def sql_columns(model_rows: list[dict]) -> dict[str, str]:
    """the model's SQL columns by lowercase name (from SHOW COLUMNS)"""
    return {str(r.get("Column") or r.get("column") or "").lower(): str(r.get("Column") or r.get("column")) for r in model_rows}


def prove(m: bm.MSTR, plan: dict, *, sql, source_sql=live.run_sql, attempts: int = 1, breakdowns_per_table: int | None = None) -> dict[str, Any]:
    """sql(statement) -> rows: the model's SQL surface (Trino). Returns {ok, probes: [{name, ok, detail}]}. A dropped
    connection is retried; anything else a query raises is that probe's failure, never the end of the proof."""
    raw_sql = sql

    def sql(statement: str) -> list[dict]:
        import requests
        for attempt in range(3):
            try:
                return raw_sql(statement)
            except requests.ConnectionError:
                if attempt == 2:
                    raise
                time.sleep(5 * (attempt + 1))
        return []
    q = lambda s: '"' + s.replace('"', '""') + '"'  # noqa: E731
    model = q(plan["name"])
    cols = sql_columns(sql(f"SHOW COLUMNS FROM {model}"))
    tables = {t["table"]: t for t in plan["tables"]}
    probes = []

    def attr_col(a: dict) -> str | None:
        """the SQL column of the attribute's ID form"""
        base = a["name"].lower()
        hits = [c for k, c in cols.items() if k == base or k.startswith(base + " (") and k.endswith(" id)")]
        return hits[0] if hits else next((c for k, c in cols.items() if k.startswith(base + " (")), None)

    reach = mp._reach(plan)
    broken_down: dict[str, int] = {}                    # fact table -> metrics already broken down by every attribute
    # sums and counts must add up across every breakdown; averages, minimums and maximums are compared with the source as
    # a total and, where the attribute sits on the metric's own table, group by group
    for mt in [x for x in plan["metrics"] if x["function"] in ("sum", "count", "avg", "min", "max")]:
        additive = mt["function"] in ("sum", "count")
        mcol = cols.get(mt["name"].lower())
        if not mcol:
            probes.append({"name": f"{mt['name']} is on the SQL surface", "ok": False, "detail": "no column"})
            continue
        agg = "SUM" if mt["function"] in ("sum", "count") else mt["function"].upper()
        t = tables[mt["table"]]
        try:
            total_model = _num(sql(f"SELECT {agg}({q(mcol)}) AS v FROM {model}")[0]["v"])  # nosec B608  # identifiers are quoted; aggregate names come from the fixed allowed set
        except (SystemExit, Exception) as e:  # noqa: BLE001
            probes.append({"name": f"{mt['name']} total", "ok": False, "detail": str(e)[:300]})
            continue
        try:
            src_fn = {"sum": "SUM", "count": "COUNT", "avg": "AVG", "min": "MIN", "max": "MAX"}[mt["function"]]
            # "* 1.0" keeps an average of whole numbers from being rounded by stores that average integers as integers
            src_arg = live.quote(t["dbms"], mt["column"]) + (" * 1.0" if src_fn == "AVG" else "")
            src = source_sql(m, t["datasource_id"], f"SELECT {src_fn}({src_arg}) AS v FROM {live.table_ref(t)}")  # nosec B608  # identifiers are quoted; aggregate names come from the fixed allowed set
            total_src = _num(src[0]["v"])
        except RuntimeError as e:
            total_src = None
            probes.append({"name": f"{mt['name']} total (source)", "ok": None, "detail": f"source not measurable: {e}"})
        if total_src is not None:
            same = total_model is not None and abs(total_model - total_src) <= (TOLERANCE if additive else 1e-6) * max(1.0, abs(total_src))
            probes.append({"name": f"{mt['name']} total", "ok": same, "detail": f"model {total_model} · source {total_src}"})
        if breakdowns_per_table is not None and broken_down.get(mt["table"], 0) >= breakdowns_per_table:
            continue                                    # its total is proven; the breakdowns were proven on another metric
        broken_down[mt["table"]] = broken_down.get(mt["table"], 0) + 1
        for a in plan["attributes"]:
            if mt["table"] not in reach[a["name"]]:
                continue
            acol = attr_col(a)
            if not acol:
                probes.append({"name": f"{a['name']} is on the SQL surface", "ok": False, "detail": "no column"})
                continue
            try:
                rows = sql(f"SELECT {q(acol)} AS k, {agg}({q(mcol)}) AS v FROM {model} GROUP BY 1")  # nosec B608  # identifiers are quoted; aggregate names come from the fixed allowed set
            except (SystemExit, Exception) as e:  # noqa: BLE001 - recorded as this probe's failure
                probes.append({"name": f"{mt['name']} by {a['name']}", "ok": False, "detail": str(e)[:300]})
                continue
            vals = [_num(r["v"]) or 0.0 for r in rows]
            s = sum(vals)
            name = f"{mt['name']} by {a['name']}"
            if total_model is None:
                probes.append({"name": name, "ok": False, "detail": "no total to compare"})
                continue
            on_table = mt["table"] in {e["table"] for e in a["forms"][0]["expressions"]}
            if not additive and not on_table:
                continue                                # nothing to add up, and no source grouping to compare with
            adds_up = abs(s - total_model) <= TOLERANCE * max(1.0, abs(total_model))
            cross = additive and len(vals) > 1 and all(abs(v - total_model) <= TOLERANCE * max(1.0, abs(total_model)) for v in vals)
            detail = f"{len(rows)} groups, sum {s} vs total {total_model}" if additive else f"{len(rows)} groups"
            ok = (adds_up or not additive) and not cross
            if ok and on_table:
                col = next(e["column"] for e in a["forms"][0]["expressions"] if e["table"] == mt["table"])
                try:
                    # a one-row fingerprint of the source's grouping (how many groups, and the sum of each group's total
                    # squared): the source SQL call returns at most 1,000 rows, so the groups themselves are not fetched
                    qc, qv = live.quote(t["dbms"], col), live.quote(t["dbms"], mt["column"]) + (" * 1.0" if src_fn == "AVG" else "")
                    fp = source_sql(m, t["datasource_id"], f"SELECT COUNT(*) AS g, SUM(s * s) AS sq FROM (SELECT {qc} AS k, {src_fn}({qv}) AS s "  # nosec B608  # identifiers are quoted; aggregate names come from the fixed allowed set
                                                         f"FROM {live.table_ref(t)} GROUP BY {qc}) x")[0]
                    want_g, want_sq = int(float(fp["g"])), _num(fp["sq"]) or 0.0
                    got_sq = sum(v * v for v in vals)
                    ok = want_g == len(vals) and abs(got_sq - want_sq) <= 1e-6 * max(1.0, abs(want_sq))
                    detail += f"; source groups {'match' if ok else f'differ ({want_g} groups, sum of squares {want_sq} vs {got_sq})'}"
                except RuntimeError as e:
                    detail += f"; source grouping not measurable ({str(e)[:120]})"
            elif cross:
                detail += "; every group equals the total (cross join)"
            probes.append({"name": name, "ok": ok, "detail": detail})
    return {"ok": all(p["ok"] is not False for p in probes) and any(p["ok"] for p in probes), "probes": probes}


def delete_model(m: bm.MSTR, model_id: str, attempts: int = 3) -> bool:
    """True only once Strategy no longer has the model: a delete can be refused while the model is busy (just published,
    being read), so it is retried and confirmed by reading the object back"""
    import time as _t
    for i in range(attempts):
        m.s.delete(f"{m.base}/api/objects/{model_id}", params={"type": 3})
        if m.s.get(f"{m.base}/api/objects/{model_id}", params={"type": 3}).status_code == 404:
            return True
        _t.sleep(10 * (i + 1))
    return False


# ── an existing model, read back into a specification and its relationships (the audit's starting point) ────────────
def spec_from_model(m: bm.MSTR, model_id: str) -> tuple[dict, list[dict], dict]:
    """(specification as designed, relationships as they are in Strategy, model info). Query-built tables are listed in
    info['unsupported'] and left out: the audit covers tables read straight from a source."""
    info = m.get(f"/api/model/dataModels/{model_id}").json()
    names, sources, unsupported = {}, [], []
    cache: dict[str, dict] = {}
    for row in m.get(f"/api/model/dataModels/{model_id}/tables").json().get("tables", []):
        tid = row["information"]["objectId"]
        t = m.get(f"/api/model/dataModels/{model_id}/tables/{tid}").json()
        pt = t.get("physicalTable") or {}
        pipe = json.loads(pt["pipeline"]) if isinstance(pt.get("pipeline"), str) else (pt.get("pipeline") or {})
        src = ((pipe.get("rootTable") or {}).get("children") or [{}])[0].get("importSource") or {}
        name = row["information"]["name"]
        names[tid] = name
        if src.get("type") != "single_table":
            unsupported.append(name)
            continue
        ds = live.datasource(m, src["dataSourceId"], cache)
        sources.append({"instance_id": ds["id"], "instance": ds["name"], "schema": src["namespace"], "table": src["tableName"], "_logical": name})
    logical_to_physical = {s["_logical"]: s["table"] for s in sources}
    attributes = []
    for a in m.get(f"/api/model/dataModels/{model_id}/attributes").json().get("attributes", []):
        aid = a["information"]["objectId"]
        full = m.get(f"/api/model/dataModels/{model_id}/attributes/{aid}", params={"showExpressionAs": "tokens"}).json()
        forms = []
        for f in full.get("forms", []):
            cat = "ID" if f.get("id") == bm.FORM_ID or f.get("category") == "ID" else "DESC"
            for e in f.get("expressions", []):
                col = next((tk.get("value") for tk in (e.get("expression") or {}).get("tokens", []) if tk.get("type") == "column_reference"), None)
                for tb in e.get("tables", []):
                    tname = logical_to_physical.get(names.get(tb.get("objectId"), tb.get("name")))
                    if col and tname:
                        forms.append({"name": f.get("name") or cat, "category": cat, "table": tname, "column": col})
        lookup = logical_to_physical.get(names.get((full.get("attributeLookupTable") or {}).get("objectId"), ""))
        if any(f["category"] == "ID" for f in forms):
            attributes.append({"name": a["information"]["name"], "description": (full.get("information") or {}).get("description", ""),
                               "lookup_table": lookup, "forms": sorted(forms, key=lambda f: f["category"] != "ID"), "_id": aid})
    metrics = []
    for mt in m.get(f"/api/model/dataModels/{model_id}/factMetrics", params={"showExpressionAs": "tokens"}).json().get("factMetrics", []):
        exprs = (mt.get("fact") or {}).get("expressions") or []
        if not exprs:
            continue
        col = next((tk.get("value") for tk in (exprs[0].get("expression") or {}).get("tokens", []) if tk.get("type") == "column_reference"), None)
        tname = logical_to_physical.get(names.get(((exprs[0].get("tables") or [{}])[0]).get("objectId"), ""))
        if col and tname:
            metrics.append({"name": mt["information"]["name"], "table": tname, "column": col, "function": (mt.get("function") or "sum").lower(), "format": "fixed2"})
    by_id = {a["_id"]: a["name"] for a in attributes}
    rels, seen = [], set()
    for a in attributes:
        for r in bm.get_attribute_relationships(m, model_id, a["_id"]) or []:
            p, c = by_id.get((r.get("parent") or {}).get("objectId")), by_id.get((r.get("child") or {}).get("objectId"))
            t = logical_to_physical.get(names.get((r.get("relationshipTable") or {}).get("objectId"), ""))
            if p and c and t and (p, c, t) not in seen:
                seen.add((p, c, t))
                rels.append({"parent": p, "child": c, "table": t, "type": r.get("relationshipType") or "one_to_many", "source": "model"})
    spec = {"name": (info.get("information") or {}).get("name", model_id), "serve_mode": info.get("dataServeMode") or "in_memory",
            "sources": [{k: v for k, v in s.items() if k != "_logical"} for s in sources],
            "attributes": [{k: v for k, v in a.items() if k != "_id"} for a in attributes], "metrics": metrics,
            "derived": [], "conditional": [], "relationships": []}
    return spec, rels, {"unsupported": unsupported, "serve_mode": spec["serve_mode"], "name": spec["name"]}


def audit_model(spec: dict, current_rels: list[dict], cat: dict, prof: dict) -> dict:
    """the model as built against what the plan would build: relationships to add (keys found in the data, the missing
    ones), relationships to remove (loops, both-way pairs, ends off their table), what each change fixes, and the
    remaining findings. Pure."""
    import mosaic_plan as mp
    suggested = mp.from_spec(spec, cat, prof)
    current = {**suggested, "relationships": [dict(r) for r in current_rels]}
    have = {(r["parent"], r["child"]) for r in current_rels}
    findings_now = mp.check(current)
    remove = []
    for f in findings_now:
        if f["code"] in ("relationship_both_ways", "relationship_cycle", "relationship_end_off_table", "relationship_twice"):
            for r in current_rels:
                if r["parent"] in f["text"] and r["child"] in f["text"] and not any((r["parent"], r["child"]) == (s["parent"], s["child"]) and r["table"] == s["table"] for s in suggested["relationships"]):
                    if r not in remove:
                        remove.append({**r, "why": f["text"]})
    add = [{**r, "why": f"{r['child']} is the key of {r['table']}" + (f" (unique in {prof[r['table']]['rows']:,} rows)" if (prof.get(r['table']) or {}).get('measured') else "")}
           for r in suggested["relationships"] if (r["parent"], r["child"]) not in have and (r["child"], r["parent"]) not in have]
    after = {**suggested, "relationships": [r for r in current_rels if r not in [{k: v for k, v in x.items() if k != "why"} for x in remove]] + [{k: v for k, v in r.items() if k != "why"} for r in add]}
    findings_after = mp.check(after)
    now_codes = {(f["code"], f["text"]) for f in findings_now if f["level"] == "error"}
    after_codes = {(f["code"], f["text"]) for f in findings_after if f["level"] == "error"}
    return {"add": add, "remove": remove, "fixed": [t for c, t in sorted(now_codes - after_codes)], "remaining": [t for c, t in sorted(after_codes)],
            "findings": findings_now, "keys": suggested.get("keys", {}), "after": after}
