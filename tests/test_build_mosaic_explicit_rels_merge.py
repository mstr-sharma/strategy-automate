import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _hermetic  # noqa: E402,F401  (scrub MSTR_*/proxy env, private secret store)

# One explicit relationship (a Region → Customer hierarchy from the dictionary) is added to the inferred ones. It used to
# replace inference wholesale, so the descriptor → key and key → fact relationships were never written and names could
# not reach the facts ("Amount by Customer Name" had no path).
import json  # noqa: E402
import os  # noqa: E402
import tempfile  # noqa: E402
import unittest  # noqa: E402

from test_build_mosaic_round2 import DS, Resp, bm, build_args, calls, changeset_routes, make_m, quiet  # noqa: E402

COLUMNS = {
    "CUSTOMERS": [{"name": "CUSTOMER_ID", "dataType": {"type": "integer", "precision": 10, "scale": 0}},
                  {"name": "CUSTOMER_NAME", "dataType": {"type": "utf8_char", "precision": 40, "scale": 0}},
                  {"name": "REGION", "dataType": {"type": "utf8_char", "precision": 20, "scale": 0}}],
    "SHIPMENTS": [{"name": "SHIPMENT_ID", "dataType": {"type": "integer", "precision": 10, "scale": 0}},
                  {"name": "CUSTOMER_ID", "dataType": {"type": "integer", "precision": 10, "scale": 0}},
                  {"name": "AMOUNT", "dataType": {"type": "double", "precision": 15, "scale": 2}}],
}


def routes():
    names = {}

    def new_attr(call):
        body = call.kw.get("json") or {}
        aid = f"A{len(names) + 1}"
        names[aid] = body["information"]["name"]
        return Resp(201, {"information": {"objectId": aid}, "forms": [{"id": bm.FORM_ID}]})

    def table_cols(call):
        import base64
        table = json.loads(base64.b64decode(call.path.rstrip("/").split("/")[-1]))["tbn"]
        return Resp(200, {"columns": COLUMNS[table]})
    tables = {"n": 0}

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
        ("PUT", r"/api/model/dataModels/MODEL1/attributes/\w+/relationships"): Resp(200, {}),
    }, names


class ExplicitRelationshipsMergeTests(unittest.TestCase):
    def test_one_explicit_relationship_keeps_the_inferred_ones(self):
        table_routes, names = routes()
        m = make_m(table_routes)
        with tempfile.TemporaryDirectory() as d:
            dictionary = os.path.join(d, "dict.json")
            with open(dictionary, "w") as f:
                json.dump({"relationships": [{"parent": "CUSTOMERS.REGION", "child": "CUSTOMERS.CUSTOMER_ID",
                                              "relationship_table": "CUSTOMERS", "type": "one_to_many"}]}, f)
            with quiet() as out:
                try:
                    bm.cmd_build(m, build_args(name="Freight", source=[f"{DS}:PUBLIC:CUSTOMERS,SHIPMENTS"], dictionary=dictionary,
                                               security_filter=[], certify=False))
                except SystemExit:
                    pass
        summary = json.loads(out.getvalue())
        self.assertEqual(summary["failures"]["relationships"], 0, summary)
        written = set()
        for c in calls(m, "PUT", r"/api/model/dataModels/MODEL1/attributes/\w+/relationships"):
            for rel in c.kw["json"]["relationships"]:
                written.add((names[rel["parent"]["objectId"]], names[rel["child"]["objectId"]]))
        self.assertIn(("Region", "Customer"), written)                 # the explicit hierarchy
        self.assertIn(("Customer Name", "Customer"), written)          # descriptor → key, inferred
        self.assertIn(("Customer", "Shipment"), written)               # key → fact, inferred
        self.assertEqual(sum(1 for p, c in written if {p, c} == {"Region", "Customer"}), 1)   # never both directions


if __name__ == "__main__":
    unittest.main()
