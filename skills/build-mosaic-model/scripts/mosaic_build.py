"""Build a Mosaic model from a specification: plan → check → apply → read back → publish → prove (see ../REBUILD.md).

  python3 mosaic_build.py build --spec spec.json --dest-folder FOLDER_ID [--name NAME]
  python3 mosaic_build.py plan  --spec spec.json            # the plan and its check, nothing written

The specification is the model as designed (Ace's draft shape: sources, attributes with forms and lookup tables,
metrics, relationships, excluded_relationships). Nothing is re-inferred from column names; only the relationships the
specification leaves implicit are added, from each table's key measured in the data. A plan the check refuses stops
before anything is created. Credentials: MSTR_BASE, MSTR_USER, MSTR_PASSWORD, MSTR_PROJECT_ID.

Progress goes to stdout line by line; the last line is a JSON summary. Exit 0 = built, published (in-memory) and proven;
1 = a model exists but something after creation failed; 2 = nothing was created (refused, or a check error).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mosaic_apply as ma  # noqa: E402
import mosaic_live as live  # noqa: E402
import mosaic_plan as mp  # noqa: E402

SQL_SURFACE_WAIT = 300


def say(text: str) -> None:
    print(text, flush=True)


def plan_for(m, spec: dict) -> tuple[dict, list[dict], dict]:
    refs = [{"datasource": s["instance_id"], "schema": s["schema"], "table": s["table"]} for s in spec["sources"]]
    say(f"→ Reading {len(refs)} source table{'s' if len(refs) != 1 else ''}…")
    cat = live.catalog(m, refs)
    for t in cat["tables"]:
        say(f"  {t['datasource']}/{t['schema']}.{t['table']}: {len(t['columns'])} cols")
    keys: dict[str, list[str]] = {}
    for a in spec["attributes"]:
        for f in a["forms"]:
            if f.get("category") == "ID":
                t = next((x for x in cat["tables"] if x["table"].casefold() == f["table"].casefold()), None)
                col = t and next((c["name"] for c in t["columns"] if c["name"].casefold() == f["column"].casefold()), None)
                if col:
                    keys.setdefault(t["table"], []).append(col)
    say("→ Measuring each table's keys in the data…")
    prof = live.profile(m, cat, keys)
    for t, p in prof.items():
        say(f"  {t}: {p['rows']:,} rows" if p.get("measured") else f"  {t}: not measurable here ({p.get('reason', '')[:120]})")
    plan = mp.from_spec(spec, cat, prof)
    findings = mp.check(plan)
    by = {}
    for r in plan["relationships"]:
        by[r.get("source", "key")] = by.get(r.get("source", "key"), 0) + 1
    say(f"→ Plan: {len(plan['attributes'])} attributes, {len(plan['metrics'])} metrics, {len(plan['relationships'])} relationships "
        f"({by.get('specification', 0)} from your design, {by.get('key', 0)} from each table's key)"
        + (f", {len(plan.get('excluded', []))} switched off" if plan.get("excluded") else ""))
    return plan, findings, prof


def cmd_plan(args) -> int:
    spec = live.load_json(args.spec, "spec")
    m = live.sign_in_from_env()
    plan, findings, _ = plan_for(m, spec)
    result = json.dumps({"plan": plan, "findings": findings}, default=str)
    if args.out:                                    # a plan is larger than a progress line: callers read it from a file
        with open(args.out, "w") as fh:
            fh.write(result)
        say(f"plan written: {args.out}")
    else:
        print(result)
    return 2 if mp.errors(findings) else 0


def _sql(m):
    import strategy_validate_models as svm
    # the SQL surface's schema is the project name, lowercased (GET /api/projects/{id} answers 500 on some tenants; the
    # list names every project the person can reach)
    name = os.environ.get("MSTR_PROJECT_NAME", "")
    if not name and m.project:
        r = m.get("/api/projects")
        rows = r.json() if r.ok else []
        rows = rows if isinstance(rows, list) else rows.get("projects", [])
        name = next((p.get("name", "") for p in rows if str(p.get("id", "")).upper() == m.project.upper()), "")
    if not name:
        raise RuntimeError("the project name for the SQL surface could not be read")
    # the signed-in person, however they signed in (environment or a credentials file)
    user = getattr(m, "user", None) or os.environ.get("MSTR_USER", "")
    pw = getattr(m, "pw", None) or os.environ.get("MSTR_PASSWORD", "")
    host, schema = svm._trino_host_from_base(m.base), name.lower()
    return lambda statement: svm._trino_query(host, user, pw, schema, statement)


def cmd_build(args) -> int:
    spec = live.load_json(args.spec, "spec")
    if args.name:
        spec["name"] = args.name
    summary: dict = {"ok": False, "model_id": None, "published": False, "proven": False,
                     "failures": {"tables": 0, "attributes": 0, "displays": 0, "metrics": 0, "relationships": 0, "post_build": 0}}
    try:
        m = live.sign_in_from_env()
    except SystemExit as e:
        say(f"FATAL: {e}" if str(e).startswith("sign-in") else f"FATAL: sign-in: {e}")
        print(json.dumps(summary))
        return 2
    plan, findings, prof = plan_for(m, spec)
    for f in findings:
        if f["level"] == "warn":
            say(f"  note: {f['text']}")
    errors = mp.errors(findings)
    if errors:
        say(f"FATAL: plan check: {errors[0]['text']}")
        for f in errors[1:]:
            say(f"  check: {f['text']}")
        summary["check"] = errors
        print(json.dumps(summary))
        return 2
    say(f"→ Creating model '{plan['name']}'…")
    try:
        res = ma.apply(m, plan, args.dest_folder or ma.bm.resolve_dest_folder(m, ""), log=say)
    except ma.ApplyError as e:
        summary["model_id"] = e.model_id
        if not e.model_id:
            say(f"FATAL: create model: {e}")
            print(json.dumps(summary))
            return 2
        say(f"FATAL: {e}")
        print(json.dumps(summary))
        return 1
    mid = summary["model_id"] = res["model_id"]
    say(f"[build] model {mid} committed")
    say("→ Reading the model back from Strategy…")
    diffs = ma.readback(m, plan, mid)
    for d in diffs:
        say(f"  WARN readback: {d}")
    if diffs:
        summary["failures"]["relationships" if any("relationship" in d for d in diffs) else "attributes"] = len(diffs)
        say(f"[build] finished with failures: {summary['failures']}")
        print(json.dumps(summary))
        return 1
    say("  ✓ Strategy holds exactly the plan")
    if plan["serve_mode"] == "in_memory":
        say("→ Publishing (loading the data into memory)…")
        t0 = time.time()
        try:
            ma.publish(m, mid, sum(p.get("rows", 0) for p in prof.values()))
        except ma.ApplyError as e:
            say(f"FATAL: _mosaic_publish_verified: timeout after {int(time.time() - t0)}s: {e}" if "within" in str(e) and "timeout" in str(e)
                else f"FATAL: publish: {e}")
            summary["failures"]["post_build"] = 1
            say(f"[build] finished with failures: {summary['failures']}")
            print(json.dumps(summary))
            return 1
        summary["published"] = True
        say(f"  ✓ published in {int(time.time() - t0)}s")
    say("→ Proving: asking the model real questions and comparing the answers with the sources…")
    sql = _sql(m)
    deadline = time.time() + SQL_SURFACE_WAIT
    republished = False
    while True:
        try:
            sql(f'SHOW COLUMNS FROM "{plan["name"]}"')
            break
        except (SystemExit, Exception) as e:  # noqa: BLE001 - the SQL surface lists a new model after a short delay
            # seen live: a name reused right after its model was deleted still points at the deleted model's id; publishing
            # again does not help, and waiting is the only cure
            stale = re.search(r"cube object by its ID: ([0-9A-F]{32})", str(e))
            stale = stale.group(1) if stale and stale.group(1) != mid else None
            if stale and time.time() > deadline:
                say(f"PROOF FAILED: Strategy's SQL endpoint still links the name '{plan['name']}' to a model deleted earlier ({stale}), so the "
                    f"new model is built and published but cannot be queried by that name yet. Rename the model, or check readiness again later.")
                summary["failures"]["post_build"] = 1
                print(json.dumps(summary))
                return 1
            if time.time() > deadline and plan["serve_mode"] == "in_memory" and not republished and not stale:
                # seen live: the SQL endpoint can miss one publish of a sound model; publishing again makes it list it
                republished = True
                say(f"  ↳ the SQL endpoint has not listed the model after {SQL_SURFACE_WAIT}s; publishing it again once…")
                try:
                    ma.publish(m, mid, sum(p.get("rows", 0) for p in prof.values()))
                    say("  ✓ published again")
                except ma.ApplyError as pe:
                    say(f"  ↳ publishing again did not finish: {str(pe)[:160]}")
                deadline = time.time() + SQL_SURFACE_WAIT
                continue
            if time.time() > deadline:
                say(f"PROOF FAILED: the model is not on the SQL surface after {SQL_SURFACE_WAIT}s{' and a second publish' if republished else ''} ({str(e)[:160]})")
                summary["failures"]["post_build"] = 1
                print(json.dumps(summary))
                return 1
            time.sleep(15)
    proof = ma.prove(m, plan, sql=sql, breakdowns_per_table=1)
    bad = [p for p in proof["probes"] if p["ok"] is False]
    for p in bad[:20]:
        say(f"PROOF FAILED: {p['name']} — {p['detail']}")
    passed = sum(1 for p in proof["probes"] if p["ok"])
    summary["proof"] = {"passed": passed, "failed": len(bad), "skipped": sum(1 for p in proof["probes"] if p["ok"] is None)}
    if bad:
        summary["failures"]["post_build"] = 1
        say(f"[build] finished with failures: {summary['failures']}")
        print(json.dumps(summary))
        return 1
    if not passed:
        # nothing could be compared with the sources: built and published, but not proven
        summary.update(ok=True, proven=False)
        say("  ! proof: no check could compare this model with its sources, so it is not marked proven")
        print(json.dumps(summary))
        return 0
    summary.update(ok=True, proven=True)
    say(f"  ✓ proof: {passed} checks passed — every total matches its source and every breakdown adds up")
    print(json.dumps(summary))
    return 0


def _audit_inputs(m, model_id: str):
    say("→ Reading the model from Strategy…")
    spec, rels, info = ma.spec_from_model(m, model_id)
    if info["unsupported"]:
        say(f"  note: {len(info['unsupported'])} query-built table(s) are not audited: {', '.join(info['unsupported'][:5])}")
    say(f"  {len(spec['sources'])} tables · {len(spec['attributes'])} attributes · {len(spec['metrics'])} metrics · {len(rels)} relationships")
    refs = [{"datasource": s["instance_id"], "schema": s["schema"], "table": s["table"]} for s in spec["sources"]]
    cat = live.catalog(m, refs)
    keys: dict[str, list[str]] = {}
    for a in spec["attributes"]:
        for f in a["forms"]:
            if f["category"] == "ID":
                keys.setdefault(f["table"], []).append(f["column"])
    say("→ Measuring each table's keys in the data…")
    prof = live.profile(m, cat, keys)
    return spec, rels, info, cat, prof


def cmd_audit(args) -> int:
    """the model as built against the plan: relationships to add or remove and what each fixes; nothing is written"""
    m = live.sign_in_from_env()
    spec, rels, info, cat, prof = _audit_inputs(m, args.model_id)
    result = ma.audit_model(spec, rels, cat, prof)
    say(f"→ {len(result['add'])} relationship(s) to add, {len(result['remove'])} to remove; fixes {len(result['fixed'])} finding(s), {len(result['remaining'])} remain")
    out = {"model_id": args.model_id, "name": info["name"], "serve_mode": info["serve_mode"], "unsupported": info["unsupported"],
           **{k: v for k, v in result.items() if k != "after"}, "relationships": rels}
    text = json.dumps(out, default=str)
    if args.out:
        with open(args.out, "w") as fh:
            fh.write(text)
        say(f"audit written: {args.out}")
    else:
        print(text)
    return 0


def cmd_fix(args) -> int:
    """apply reviewed relationship changes ({add: [...], remove: [...]}) to an existing model, read them back, republish
    (in-memory) and prove the model against its sources"""
    changes = live.load_json(args.changes, "changes")
    m = live.sign_in_from_env()
    spec, rels, info, cat, prof = _audit_inputs(m, args.model_id)
    summary = {"ok": False, "model_id": args.model_id, "added": 0, "removed": 0, "published": False, "proof": None}
    current = {(r["parent"], r["child"], r["table"]) for r in rels}
    add = [r for r in changes.get("add", []) if (r["parent"], r["child"], r["table"]) not in current]
    remove = [r for r in changes.get("remove", []) if (r["parent"], r["child"], r["table"]) in current]
    after = [r for r in rels if (r["parent"], r["child"], r["table"]) not in {(x["parent"], x["child"], x["table"]) for x in remove}] + \
        [{k: r[k] for k in ("parent", "child", "table", "type")} for r in add]
    plan_after = {**mp.from_spec(spec, cat, prof), "relationships": after}
    errs = mp.errors(mp.check(plan_after))
    if any(e["code"].startswith("relationship_") for e in errs):
        say(f"FATAL: plan check: {next(e['text'] for e in errs if e['code'].startswith('relationship_'))}")
        print(json.dumps(summary))
        return 2
    m.login(identity=True)
    attrs = {a["information"]["name"]: a["information"]["objectId"] for a in m.get(f"/api/model/dataModels/{args.model_id}/attributes").json().get("attributes", [])}
    tables = {}
    for row in m.get(f"/api/model/dataModels/{args.model_id}/tables").json().get("tables", []):
        tid = row["information"]["objectId"]
        t = m.get(f"/api/model/dataModels/{args.model_id}/tables/{tid}").json()
        pt = t.get("physicalTable") or {}
        pipe = json.loads(pt["pipeline"]) if isinstance(pt.get("pipeline"), str) else (pt.get("pipeline") or {})
        src = ((pipe.get("rootTable") or {}).get("children") or [{}])[0].get("importSource") or {}
        tables[src.get("tableName") or row["information"]["name"]] = tid
    say(f"→ Writing {len(add)} new and removing {len(remove)} relationship(s)…")
    cs = ma.bm.open_cs(m)
    try:
        by_child: dict[str, list[dict]] = {}
        for r in add:
            by_child.setdefault(r["child"], []).append({"parent": {"objectId": attrs[r["parent"]], "subType": "attribute"}, "child": {"objectId": attrs[r["child"]], "subType": "attribute"},
                                                         "relationshipType": r.get("type", "one_to_many"), "relationshipTable": {"objectId": tables[r["table"]], "subType": "logical_table"}})
        for child, new in by_child.items():
            ok, _, _, err = ma.bm.put_relationships_merged(m, args.model_id, attrs[child], new, cs)
            if not ok:
                raise ma.ApplyError(f"relationships into {child}: {err}", args.model_id)
            summary["added"] += len(new)
            say(f"  + {len(new)} into {child}")
        for r in remove:
            kept = [x for x in ma.bm.get_attribute_relationships(m, args.model_id, attrs[r["child"]]) or []
                    if not ((x.get("parent") or {}).get("objectId") == attrs[r["parent"]] and (x.get("child") or {}).get("objectId") == attrs[r["child"]]
                            and (x.get("relationshipTable") or {}).get("objectId") == tables[r["table"]])]
            ok, _, _, err = ma.bm.put_relationships_merged(m, args.model_id, attrs[r["child"]], kept, cs, replace=True)
            if not ok:
                raise ma.ApplyError(f"removing {r['parent']} → {r['child']}: {err}", args.model_id)
            summary["removed"] += 1
            say(f"  − {r['parent']} → {r['child']} on {r['table']}")
        ma.bm.commit_cs(m, cs)
        cs = None
    except (ma.ApplyError, KeyError) as e:
        if cs:
            ma.bm.discard_cs(m, cs)
        say(f"FATAL: {e}")
        print(json.dumps(summary))
        return 1
    _, now, _ = ma.spec_from_model(m, args.model_id)
    have = {(r["parent"], r["child"], r["table"]) for r in now}
    missing = [r for r in add if (r["parent"], r["child"], r["table"]) not in have] + [r for r in remove if (r["parent"], r["child"], r["table"]) in have]
    if missing:
        say(f"FATAL: read back: {len(missing)} change(s) not in Strategy")
        print(json.dumps(summary))
        return 1
    say("  ✓ Strategy holds exactly the reviewed relationships")
    if info["serve_mode"] == "in_memory":
        say("→ Republishing so the changes reach the loaded data…")
        try:
            ma.bm._publish(m, args.model_id, poll_seconds=1200, skip_classify=True)
            summary["published"] = True
        except SystemExit as e:
            say(f"FATAL: publish: {e}")
            print(json.dumps(summary))
            return 1
    say("→ Proving: asking the model real questions and comparing the answers with the sources…")
    plan_after["name"] = info["name"]
    proof = ma.prove(m, plan_after, sql=_sql(m), breakdowns_per_table=1)
    bad = [p for p in proof["probes"] if p["ok"] is False]
    for p in bad[:20]:
        say(f"PROOF FAILED: {p['name']} — {p['detail']}")
    summary["proof"] = {"passed": sum(1 for p in proof["probes"] if p["ok"]), "failed": len(bad)}
    summary["ok"] = not bad
    say(f"  ✓ proof: {summary['proof']['passed']} checks passed" if not bad else f"  {len(bad)} proof check(s) failed")
    print(json.dumps(summary))
    return 0 if not bad else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--spec", required=True)
    b.add_argument("--dest-folder", default="", help="destination folder id; default: your My Objects")
    b.add_argument("--name")
    p = sub.add_parser("plan")
    p.add_argument("--spec", required=True)
    p.add_argument("--out", help="write the plan and findings here instead of stdout")
    a = sub.add_parser("audit")
    a.add_argument("--model-id", required=True)
    a.add_argument("--out")
    f = sub.add_parser("fix")
    f.add_argument("--model-id", required=True)
    f.add_argument("--changes", required=True, help="JSON {add: [...], remove: [...]} from audit, as reviewed")
    args = ap.parse_args()
    return {"build": cmd_build, "plan": cmd_plan, "audit": cmd_audit, "fix": cmd_fix}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
