#!/usr/bin/env python3
"""Finish the Campaign Promo ROI trio on the EReaderCo model (built in Studio 2026-09-02
without formats/descriptions and never republished).

PUTs the three metrics in place with the proven level-metric payload shapes
(tokens intermediates with attribute-only dimty pinned at Campaign Name; tree
divide final with dimty null), adding business descriptions and 2dp formats,
then republishes the in_memory cube so v2 cube instances can serve them.

One process / one session; identity=True (changeset commits require it).
"""
import os
import sys
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..",
                                "skills", "build-mosaic-model", "scripts"))
from build_mosaic import MSTR, open_cs, discard_cs, _mosaic_publish_verified  # noqa: E402

MID = "20B2F4E3B58A47C7825C2C7A8D0559E9"
CAMPAIGN = ("38EE99E5CBAB4A3D8CED0EA5EC5CEEE9", "Campaign Name")
TXN_AMT = ("F216908C7E1741B789DC1846CCEFFD59", "Transaction Amount")
DISC_AMT = ("96F4FBE344FE43B6A62FC995C2B6129B", "Discount Amount")
M_NUM = ("AEC88CEFA9DC4096AA623C0F3D30C1B9", "Transaction Amount @ Campaign")
M_DEN = ("C49B651E1B194AAC96A991B272C7A6D2", "Discount Amount @ Campaign")
M_ROI = ("812A87F3144E4E4DB733D4D460622422", "Campaign Promo ROI")

SUM_FN = "8107C31BDD9911D3B98100C04F2233EA"
CURRENCY = [{"type": "number_category", "value": "2"},
            {"type": "number_decimal_places", "value": "2"},
            {"type": "number_format", "value": "$#,##0.00;($#,##0.00)"}]
NUM2DP = [{"type": "number_category", "value": "1"},
          {"type": "number_decimal_places", "value": "2"},
          {"type": "number_format", "value": "#,##0.00"}]


def level_tokens(operand, level_attr):
    oid_, oname = operand
    lid, lname = level_attr
    return [
        {"type": "function", "value": "Sum", "target": {"objectId": SUM_FN, "subType": "function", "name": "Sum"}},
        {"type": "character", "value": "<"},
        {"type": "identifier", "value": "UseLookupForAttributes"},
        {"type": "function", "value": "="},
        {"type": "boolean", "value": "False"},
        {"type": "character", "value": ">"},
        {"type": "character", "value": "("},
        {"type": "object_reference", "value": f"[{oname}]",
         "target": {"objectId": oid_, "subType": "fact_metric", "name": oname}},
        {"type": "character", "value": ")"},
        {"type": "character", "value": "{"},
        {"type": "object_reference", "value": f"[{lname}]",
         "target": {"objectId": lid, "subType": "attribute", "name": lname}},
        {"type": "character", "value": "+"},
        {"type": "character", "value": "}"},
        {"type": "end_of_text", "value": ""},
    ]


def commit_or_raise(m, cs):
    r = m.post(f"/api/model/changesets/{cs}/commit")
    m.s.headers.pop("X-MSTR-MS-Changeset", None)
    if not r.ok:
        raise RuntimeError(f"commit {cs}: HTTP {r.status_code} body={r.text[:400]!r}")


def main():
    args = types.SimpleNamespace(
        base=os.environ["MSTR_BASE"], user=os.environ["MSTR_USER"],
        password=os.environ["MSTR_PASSWORD"], login_mode=1,
        project_id=os.environ["MSTR_PROJECT_ID"], verbose=False)
    m = MSTR(args)
    m.login(identity=True)
    try:
        cs = open_cs(m, release_self_locks=True)
        try:
            for (mid_, name), operand, side in (
                    (M_NUM, TXN_AMT, "Snowflake SALES"),
                    (M_DEN, DISC_AMT, "Neon PG PROMO")):
                body = {"information": {"name": name, "subType": "metric",
                                        "description": f"{operand[1]} aggregated at Campaign Name level only "
                                                       f"({side} side; level-pinned component of Campaign Promo ROI)."},
                        "expression": {"text": f"Sum({{{operand[1]}}})",
                                       "tokens": level_tokens(operand, CAMPAIGN)},
                        "dimty": {"dimtyUnits": [
                            {"dimtyUnitType": "attribute",
                             "target": {"objectId": CAMPAIGN[0], "subType": "attribute", "name": CAMPAIGN[1]},
                             "aggregation": "normal", "filtering": "apply", "groupBy": True}],
                            "excludeAttribute": False, "allowAddingUnit": True},
                        "format": {"header": [], "values": CURRENCY}}
                r = m.put(f"/api/model/dataModels/{MID}/metrics/{mid_}?showAdvancedProperties=true", json=body)
                if not r.ok:
                    raise RuntimeError(f"{name}: {r.status_code} {r.text[:300]}")
                print(f"  ~ {name}: description + $2dp format, pin re-asserted")

            body = {"information": {"name": M_ROI[1], "subType": "metric",
                                    "description": "Paid a-la-carte revenue generated per promotional discount dollar "
                                                   "(cross-store level metric: Snowflake sales over Neon PG discounts, "
                                                   "pinned at Campaign Name) - the campaign's ROI multiple on any report row."},
                    "expression": {"tree": {"type": "operator", "function": "divide", "children": [
                        {"type": "object_reference", "target": {"objectId": M_NUM[0], "subType": "metric", "name": M_NUM[1]}},
                        {"type": "object_reference", "target": {"objectId": M_DEN[0], "subType": "metric", "name": M_DEN[1]}}]}},
                    "dimty": None,
                    "format": {"header": [], "values": NUM2DP}}
            r = m.put(f"/api/model/dataModels/{MID}/metrics/{M_ROI[0]}?showAdvancedProperties=true", json=body)
            if not r.ok:
                raise RuntimeError(f"{M_ROI[1]}: {r.status_code} {r.text[:300]}")
            print(f"  ~ {M_ROI[1]}: description + 2dp format")
            commit_or_raise(m, cs)
            print("✓ committed (trio polished in place)")
        except Exception:
            discard_cs(m, cs)
            raise

        try:
            _mosaic_publish_verified(m, MID, poll_seconds=780, poll_interval=10.0)
            print("✓ publish confirmed complete in poll window")
        except SystemExit as e:
            print(f"  publish poll ended without confirmation ({e}); run validate_promo_roi.py to verify")
        return 0
    finally:
        m.logout()


if __name__ == "__main__":
    sys.exit(main())
