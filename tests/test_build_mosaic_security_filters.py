import os
import sys
import unittest


ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(ROOT, "skill", "scripts"))

import build_mosaic as bm  # noqa: E402


ATTR_ID = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
FORM_ID = "BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB"


class _Resp:
    def __init__(self, ok=True):
        self.ok = ok
        self.status_code = 204 if ok else 400
        self.text = ""


class _FakeMSTR:
    def __init__(self):
        self.patch_calls = []
        self.post_calls = []

    def patch(self, path, **kwargs):
        self.patch_calls.append((path, kwargs))
        return _Resp(True)

    def post(self, path, **kwargs):
        self.post_calls.append((path, kwargs))
        return _Resp(False)


class MosaicSecurityFilterTests(unittest.TestCase):
    def test_shorthand_uses_mosaic_form_qualification_shape(self):
        q = bm._parse_mosaic_security_filter_qualification(f"{ATTR_ID}:{FORM_ID}=1")

        tree = q["tree"]
        pred = tree["predicateTree"]
        self.assertEqual(tree["type"], "predicate_form_qualification")
        self.assertEqual(pred["function"], "equals")
        self.assertEqual(pred["attribute"]["objectId"], ATTR_ID)
        self.assertEqual(pred["form"]["objectId"], FORM_ID)
        self.assertEqual(pred["form"]["subType"], "attribute_form_system")
        self.assertEqual(pred["parameters"][0]["constant"], {"type": "int32", "value": "1"})

    def test_shorthand_defaults_to_universal_id_form(self):
        q = bm._parse_mosaic_security_filter_qualification(f"{ATTR_ID}=Books")

        pred = q["tree"]["predicateTree"]
        self.assertEqual(pred["form"]["objectId"], bm.FORM_ID)
        self.assertEqual(pred["parameters"][0]["constant"], {"type": "string", "value": "Books"})

    def test_member_assignment_uses_mosaic_members_path(self):
        fake = _FakeMSTR()

        ok = bm._assign_security_filter_members(fake, "MODELID", "SFID", ["USERID"])

        self.assertTrue(ok)
        self.assertEqual(fake.patch_calls[0][0], "/api/dataModels/MODELID/securityFilters/SFID/members")
        self.assertEqual(
            fake.patch_calls[0][1]["json"],
            {"operationList": [{"op": "addElements", "path": "/Members", "value": ["USERID"]}]},
        )
        self.assertEqual(fake.post_calls, [])


if __name__ == "__main__":
    unittest.main()
