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
    spec = json.load(open(args.spec))
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
    host, user, pw, schema = svm._trino_host_from_base(m.base), os.environ["MSTR_USER"], os.environ["MSTR_PASSWORD"], name.lower()
    return lambda statement: svm._trino_query(host, user, pw, schema, statement)


def cmd_build(args) -> int:
    spec = json.load(open(args.spec))
    if args.name:
        spec["name"] = args.name
    summary: dict = {"ok": False, "model_id": None, "published": False, "proven": False,
                     "failures": {"tables": 0, "attributes": 0, "displays": 0, "metrics": 0, "relationships": 0, "post_build": 0}}
    try:
        m = live.sign_in_from_env()
    except SystemExit as e:
        say(f"FATAL: sign-in: {e}")
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
    while True:
        try:
            sql(f'SHOW COLUMNS FROM "{plan["name"]}"')
            break
        except (SystemExit, Exception) as e:  # noqa: BLE001 - the SQL surface lists a new model after a short delay
            if time.time() > deadline:
                say(f"PROOF FAILED: the model is not on the SQL surface after {SQL_SURFACE_WAIT}s ({str(e)[:160]})")
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
    summary.update(ok=True, proven=True)
    say(f"  ✓ proof: {passed} checks passed — every total matches its source and every breakdown adds up")
    print(json.dumps(summary))
    return 0


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
    args = ap.parse_args()
    return cmd_build(args) if args.cmd == "build" else cmd_plan(args)


if __name__ == "__main__":
    sys.exit(main())
