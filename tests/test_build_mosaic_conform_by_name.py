import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _hermetic  # noqa: E402,F401  (scrub MSTR_*/proxy env, private secret store)

# A foreign key the dictionary names like an entity built from another table's key (SERVICE_RECORDS.EPICOR_PRODUCT_ID
# named "Product", PRODUCTS.PRODUCT_ID → entity "Product") must conform to that entity attribute. Studio refuses a
# second attribute with the same name (8004e409), which used to fail the build and skip publishing.
import json  # noqa: E402
import os  # noqa: E402
import tempfile  # noqa: E402
import unittest  # noqa: E402

from test_build_mosaic_round2 import DS, Resp, bm, build_args, calls, changeset_routes, make_m, quiet  # noqa: E402

COLUMNS = {
    "PRODUCTS": [{"name": "PRODUCT_ID", "dataType": {"type": "integer", "precision": 10, "scale": 0}},
                 {"name": "PRODUCT_NAME", "dataType": {"type": "utf8_char", "precision": 40, "scale": 0}}],
    "SERVICE_RECORDS": [{"name": "SERVICE_ID", "dataType": {"type": "integer", "precision": 10, "scale": 0}},
                        {"name": "EPICOR_PRODUCT_ID", "dataType": {"type": "integer", "precision": 10, "scale": 0}},
                        {"name": "AMOUNT", "dataType": {"type": "double", "precision": 15, "scale": 2}}],
}


def routes():
    names, patched = {}, []

    def new_attr(call):
        body = call.kw.get("json") or {}
        name = body["information"]["name"]
        if name.lower() in names:
            return Resp(400, {"errors": [{"code": "8004e409", "message": f"The object name {name} (type: attribute) is duplicated in the Mosaic model."}]})
        names[name.lower()] = f"A{len(names) + 1}"
        return Resp(201, {"information": {"objectId": names[name.lower()]}, "forms": [{"id": bm.FORM_ID}]})

    def get_attr(call):
        return Resp(200, {"forms": [{"id": bm.FORM_ID, "expressions": [], "lookupTable": {}}], "relationships": []})

    def patch_attr(call):
        patched.append(call)
        return Resp(200, {})

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
        ("GET", r"/api/model/dataModels/MODEL1/attributes/\w+"): get_attr,
        ("PATCH", r"/api/model/dataModels/MODEL1/attributes/\w+"): patch_attr,
        ("POST", r"/api/model/dataModels/MODEL1/factMetrics"): Resp(201, {"information": {"objectId": "F1"}}),
        ("PUT", r"/api/model/dataModels/MODEL1/attributes/\w+/relationships"): Resp(200, {}),
    }, names, patched


class ConformByNameTests(unittest.TestCase):
    def test_a_foreign_key_named_like_an_entity_joins_that_entity_attribute(self):
        table_routes, names, patched = routes()
        m = make_m(table_routes)
        with tempfile.TemporaryDirectory() as d:
            dictionary = os.path.join(d, "dict.json")
            with open(dictionary, "w") as f:
                json.dump({"attributes": {"SERVICE_RECORDS.EPICOR_PRODUCT_ID": {"name": "Product"}}}, f)
            code = None
            with quiet() as out:
                try:
                    bm.cmd_build(m, build_args(name="Service", source=[f"{DS}:PUBLIC:PRODUCTS,SERVICE_RECORDS"], dictionary=dictionary,
                                               security_filter=[], certify=False))
                except SystemExit as e:
                    code = e.code
        summary = json.loads(out.getvalue())
        self.assertEqual(summary["failures"]["attributes"], 0, summary)
        self.assertIn(code, (None, 0))
        self.assertEqual(list(names).count("product"), 1)              # one Product attribute, never a duplicate POST
        posts = [c.kw["json"]["information"]["name"] for c in calls(m, "POST", r"/api/model/dataModels/MODEL1/attributes")]
        self.assertEqual(posts.count("Product"), 1, posts)
        # the foreign key joined the entity attribute as another expression of its ID form
        joined = [c for c in patched if any(e.get("expression", {}).get("tokens", [{}])[0].get("value") == "EPICOR_PRODUCT_ID"
                                            for f in (c.kw.get("json") or {}).get("forms", []) for e in f.get("expressions", []))]
        self.assertEqual(len(joined), 1)
        self.assertEqual(joined[0].path.split("?")[0], f"/api/model/dataModels/MODEL1/attributes/{names['product']}")


if __name__ == "__main__":
    unittest.main()
