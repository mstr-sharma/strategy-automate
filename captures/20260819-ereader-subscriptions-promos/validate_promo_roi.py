#!/usr/bin/env python3
"""Validate the Campaign Promo ROI level-metric trio on the EReaderCo model
(20B2F4E3B58A47C7825C2C7A8D0559E9) against the deterministic source CSVs.

Trio (built in Studio, verified 2026-09-02):
  Transaction Amount @ Campaign  AEC88CEFA9DC4096AA623C0F3D30C1B9
      = Sum([Transaction Amount]) {[Campaign Name]+}      (Snowflake SALES side)
  Discount Amount @ Campaign     C49B651E1B194AAC96A991B272C7A6D2
      = Sum([Discount Amount]) {[Campaign Name]+}          (Neon PG PROMO side)
  Campaign Promo ROI             812A87F3144E4E4DB733D4D460622422
      = [Transaction Amount @ Campaign] / [Discount Amount @ Campaign]

Expectations, fully cube-independent:
  promo_redemptions.csv gives campaign -> {transaction ids, discount sum};
  sales.csv gives transaction -> paid amount. Expected ROI = paid/discount.
Checks:
  A. source sanity: sales total 43,105.11 / discounts 4,390.70 / 1,239 redemptions
  B. per-campaign num, den, roi vs cube grid [Campaign Name] x trio (+-0.02)
  C. pin proof: [Campaign Name, Activity Date (Month)] x ROI is CONSTANT
     within each campaign (level pin ignores the finer month grain)
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
CAMPAIGN = "38EE99E5CBAB4A3D8CED0EA5EC5CEEE9"
MONTH = "A45A57E876B64283969072C5D2CC27CD"
M_NUM = "AEC88CEFA9DC4096AA623C0F3D30C1B9"
M_DEN = "C49B651E1B194AAC96A991B272C7A6D2"
M_ROI = "812A87F3144E4E4DB733D4D460622422"


def fetch_grid(m, attrs, metrics):
    body = {"requestedObjects": {"attributes": [{"id": a} for a in attrs],
                                 "metrics": [{"id": x} for x in metrics]}}
    r = m.s.post(f"{m.base}/api/v2/cubes/{MID}/instances?limit=30000", json=body, timeout=(10, 300))
    if not r.ok:
        raise RuntimeError(f"grid: {r.status_code} {r.text[:300]}")
    j = r.json()
    rows_def = j["definition"]["grid"]["rows"]
    hdr = j["data"]["headers"]["rows"]
    mv = (j["data"].get("metricValues") or {}).get("raw", [])
    out = []
    for ri, idxs in enumerate(hdr):
        cells = []
        for ai, ei in enumerate(idxs):
            el = rows_def[ai]["elements"][ei]
            eid = el.get("id", "")
            mkey = re.match(r"^h(.*);[0-9A-F]{32}$", eid)
            cells.append(mkey.group(1) if mkey else (el.get("formValues") or ["?"])[0])
        out.append((cells, mv[ri] if ri < len(mv) else []))
    return out


def main():
    # ── expectations from source CSVs ────────────────────────────────────────
    amounts = {}
    with open(HERE / "sales.csv") as f:
        for row in csv.DictReader(f):
            amounts[row["TRANSACTION_ID"]] = float(row["AMOUNT"])
    disc = defaultdict(float)
    txns = defaultdict(set)
    n_red = 0
    with open(HERE / "promo_redemptions.csv") as f:
        for row in csv.DictReader(f):
            n_red += 1
            disc[row["CAMPAIGN_NAME"]] += float(row["DISCOUNT_AMOUNT"])
            txns[row["CAMPAIGN_NAME"]].add(row["TRANSACTION_ID"])
    sales_total = sum(amounts.values())
    disc_total = sum(disc.values())
    print(f"source sanity: sales {sales_total:,.2f} / discounts {disc_total:,.2f} / {n_red} redemptions")
    ok = (abs(sales_total - 43105.11) < 0.02 and abs(disc_total - 4390.70) < 0.02 and n_red == 1239)
    if not ok:
        print("FAIL: source CSVs do not match the verified totals")
        return 1
    expect = {}
    for c in disc:
        num = sum(amounts[t] for t in txns[c] if t in amounts)
        expect[c] = (num, disc[c], num / disc[c])

    args = types.SimpleNamespace(
        base=os.environ["MSTR_BASE"], user=os.environ["MSTR_USER"],
        password=os.environ["MSTR_PASSWORD"], login_mode=1,
        project_id=os.environ["MSTR_PROJECT_ID"], verbose=False)
    m = MSTR(args)
    m.login()
    failures = []
    try:
        # ── B: per-campaign values ───────────────────────────────────────────
        grid = fetch_grid(m, [CAMPAIGN], [M_NUM, M_DEN, M_ROI])
        seen = set()
        print(f"\n{'campaign':<28} {'paid$':>10} {'disc$':>9} {'ROI':>7}   expected")
        for (cells, vals) in grid:
            c = cells[0]
            if c not in expect:
                failures.append(f"unexpected campaign row {c!r}")
                continue
            seen.add(c)
            en, ed, er = expect[c]
            an, ad, ar = (vals + [None] * 3)[:3]
            row_ok = (an is not None and abs(an - en) < 0.02
                      and abs(ad - ed) < 0.02 and abs(ar - er) < 0.005)
            print(f"{c:<28} {an:>10,.2f} {ad:>9,.2f} {ar:>7.2f}   "
                  f"{en:,.2f}/{ed:,.2f}={er:.2f} {'ok' if row_ok else 'MISMATCH'}")
            if not row_ok:
                failures.append(f"{c}: got ({an},{ad},{ar}) expected ({en:.2f},{ed:.2f},{er:.2f})")
        missing = set(expect) - seen
        if missing:
            failures.append(f"campaigns missing from grid: {sorted(missing)}")

        # ── C: pin constancy across months ───────────────────────────────────
        grid2 = fetch_grid(m, [CAMPAIGN, MONTH], [M_ROI])
        per_c = defaultdict(set)
        for (cells, vals) in grid2:
            if vals and vals[0] is not None:
                per_c[cells[0]].add(round(vals[0], 4))
        bad = {c: v for c, v in per_c.items() if len(v) > 1}
        if bad:
            failures.append(f"ROI varies within campaign across months (pin broken): {bad}")
        else:
            print(f"\npin proof: ROI constant across months within every campaign "
                  f"({len(per_c)} campaigns x months grid, {len(grid2)} rows)")
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
