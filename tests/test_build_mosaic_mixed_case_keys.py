import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _hermetic  # noqa: E402,F401  (scrub MSTR_*/proxy env, private secret store)

# A key carried by a Snowflake table (SHIPMENT_ID) and a Postgres table (shipment_id) is one entity attribute on both
# tables. The entity used to be attached only where the column name matched exactly, while the relationships matched
# case-insensitively — so "Shipment → Invoice" through the Postgres table referenced a table Shipment was not on, and
# Studio refused it (HTTP 400): the build failed on relationships and never published.
import json  # noqa: E402
import unittest  # noqa: E402

from test_build_mosaic_round2 import DS, Resp, bm, build_args, calls, changeset_routes, make_m, quiet  # noqa: E402

COLUMNS = {
    "SHIPMENTS": [{"name": "SHIPMENT_ID", "dataType": {"type": "integer", "precision": 10, "scale": 0}},
                  {"name": "SHIP_MODE", "dataType": {"type": "utf8_char", "precision": 20, "scale": 0}}],
    "shipment_invoice": [{"name": "invoice_id", "dataType": {"type": "integer", "precision": 10, "scale": 0}},
                         {"name": "shipment_id", "dataType": {"type": "integer", "precision": 10, "scale": 0}},
                         {"name": "freight_usd", "dataType": {"type": "double", "precision": 15, "scale": 2}}],
}


def routes():
    names, on_tables, tables = {}, {}, {"n": 0, "by_name": {}}

    def new_attr(call):
        body = call.kw.get("json") or {}
        aid = f"A{len(names) + 1}"
        names[body["information"]["name"].lower()] = aid
        on_tables[aid] = {t["objectId"] for f in body.get("forms", []) for e in f.get("expressions", []) for t in e.get("tables", [])}
        return Resp(201, {"information": {"objectId": aid}, "forms": [{"id": bm.FORM_ID}]})

    def put_rels(call):
        # like Studio: both ends must be on the relationship table
        for rel in (call.kw.get("json") or {}).get("relationships", []):
            t = rel["relationshipTable"]["objectId"]
            if any(t not in on_tables.get(rel[end]["objectId"], set()) for end in ("parent", "child")):
                return Resp(400, {})
        return Resp(200, {})

    def table_cols(call):
        import base64
        table = json.loads(base64.b64decode(call.path.rstrip("/").split("/")[-1]))["tbn"]
        return Resp(200, {"columns": COLUMNS[table]})

    def new_table(call):
        tables["n"] += 1
        return Resp(201, {"information": {"objectId": f"T{tables['n']}"}})
    return {
        **changeset_routes(),
        ("GET", r"/api/datasources/\w+/catalog/namespaces"): Resp(200, {"namespaces": [{"name": "PUBLIC", "id": "NS1"}]}),
        ("GET", r"/api/datasources/\w+/catalog/namespaces/\w+/tables/.+"): table_cols,
        ("POST", r"/api/model/dataModels"): Resp(201, {"information": {"objectId": "MODEL1"}}),
        ("POST", r"/api/model/dataModels/MODEL1/tables"): new_table,
        ("POST", r"/api/model/dataModels/MODEL1/attributes"): new_attr,
        ("GET", r"/api/model/dataModels/MODEL1/attributes/\w+/relationships"): Resp(200, {"relationships": []}),
        ("GET", r"/api/model/dataModels/MODEL1/attributes/\w+"): Resp(200, {"forms": [{"id": bm.FORM_ID, "expressions": [], "lookupTable": {}}]}),
        ("PATCH", r"/api/model/dataModels/MODEL1/attributes/\w+"): Resp(200, {}),
        ("POST", r"/api/model/dataModels/MODEL1/factMetrics"): Resp(201, {"information": {"objectId": "F1"}}),
        ("PUT", r"/api/model/dataModels/MODEL1/attributes/\w+/relationships"): put_rels,
    }, names


class MixedCaseKeyTests(unittest.TestCase):
    def test_a_key_in_upper_and_lower_case_is_one_entity_on_both_tables(self):
        table_routes, names = routes()
        m = make_m(table_routes)
        code = None
        with quiet() as out:
            try:
                bm.cmd_build(m, build_args(name="Freight", source=[f"{DS}:PUBLIC:SHIPMENTS,shipment_invoice"],
                                           security_filter=[], certify=False))
            except SystemExit as e:
                code = e.code
        summary = json.loads(out.getvalue())
        self.assertEqual(summary["failures"]["relationships"], 0, summary)
        self.assertIn(code, (None, 0))
        shipment = next(c.kw["json"] for c in calls(m, "POST", r"/api/model/dataModels/MODEL1/attributes")
                        if c.kw["json"]["information"]["name"] == "Shipment")
        cols = sorted(e["expression"]["tokens"][0]["value"] for f in shipment["forms"] for e in f["expressions"])
        self.assertEqual(cols, ["SHIPMENT_ID", "shipment_id"])       # each table's own column name


if __name__ == "__main__":
    unittest.main()
