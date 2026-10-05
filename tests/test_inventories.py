"""strategy_mosaic_inventory.py / strategy_semantic_inventory.py: which objects count as Mosaic
models, and how an incomplete inventory is reported."""
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

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "skills", "build-mosaic-model", "scripts"))

from fake_tenant import FakeTenant  # noqa: E402

import strategy_mosaic_inventory as mi  # noqa: E402
import strategy_semantic_inventory as si  # noqa: E402

GOOD, BAD, CUBE = "A" * 32, "B" * 32, "C" * 32


class MosaicClassificationTests(unittest.TestCase):
    def test_779_needs_ext_type_448_or_none(self):
        self.assertTrue(mi.is_mosaic_model({"subtype": 779, "extType": 448}))
        self.assertTrue(mi.is_mosaic_model({"subType": "779", "extType": "448"}))
        self.assertTrue(mi.is_mosaic_model({"subtype": 779}))                  # older payloads
        self.assertFalse(mi.is_mosaic_model({"subtype": 779, "extType": 449}))  # data-import cube
        self.assertFalse(mi.is_mosaic_model({"subtype": 776, "extType": 448}))  # classic cube
        self.assertFalse(mi.is_mosaic_model({"subtype": "x"}))

    def test_failed_reads_are_counted_per_kind(self):
        definitions = {
            GOOD: {"ok": True, "subresources": {"model": {"ok": True}, "folders": {"ok": True}}, "tableDetailFailures": 0},
            BAD: {"ok": True, "subresources": {"model": {"ok": True}, "folders": {"ok": False}}, "tableDetailFailures": 2},
            "": {"ok": False, "error": "missing model id", "subresources": {}},
        }
        self.assertEqual(mi.failed_reads(definitions), {"folders": 1, "model": 1, "tableDetails": 2})
        self.assertEqual(mi.failed_reads({GOOD: definitions[GOOD]}), {})


class MosaicInventoryRunTests(unittest.TestCase):
    def setUp(self):
        self.tenant = FakeTenant()
        self.addCleanup(self.tenant.close)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = tmp.name
        self.tenant.state.search_items = [
            {"id": GOOD, "name": "Sales Model", "type": 3, "subtype": 779, "extType": 448},
            {"id": BAD, "name": "Ops Model", "type": 3, "subtype": 779, "extType": 448},
            {"id": CUBE, "name": "Imported Cube", "type": 3, "subtype": 779, "extType": 449},
        ]
        tenant = self.tenant

        @tenant.route("GET", r"/api/model/dataModels/(\w+)(/.*)?")
        def model(call, m):
            if tenant._user(call) is None:
                return 401, {"code": "ERR009", "message": "expired"}, {}
            model_id, suffix = m.group(1), m.group(2) or ""
            if model_id == BAD and suffix == "/folders":
                return 500, {"code": "ERR001", "message": "folders unavailable"}, {}
            if suffix == "":
                return 200, {"information": {"objectId": model_id, "name": model_id[:4], "subType": 779},
                             "dataServeMode": "in_memory"}, {}
            if suffix == "/tables":
                return 200, {"tables": [{"information": {"objectId": "T" * 32, "name": "FACT"}}]}, {}
            if suffix.startswith("/tables/"):
                return 200, {"information": {"objectId": "T" * 32, "name": "FACT"},
                             "physicalTable": {"type": "normal", "columns": [{"name": "X"}]}}, {}
            return 200, {}, {}

    def test_partial_failure_exits_3_and_cubes_are_never_read(self):
        out = os.path.join(self.tmp, "inv.json")
        with open(out, "w") as f:
            f.write("{}")
        os.chmod(out, 0o644)
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = mi.main(["--base", self.tenant.base, "--user", "alice", "--password", "correct horse",
                            "--auth-method", "password", "--project-name", "Tutorial",
                            "--workers", "2", "--out", out])
        self.assertEqual(code, mi.EXIT_PARTIAL, stderr.getvalue())
        summary = json.loads(stdout.getvalue())
        self.assertFalse(summary["ok"])
        self.assertEqual(summary["failedReads"], {"folders": 1})
        self.assertEqual(summary["modelCount"], 2)
        self.assertEqual(self.tenant.count("GET", r"/api/model/dataModels/%s.*" % CUBE), 0)
        self.assertEqual(self.tenant.open_sessions, 0)
        with open(out) as f:
            self.assertEqual(json.load(f)["failedReads"], {"folders": 1})
        if os.name == "posix":
            self.assertEqual(stat.S_IMODE(os.stat(out).st_mode), 0o600)

    def test_complete_inventory_exits_0(self):
        self.tenant.state.search_items = self.tenant.state.search_items[:1]
        with contextlib.redirect_stdout(io.StringIO()) as stdout, contextlib.redirect_stderr(io.StringIO()):
            code = mi.main(["--base", self.tenant.base, "--user", "alice", "--password", "correct horse",
                            "--auth-method", "password", "--project-name", "Tutorial",
                            "--out", os.path.join(self.tmp, "inv.json")])
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(stdout.getvalue())["ok"])


class SemanticInventoryTests(unittest.TestCase):
    def test_failed_reads_cover_families_and_the_system_hierarchy(self):
        inventory = {"analysis": {"attributes": {"definitionReadFailed": 0},
                                  "metrics": {"definitionReadFailed": 3}},
                     "systemHierarchy": {"definitionOk": False}}
        self.assertEqual(si.failed_reads(inventory), {"metrics": 3, "systemHierarchy": 1})
        inventory["systemHierarchy"]["definitionOk"] = True
        inventory["analysis"]["metrics"]["definitionReadFailed"] = 0
        self.assertEqual(si.failed_reads(inventory), {})
        self.assertEqual(si.failed_reads({"analysis": {}}), {})               # --skip-system-hierarchy


if __name__ == "__main__":
    unittest.main()
