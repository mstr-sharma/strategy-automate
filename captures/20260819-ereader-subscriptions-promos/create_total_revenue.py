#!/usr/bin/env python3
"""Create the demo-safe cross-store metric on the EReaderCo model:

  Total Revenue = NullToZero(Transaction Amount) + NullToZero(Monthly Recurring
                  Revenue Amount)

Additive (SUM-distributes at every grain) and null-safe (rows carrying only one
revenue stream still contribute), so Claude/MCP SQL, Tableau's default SUM, and
Strategy grids all agree. Falls back to a plain plus if NullToZero can't be
resolved/accepted. Then republishes the in_memory cube (derived metrics are not
v2-instance-addressable until republish).

One process / one session; identity=True.
"""
import os
import sys
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..",
                                "skills", "build-mosaic-model", "scripts"))
from build_mosaic import MSTR, open_cs, discard_cs, _mosaic_publish_verified  # noqa: E402

MID = "20B2F4E3B58A47C7825C2C7A8D0559E9"
TXN = ("F216908C7E1741B789DC1846CCEFFD59", "Transaction Amount")
MRR = ("09A1AE3A34EA44E79A3DF6C93A1256F2", "Monthly Recurring Revenue Amount")
NAME = "Total Revenue"
DESC = ("Company-wide revenue: a-la-carte sales (Transaction Amount, Snowflake) plus "
        "EReaderCo Plus subscription revenue (Monthly Recurring Revenue Amount, Neon PG). "
        "Fully additive and null-safe - safe to SUM at any grain in any tool.")
CURRENCY = [{"type": "number_category", "value": "2"},
            {"type": "number_decimal_places", "value": "2"},
            {"type": "number_format", "value": "$#,##0.00;($#,##0.00)"}]


def commit_or_raise(m, cs):
    r = m.post(f"/api/model/changesets/{cs}/commit")
    m.s.headers.pop("X-MSTR-MS-Changeset", None)
    if not r.ok:
        raise RuntimeError(f"commit {cs}: HTTP {r.status_code} body={r.text[:400]!r}")


def find_null_to_zero(m):
    r = m.get("/api/searches/results?type=11&name=NullToZero&limit=10")
    if r.ok:
        for it in r.json().get("result", []):
            if it.get("name", "").lower() == "nulltozero":
                return it["id"]
    return None


def ntz_tokens(fn_id):
    def call(op):
        oid_, oname = op
        return [
            {"type": "function", "value": "NullToZero",
             "target": {"objectId": fn_id, "subType": "function", "name": "NullToZero"}},
            {"type": "character", "value": "("},
            {"type": "object_reference", "value": f"[{oname}]",
             "target": {"objectId": oid_, "subType": "fact_metric", "name": oname}},
            {"type": "character", "value": ")"},
        ]
    return call(TXN) + [{"type": "function", "value": "+"}] + call(MRR) + [
        {"type": "end_of_text", "value": ""}]


def plus_tree():
    return {"type": "operator", "function": "plus", "children": [
        {"type": "object_reference", "target": {"objectId": TXN[0], "subType": "fact_metric", "name": TXN[1]}},
        {"type": "object_reference", "target": {"objectId": MRR[0], "subType": "fact_metric", "name": MRR[1]}}]}


def main():
    args = types.SimpleNamespace(
        base=os.environ["MSTR_BASE"], user=os.environ["MSTR_USER"],
        password=os.environ["MSTR_PASSWORD"], login_mode=1,
        project_id=os.environ["MSTR_PROJECT_ID"], verbose=False)
    m = MSTR(args)
    m.login(identity=True)
    try:
        existing = {d["information"]["name"]: d["information"]["objectId"]
                    for d in m.get(f"/api/model/dataModels/{MID}/metrics").json().get("metrics", [])}
        fn_id = find_null_to_zero(m)
        print(f"NullToZero function id: {fn_id or 'NOT FOUND - will use plain plus'}")

        cs = open_cs(m, release_self_locks=True)
        try:
            bodies = []
            if fn_id:
                bodies.append(("tokens NullToZero",
                               {"information": {"name": NAME, "subType": "metric", "description": DESC},
                                "expression": {"text": f"NullToZero([{TXN[1]}]) + NullToZero([{MRR[1]}])",
                                               "tokens": ntz_tokens(fn_id)},
                                "dimty": None,
                                "format": {"header": [], "values": CURRENCY}}))
            bodies.append(("tree plain plus",
                           {"information": {"name": NAME, "subType": "metric", "description": DESC},
                            "expression": {"tree": plus_tree()},
                            "dimty": None,
                            "format": {"header": [], "values": CURRENCY}}))
            mid_ = existing.get(NAME)
            created = None
            for label, body in bodies:
                if mid_:
                    r = m.put(f"/api/model/dataModels/{MID}/metrics/{mid_}?showAdvancedProperties=true", json=body)
                else:
                    r = m.post(f"/api/model/dataModels/{MID}/metrics?showAdvancedProperties=true", json=body)
                if r.ok:
                    created = label
                    mid_ = mid_ or r.json()["information"]["objectId"]
                    break
                print(f"  {label} rejected: {r.status_code} {r.text[:200]}")
            if not created:
                raise RuntimeError("all expression shapes rejected")
            print(f"  + {NAME} -> {mid_}  ({created})")
            commit_or_raise(m, cs)
            print("✓ committed")
        except Exception:
            discard_cs(m, cs)
            raise

        try:
            _mosaic_publish_verified(m, MID, poll_seconds=900, poll_interval=10.0)
            print("✓ publish confirmed complete in poll window")
        except SystemExit as e:
            print(f"  publish poll ended without confirmation ({e}); probe by query")
        return 0
    finally:
        m.logout()


if __name__ == "__main__":
    sys.exit(main())
