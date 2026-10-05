"""preflight_model_check.py: the legacy-blueprint comparison and the order of its I/O."""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _hermetic  # noqa: E402,F401  (scrub MSTR_*/proxy env, private secret store)

import contextlib
import io
import json
import os
import stat
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "build-mosaic-model", "scripts"))

import preflight_model_check as pf  # noqa: E402

COLUMNS = {
    "CUSTOMER": [{"name": "CUSTOMER_ID", "dataType": {"type": "integer"}},
                 {"name": "CUSTOMER_DESC", "dataType": {"type": "varchar"}}],
    "SALES": [{"name": "CUSTOMER_ID", "dataType": {"type": "integer"}},
              {"name": "UNIT_PRICE", "dataType": {"type": "money"}},
              {"name": "AMOUNT", "dataType": {"type": "decimal", "precision": 18, "scale": 2}}],
}


def by_table():
    return {t: [pf.classify_column(t, c) for c in cols] for t, cols in COLUMNS.items()}


def findings_for(blueprint):
    found = []
    pf.check_contextual_fit(by_table(), blueprint, found)
    return [(f.severity, f.code, f.subject) for f in found]


def attribute(*cols):
    return {"forms": [{"category": "ID" if i == 0 else "DESC", "col": c, "table": "T"} for i, c in enumerate(cols)]}


class BlueprintComparisonTests(unittest.TestCase):
    def test_documented_shape_matches_on_form_columns_not_entity_names(self):
        # The docstring's own example shape: entity-keyed, columns in forms[].col.
        got = findings_for({"attributes": {"Customer": attribute("CUSTOMER_ID", "CUSTOMER_DESC")}, "metrics": {}})
        self.assertNotIn("BLUEPRINT_ATTR_MISSING", [code for _s, code, _n in got])

    def test_absent_columns_are_an_error(self):
        got = findings_for({"attributes": {"Region": attribute("REGION_ID", "REGION_DESC")}, "metrics": {}})
        self.assertIn(("ERROR", "BLUEPRINT_ATTR_MISSING", "Region"), got)

    def test_partly_missing_forms_and_metric_like_columns_warn(self):
        got = findings_for({"attributes": {"Customer": attribute("CUSTOMER_ID", "CUSTOMER_NAME"),
                                           "Price Band": attribute("UNIT_PRICE")}, "metrics": {}})
        self.assertIn(("WARN", "BLUEPRINT_FORM_MISSING", "Customer"), got)
        self.assertIn(("WARN", "BLUEPRINT_ATTR_AS_METRIC", "Price Band (SALES.UNIT_PRICE)"), got)
        self.assertNotIn("ERROR", [s for s, _c, _n in got])

    def test_form_less_attributes_fall_back_to_their_name(self):
        self.assertEqual(pf.blueprint_columns("customer_id", {}), ["CUSTOMER_ID"])
        self.assertNotIn("BLUEPRINT_ATTR_MISSING",
                         [c for _s, c, _n in findings_for({"attributes": {"customer_id": {}}, "metrics": {}})])

    def test_wrong_shapes_are_refused(self):
        for bad in ([], {"attributes": []}, {"attributes": {"X": "CUSTOMER_ID"}}, {"metrics": []}):
            with self.assertRaises(SystemExit):
                pf.validate_blueprint(bad)


class FakeMSTR:
    instances = []

    def __init__(self, ns):
        FakeMSTR.instances.append(self)
        self.logged_out = False

    def login(self):
        pass

    def logout(self):
        self.logged_out = True


class MainOrderTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = tmp.name
        FakeMSTR.instances = []

    def run_main(self, *extra):
        argv = ["--base", "https://tenant.invalid/MicroStrategyLibrary", "--instance", "WH",
                "--schema", "S", "--tables", "CUSTOMER", "SALES", *extra]
        with mock.patch.object(pf.bm, "MSTR", FakeMSTR), \
                mock.patch.object(pf.bm, "resolve_instance_id", return_value="INST"), \
                mock.patch.object(pf.bm, "fetch_table_metadata",
                                  side_effect=lambda m, inst, schema, t: {"columns": COLUMNS[t]}), \
                contextlib.redirect_stdout(io.StringIO()) as out:
            pf.main(argv)
        return out.getvalue()

    def test_bad_blueprint_fails_before_anyone_signs_in(self):
        missing = os.path.join(self.tmp, "nope.json")
        broken = os.path.join(self.tmp, "broken.json")
        with open(broken, "w") as f:
            f.write("{not json")
        for path, message in ((missing, "--blueprint"), (broken, "not valid JSON")):
            with self.assertRaises(SystemExit) as cm:
                self.run_main("--blueprint", path)
            self.assertIn(message, str(cm.exception.code))
        self.assertEqual(FakeMSTR.instances, [])

    def test_documented_blueprint_passes_the_default_error_gate(self):
        bp = os.path.join(self.tmp, "bp.json")
        with open(bp, "w") as f:
            json.dump({"attributes": {"Customer": attribute("CUSTOMER_ID", "CUSTOMER_DESC")}, "metrics": {}}, f)
        out = os.path.join(self.tmp, "report.json")
        with open(out, "w") as f:
            f.write("{}")
        os.chmod(out, 0o644)
        text = self.run_main("--blueprint", bp, "--out", out)      # no SystemExit(1): no ERROR finding
        self.assertIn("Blueprint: yes", text)
        self.assertTrue(FakeMSTR.instances[0].logged_out)
        with open(out) as f:
            self.assertTrue(json.load(f)["blueprint_used"])
        if os.name == "posix":
            self.assertEqual(stat.S_IMODE(os.stat(out).st_mode), 0o600)


if __name__ == "__main__":
    unittest.main()
