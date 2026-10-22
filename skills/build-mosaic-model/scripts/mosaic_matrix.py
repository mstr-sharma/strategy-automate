"""The live matrix: build real models from many table sets and prove each one, as the release gate (../REBUILD.md).

  python3 mosaic_matrix.py run [--cases 6] [--seed N] [--specs DIR] [--keep]
  python3 mosaic_matrix.py gate [--max-age-days 7]        # exit 0 when the latest run passed on this commit

Cases come from saved designs (every *.json specification in --specs, default ignore/matrix-specs/, outside git
because real designs carry real names) and from the tenant itself: Snowflake datasets that share a prefix, other
Snowflake table families, Postgres schemas, and cross-store pairs (a Postgres schema with the Snowflake dataset whose
keys it shares). Generated cases draft their design from the columns (mosaic_plan.spec_from_tables).

Every case runs plan → check → apply → read back → publish → prove (totals against the source, two metrics per fact
table broken down by every attribute), then deletes its model. A case that fails anywhere after the check fails the
run; a generated design the check refuses is reported, not failed (it says what a person would have to decide).
The report goes to ignore/matrix/<time>.json and ignore/matrix/latest.json with the strategy-automate commit.
Credentials: MSTR_BASE, MSTR_USER, MSTR_PASSWORD, MSTR_PROJECT_ID; sources: MOSAIC_MATRIX_SOURCES (default below).
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import random
import re
import subprocess
import sys
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_mosaic as bm  # noqa: E402
import mosaic_apply as ma  # noqa: E402
import mosaic_build as mb  # noqa: E402
import mosaic_live as live  # noqa: E402
import mosaic_plan as mp  # noqa: E402

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
REPORTS = os.path.join(REPO, "ignore", "matrix")
SPECS = os.path.join(REPO, "ignore", "matrix-specs")
SYSTEM_SCHEMAS = {"information_schema", "pg_catalog", "public"}
MAX_ROWS = 3_000_000
SD = re.compile(r"^(SD_[A-Z]+_[A-Z0-9]+_\d{8}_\d{4})_", re.I)


def say(text: str) -> None:
    print(text, flush=True)


def commit() -> str:
    try:
        return subprocess.run(["git", "-C", REPO, "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=10).stdout.strip() or "unknown"
    except Exception:  # noqa: BLE001
        return "unknown"


# ── discovery ────────────────────────────────────────────────────────────────────────────────────────────────────────
def list_tables(m, ds_id: str, schema: str) -> list[str]:
    ns_id = bm.resolve_namespace_id(m, ds_id, schema)
    _, body = m.try_candidates("list_tables", id=ds_id, ns_id=ns_id)
    return [t.get("name") for t in (body.get("tables") or []) if isinstance(t, dict) and t.get("name")]


def list_schemas(m, ds_id: str) -> list[str]:
    _, body = m.try_candidates("list_namespaces", id=ds_id)
    rows = body.get("namespaces") if isinstance(body, dict) else body
    return [n.get("name") for n in rows or [] if isinstance(n, dict) and n.get("name")]


def groups_of(tables: list[str]) -> dict[str, list[str]]:
    """related tables: a synthetic dataset's prefix, else the first two words of the name"""
    out: dict[str, list[str]] = {}
    for t in tables:
        m = SD.match(t)
        key = m.group(1) if m else "_".join(t.split("_")[:2]) if t.count("_") >= 2 else None
        if key:
            out.setdefault(key, []).append(t)
    return {k: sorted(v) for k, v in out.items() if 2 <= len(v) <= 8}


def generated_cases(m, sources: list[tuple[str, str]], n: int, rng: random.Random) -> list[dict]:
    """sources: (datasource name or id, schema or '*'); returns case seeds {kind, refs:[{datasource,schema,table}]}"""
    snow, pg = [], []
    for ds, schema in sources:
        info = live.datasource(m, ds)
        schemas = [s for s in list_schemas(m, info["id"]) if s.lower() not in SYSTEM_SCHEMAS] if schema == "*" else [schema]
        for sc in schemas:
            try:
                tables = list_tables(m, info["id"], sc)
            except SystemExit:
                continue
            if "postgres" in info["dbms"].lower():
                if 2 <= len(tables) <= 6:
                    pg.append({"ds": info, "schema": sc, "tables": tables})
            else:
                for key, ts in groups_of(tables).items():
                    snow.append({"ds": info, "schema": sc, "key": key, "tables": ts, "sd": bool(SD.match(ts[0]))})
    ref = lambda d, sc, t: {"datasource": d["id"], "schema": sc, "table": t}  # noqa: E731
    cases = []
    kinds = ["cross", "snowflake_dataset", "postgres_schema", "snowflake_family"]
    for i in range(n):
        kind = kinds[i % len(kinds)]
        if kind == "cross" and pg:
            p = rng.choice(pg)
            token = re.split(r"[_\W]+", p["schema"])[0].upper()
            twins = [g for g in snow if g["sd"] and token and token in g["key"].upper()]
            if twins:
                g = rng.choice(twins)
                cases.append({"kind": "cross", "refs": [ref(g["ds"], g["schema"], t) for t in g["tables"]] + [ref(p["ds"], p["schema"], t) for t in p["tables"]]})
                continue
            kind = "postgres_schema"
        if kind == "postgres_schema" and pg:
            p = rng.choice(pg)
            cases.append({"kind": kind, "refs": [ref(p["ds"], p["schema"], t) for t in p["tables"]]})
            continue
        pool = [g for g in snow if g["sd"] == (kind == "snowflake_dataset")] or snow
        if pool:
            g = rng.choice(pool)
            cases.append({"kind": kind, "refs": [ref(g["ds"], g["schema"], t) for t in g["tables"]]})
    return cases


# ── one case ─────────────────────────────────────────────────────────────────────────────────────────────────────────
def run_case(m, case: dict, folder: str, sql, keep: bool) -> dict:
    out = {"kind": case["kind"], "name": case.get("name"), "tables": [r["table"] for r in case.get("refs", [])] or None, "outcome": None, "detail": ""}
    t0 = time.time()
    model_id = None
    try:
        if case.get("spec"):
            spec = case["spec"]
            out["tables"] = [s["table"] for s in spec["sources"]]
            plan, findings, prof = mb.plan_for(m, spec)
        else:
            cat = live.catalog(m, case["refs"])
            cols = {t["table"]: [c["name"] for c in t["columns"] if mp.KEY_COLUMN.search(c["name"])] for t in cat["tables"]}
            prof = live.profile(m, cat, cols)
            rows = sum(p.get("rows", 0) for p in prof.values())
            if rows > MAX_ROWS:
                out.update(outcome="skipped", detail=f"{rows:,} rows; over the matrix's {MAX_ROWS:,}-row budget")
                return out
            spec = mp.spec_from_tables(cat, prof, f"ZZ Matrix {case['kind']} {time.strftime('%H%M%S')}")
            plan = mp.from_spec(spec, cat, prof)
            findings = mp.check(plan)
        out["shape"] = {"attributes": len(plan["attributes"]), "metrics": len(plan["metrics"]), "relationships": len(plan["relationships"]),
                        "stores": sorted({t["dbms"] for t in plan["tables"]})}
        errors = mp.errors(findings)
        if errors:
            out.update(outcome="refused_by_check", detail="; ".join(e["text"] for e in errors[:3]))
            return out
        if not plan["metrics"]:
            out.update(outcome="skipped", detail="no numeric columns to measure")
            return out
        plan["name"] = spec["name"] if spec["name"].startswith("ZZ ") else f"ZZ Matrix {spec['name']}"[:200]
        res = ma.apply(m, plan, folder, log=lambda _: None)
        model_id = res["model_id"]
        diffs = ma.readback(m, plan, model_id)
        if diffs:
            out.update(outcome="failed", stage="read back", detail="; ".join(diffs[:3]))
            return out
        if plan["serve_mode"] == "in_memory":
            ma.publish(m, model_id, sum(p.get("rows", 0) for p in prof.values()))
        deadline = time.time() + mb.SQL_SURFACE_WAIT
        while True:
            try:
                sql(f'SHOW COLUMNS FROM "{plan["name"]}"')
                break
            except (SystemExit, Exception):  # noqa: BLE001
                if time.time() > deadline:
                    raise
                time.sleep(15)
        proof = ma.prove(m, plan, sql=sql, breakdowns_per_table=2)
        bad = [p for p in proof["probes"] if p["ok"] is False]
        out["proof"] = {"passed": sum(1 for p in proof["probes"] if p["ok"]), "failed": len(bad)}
        out.update(outcome="failed" if bad else "proven", stage="prove" if bad else None, detail="; ".join(f"{p['name']}: {p['detail']}" for p in bad[:3]))
        return out
    except ma.ApplyError as e:
        model_id = model_id or e.model_id
        out.update(outcome="failed", stage="apply" if not model_id else "publish", detail=str(e)[:400])
        return out
    except (SystemExit, Exception) as e:  # noqa: BLE001 - a case's failure is recorded, the run goes on
        out.update(outcome="failed", stage="unexpected", detail=f"{type(e).__name__}: {str(e)[:300]}", trace=traceback.format_exc()[-1200:])
        return out
    finally:
        out["seconds"] = int(time.time() - t0)
        if model_id and not keep:
            out["deleted"] = ma.delete_model(m, model_id)
        elif model_id:
            out["model_id"] = model_id


def cmd_run(args) -> int:
    m = live.sign_in_from_env()
    rng = random.Random(args.seed)
    sources = [tuple(s.rsplit(":", 1)) for s in (os.environ.get("MOSAIC_MATRIX_SOURCES") or "Synthetic Data:MCI_DEMO;Neon PostgreSQL:*").split(";") if ":" in s]
    cases = [{"kind": "saved_design", "name": os.path.basename(f), "spec": {**json.load(open(f)), "name": f"ZZ Matrix {time.strftime('%H%M%S')} {os.path.basename(f)[:-5]}"}}
             for f in sorted(glob.glob(os.path.join(args.specs, "*.json")))]
    say(f"→ {len(cases)} saved design{'s' if len(cases) != 1 else ''}; drawing {args.cases} generated cases (seed {args.seed})…")
    cases += generated_cases(m, sources, args.cases, rng)
    folder = [f for f in m.get("/api/folders/preDefined", params={"folderType": "20"}).json().get("preDefined", []) if f.get("folderType") == 20][0]["id"]
    sql = mb._sql(m)
    results = []
    for i, case in enumerate(cases, 1):
        say(f"→ case {i}/{len(cases)} [{case['kind']}] {case.get('name') or ', '.join(r['table'] for r in case['refs'][:4])}{'…' if len(case.get('refs', [])) > 4 else ''}")
        r = run_case(m, case, folder, sql, args.keep)
        results.append(r)
        say(f"  {r['outcome'].upper()}" + (f" at {r.get('stage')}" if r.get("stage") else "") + (f" · {r['proof']['passed']} checks" if r.get("proof") else "")
            + (f" · {r['detail'][:220]}" if r["detail"] else "") + f" · {r['seconds']}s")
    report = {"commit": commit(), "at": time.time(), "seed": args.seed, "ok": not any(r["outcome"] == "failed" for r in results),
              "counts": {k: sum(1 for r in results if r["outcome"] == k) for k in ("proven", "failed", "refused_by_check", "skipped")}, "cases": results}
    os.makedirs(REPORTS, exist_ok=True)
    path = os.path.join(REPORTS, time.strftime("%Y%m%d-%H%M%S") + ".json")
    for p in (path, os.path.join(REPORTS, "latest.json")):
        json.dump(report, open(p, "w"), indent=1)
    say(f"→ {'PASSED' if report['ok'] else 'FAILED'}: {report['counts']} · report {path}")
    return 0 if report["ok"] else 1


def cmd_gate(args) -> int:
    """the latest run passed, on this commit, recently enough"""
    try:
        report = json.load(open(os.path.join(REPORTS, "latest.json")))
    except (OSError, ValueError):
        say("no matrix run recorded; run: python3 mosaic_matrix.py run")
        return 1
    age = (time.time() - report.get("at", 0)) / 86400
    problems = [p for p, bad in (("it did not pass", not report.get("ok")), (f"it ran on {report.get('commit')}, not {commit()}", report.get("commit") != commit()),
                                 (f"it is {age:.1f} days old (limit {args.max_age_days})", age > args.max_age_days),
                                 ("it proved no model", not report.get("counts", {}).get("proven"))) if bad]
    say(("matrix gate: OK — " if not problems else "matrix gate: NOT MET — " + "; ".join(problems) + " — ") + f"{report.get('counts')} on {report.get('commit')}")
    return 1 if problems else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--cases", type=int, default=6)
    r.add_argument("--seed", type=int, default=int(time.time()) % 100000)
    r.add_argument("--specs", default=SPECS)
    r.add_argument("--keep", action="store_true", help="keep the models it builds")
    g = sub.add_parser("gate")
    g.add_argument("--max-age-days", type=float, default=7)
    args = ap.parse_args()
    return cmd_run(args) if args.cmd == "run" else cmd_gate(args)


if __name__ == "__main__":
    sys.exit(main())
