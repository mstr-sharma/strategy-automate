import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _hermetic  # noqa: E402,F401  (scrub MSTR_*/proxy env, private secret store)

# Randomized builds: tables, keys and dictionary names that collide (exactly or only by case) must never produce a
# duplicate attribute in Studio (8004e409): every collision conforms onto the attribute already built under that name.
import base64  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import random  # noqa: E402
import tempfile  # noqa: E402
import unittest  # noqa: E402

from test_build_mosaic_round2 import DS, Resp, bm, build_args, changeset_routes, make_m, quiet  # noqa: E402


def routes(columns):
    names = {}

    def new_attr(call):
        name = call.kw["json"]["information"]["name"]
        if name.casefold() in names:
            return Resp(400, {"errors": [{"code": "8004e409", "message": f"The object name {name} (type: attribute) is duplicated in the Mosaic model."}]})
        names[name.casefold()] = f"A{len(names) + 1}"
        return Resp(201, {"information": {"objectId": names[name.casefold()]}, "forms": [{"id": bm.FORM_ID}]})
    tables = {"n": 0}

    def new_table(call):
        tables["n"] += 1
        return Resp(201, {"information": {"objectId": f"T{tables['n']}"}})
    return {
        **changeset_routes(),
        ("GET", r"/api/datasources/\w+/catalog/namespaces"): Resp(200, {"namespaces": [{"name": "PUBLIC", "id": "NS1"}]}),
        ("GET", r"/api/datasources/\w+/catalog/namespaces/\w+/tables/.+"):
            lambda call: Resp(200, {"columns": columns[json.loads(base64.b64decode(call.path.rstrip('/').split('/')[-1]))["tbn"]]}),
        ("POST", r"/api/model/dataModels"): Resp(201, {"information": {"objectId": "MODEL1"}}),
        ("POST", r"/api/model/dataModels/MODEL1/tables"): new_table,
        ("POST", r"/api/model/dataModels/MODEL1/attributes"): new_attr,
        ("GET", r"/api/model/dataModels/MODEL1/attributes/\w+"): Resp(200, {"forms": [{"id": bm.FORM_ID, "expressions": [], "lookupTable": {}}], "relationships": []}),
        ("PATCH", r"/api/model/dataModels/MODEL1/attributes/\w+"): Resp(200, {}),
        ("POST", r"/api/model/dataModels/MODEL1/factMetrics"): Resp(201, {"information": {"objectId": "F1"}}),
        ("PUT", r"/api/model/dataModels/MODEL1/attributes/\w+/relationships"): Resp(200, {}),
    }, names


INT = {"type": "integer", "precision": 10, "scale": 0}
TXT = {"type": "utf8_char", "precision": 40, "scale": 0}
NUM = {"type": "double", "precision": 15, "scale": 2}
NAMES = ["Product", "product", "Customer", "Region", "Vehicle", "Service", "Part", "Store"]


class NameCollisionFuzz(unittest.TestCase):
    def test_random_builds_never_post_a_duplicate_attribute_name(self):
        rng = random.Random(20261020)
        for case in range(150):
            entities = rng.sample(["PRODUCT", "CUSTOMER", "VEHICLE", "SERVICE", "PART", "STORE"], rng.randint(2, 4))
            columns, dictionary = {}, {}
            for i, entity in enumerate(entities):
                cols = [{"name": f"{entity}_ID", "dataType": INT}, {"name": f"{entity}_NAME", "dataType": TXT}]
                for other in rng.sample(entities, rng.randint(0, len(entities) - 1)):
                    if other != entity:
                        fk = f"{rng.choice(['', 'EPICOR_', 'PRIMARY_'])}{other}_ID"
                        if fk not in {c["name"] for c in cols}:
                            cols.append({"name": fk, "dataType": INT})
                        if rng.random() < 0.7:                  # the dictionary names the FK like the entity (any case)
                            dictionary[f"{entity}S.{fk}"] = {"name": rng.choice([other.title(), other.lower(), other.title()])}
                if rng.random() < 0.3:                          # a descriptor named like another entity
                    dictionary[f"{entity}S.{entity}_NAME"] = {"name": rng.choice(NAMES)}
                cols.append({"name": "AMOUNT", "dataType": NUM})
                columns[f"{entity}S"] = cols
            table_routes, names = routes(columns)
            m = make_m(table_routes)
            with tempfile.TemporaryDirectory() as d:
                path = os.path.join(d, "dict.json")
                with open(path, "w") as f:
                    json.dump({"attributes": dictionary}, f)
                with quiet() as out:
                    try:
                        bm.cmd_build(m, build_args(name="Fuzz", source=[f"{DS}:PUBLIC:{','.join(columns)}"], dictionary=path, security_filter=[], certify=False))
                    except SystemExit:
                        pass
            summary = json.loads(out.getvalue())
            self.assertEqual(summary["failures"]["attributes"], 0, f"case {case}: {dictionary}")


if __name__ == "__main__":
    unittest.main()
