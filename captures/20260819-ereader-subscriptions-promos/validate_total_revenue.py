#!/usr/bin/env python3
"""Validate the Total Revenue demo metric on the EReaderCo model against source CSVs.

Checks (cube v2 instances = what Strategy dashboards serve):
  A. [Activity Date (Month)] x [Total Revenue] — all 20 months +-0.02
  B. grand total (metric alone) = 61,157.10
  C. [Customer Segment] x [Total Revenue] — additivity across a non-date dim:
     segment values must sum back to the grand total (no fan, no loss)
Exit 0 = all pass.
"""
import csv
import os
import re
import sys
import types
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..",
                                "skills", "build-mosaic-model", "scripts"))
from build_mosaic import MSTR  # noqa: E402

HERE = Path(__file__).parent
MID = "20B2F4E3B58A47C7825C2C7A8D0559E9"
MONTH = "A45A57E876B64283969072C5D2CC27CD"
SEGMENT = "22309B9EEBC844648DABFD7039104D94"
GRAND = 61157.10


def fetch_grid(m, metric_id, attrs):
    body = {"requestedObjects": {"attributes": [{"id": a} for a in attrs],
                                 "metrics": [{"id": metric_id}]}}
    r = m.s.post(f"{m.base}/api/v2/cubes/{MID}/instances?limit=30000", json=body, timeout=(10, 300))
    if not r.ok:
        raise RuntimeError(f"grid {attrs}: {r.status_code} {r.text[:250]}")
    j = r.json()
    mv = (j["data"].get("metricValues") or {}).get("raw", [])
    if not attrs:
        return {(): mv[0][0] if mv and mv[0] else None}
    rows_def = j["definition"]["grid"]["rows"]
    out = {}
    for ri, idxs in enumerate(j["data"]["headers"]["rows"]):
        el = rows_def[0]["elements"][idxs[0]]
        eid = el.get("id", "")
        mkey = re.match(r"^h(.*);[0-9A-F]{32}$", eid)
        key = mkey.group(1) if mkey else (el.get("formValues") or ["?"])[0]
        out[key] = mv[ri][0] if ri < len(mv) and mv[ri] else None
    return out


def main():
    sales = defaultdict(float)
    with open(HERE / "sales.csv") as f:
        for r in csv.DictReader(f):
            sales[r["DATE"][:7]] += float(r["AMOUNT"])
    mrr = defaultdict(float)
    with open(HERE / "subscription_months.csv") as f:
        rd = csv.DictReader(f)
        dcol = ([c for c in rd.fieldnames if "MONTH" in c and "START" in c]
                or [c for c in rd.fieldnames if "DATE" in c])[0]
        for r in rd:
            mrr[r[dcol][:7]] += float(r["MRR_AMOUNT"])
    expect = {mo: sales.get(mo, 0.0) + mrr.get(mo, 0.0) for mo in set(sales) | set(mrr)}

    args = types.SimpleNamespace(
        base=os.environ["MSTR_BASE"], user=os.environ["MSTR_USER"],
        password=os.environ["MSTR_PASSWORD"], login_mode=1,
        project_id=os.environ["MSTR_PROJECT_ID"], verbose=False)
    m = MSTR(args)
    m.login()
    failures = []
    try:
        mets = m.get(f"/api/model/dataModels/{MID}/metrics").json().get("metrics", [])
        tr = next((x["information"]["objectId"] for x in mets
                   if x["information"]["name"] == "Total Revenue"), None)
        if not tr:
            print("FAIL: Total Revenue metric not found on model")
            return 1
        print(f"Total Revenue metric id: {tr}")

        by_month = fetch_grid(m, tr, [MONTH])
        norm = {}
        for k, v in by_month.items():
            ks = str(k)
            # month smart keys by its bigint ID form, e.g. 202501
            mo = f"{ks[:4]}-{ks[4:6]}" if re.match(r"^\d{6}$", ks) else ks[:7]
            norm[mo] = v
        for mo in sorted(expect):
            got = norm.get(mo)
            ok = got is not None and abs(got - expect[mo]) < 0.02
            print(f"  {mo}  cube={got if got is None else f'{got:,.2f}'}  "
                  f"expected={expect[mo]:,.2f}  {'ok' if ok else 'MISMATCH'}")
            if not ok:
                failures.append(f"month {mo}: got {got} expected {expect[mo]:.2f}")

        total = fetch_grid(m, tr, [])[()]
        ok = total is not None and abs(total - GRAND) < 0.02
        print(f"  grand total: {total:,.2f} vs {GRAND:,.2f} {'ok' if ok else 'MISMATCH'}")
        if not ok:
            failures.append(f"grand total {total} != {GRAND}")

        by_seg = fetch_grid(m, tr, [SEGMENT])
        seg_sum = sum(v for v in by_seg.values() if v is not None)
        ok = abs(seg_sum - GRAND) < 0.05
        print(f"  segments {sorted(by_seg)} sum {seg_sum:,.2f} {'ok' if ok else 'MISMATCH (fan/loss!)'}")
        if not ok:
            failures.append(f"segment sum {seg_sum:.2f} != grand {GRAND}")
    finally:
        m.logout()

    if failures:
        print("\nFAILURES:")
        for f_ in failures:
            print(" -", f_)
        return 1
    print("\nALL VALIDATIONS PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
