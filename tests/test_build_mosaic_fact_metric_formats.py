import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _hermetic  # noqa: E402,F401  (scrub MSTR_*/proxy env, private secret store)

import json
import os
import sys
import tempfile
import types
import unittest
from unittest import mock


ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(ROOT, "skills", "build-mosaic-model", "scripts"))

import build_mosaic as bm  # noqa: E402


def category(tokens):
    return next(t["value"] for t in tokens if t["type"] == "number_category")


class Resp:
    def __init__(self, body, status=200):
        self._body, self.status_code = body, status
        self.ok = 200 <= status < 300
        self.text = json.dumps(body)

    def json(self):
        return self._body


class FakeMSTR:
    """Two fact metrics; GET/PATCH against an in-memory store."""

    def __init__(self):
        self.store = {
            "M1": {"information": {"objectId": "M1", "name": "Unit Price"}, "function": "sum",
                   "format": {"header": [], "values": []}},
            "M2": {"information": {"objectId": "M2", "name": "Units"}, "function": "sum",
                   "format": {"header": [], "values": bm.METRIC_FORMAT_PRESETS["integer"]}},
        }
        self.patches = []

    def login(self, **_):
        pass

    def get(self, path, **_):
        if path.endswith("/factMetrics"):
            return Resp({"factMetrics": [{"information": v["information"]} for v in self.store.values()]})
        return Resp(self.store[path.rsplit("/", 1)[1]])

    def patch(self, path, json=None, **_):
        mid = path.rsplit("/", 1)[1]
        self.patches.append((mid, json))
        self.store[mid].update(json)
        return Resp({})


class MetricFormatTests(unittest.TestCase):
    def test_presets_use_the_verified_category_codes(self):
        self.assertEqual(category(bm.METRIC_FORMAT_PRESETS["currency"]), "1")
        self.assertEqual(category(bm.METRIC_FORMAT_PRESETS["percent"]), "4")
        self.assertEqual(category(bm.METRIC_FORMAT_PRESETS["integer"]), "0")
        self.assertEqual(category(bm.METRIC_FORMAT_PRESETS["scientific"]), "6")

    def test_default_format_by_name_and_type(self):
        self.assertEqual(category(bm._default_metric_format("Total Revenue", {"type": "double"})), "1")
        units = bm._default_metric_format("Total Units", {"type": "int64"})
        self.assertIn({"type": "number_format", "value": "#,##0"}, units)
        # avg of an integer column is fractional -> two decimals, not #,##0
        self.assertIn({"type": "number_decimal_places", "value": "2"},
                      bm._default_metric_format("Avg Units", {"type": "int64"}, "avg"))
        # percent is never guessed from the name
        self.assertEqual(category(bm._default_metric_format("Yield Pct", {"type": "double"})), "0")

    def test_resolve_and_match(self):
        custom = [{"type": "number_category", "value": "0"}]
        self.assertEqual(bm._resolve_metric_format(custom), custom)
        self.assertEqual(bm._resolve_metric_format("hrs", {"hrs": custom}), custom)
        with self.assertRaises(SystemExit):
            bm._resolve_metric_format("nope")
        have = {"values": bm.METRIC_FORMAT_PRESETS["currency"] + [{"type": "x", "value": "y"}]}
        self.assertTrue(bm._format_matches(have, bm.METRIC_FORMAT_PRESETS["currency"]))
        self.assertFalse(bm._format_matches(have, bm.METRIC_FORMAT_PRESETS["integer"]))


class PatchFactMetricsTests(unittest.TestCase):
    def run_cmd(self, spec, dry_run=False):
        m = FakeMSTR()
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(spec, f)
        args = types.SimpleNamespace(model_id="MODEL", spec=f.name, dry_run=dry_run)
        try:
            with mock.patch.object(bm, "open_cs", return_value="CS"), \
                 mock.patch.object(bm, "commit_cs") as commit, \
                 mock.patch.object(bm, "discard_cs"), \
                 mock.patch("sys.stdout"), mock.patch("sys.stderr"):
                bm.cmd_patch_fact_metrics(m, args)
        finally:
            os.unlink(f.name)
        return m, commit

    def test_patches_only_what_differs_in_one_changeset(self):
        m, commit = self.run_cmd({"metrics": [
            {"name": "unit price", "function": "avg", "format": "currency"},
            {"name": "Units", "function": "sum", "format": "integer"},
        ]})
        self.assertEqual([mid for mid, _ in m.patches], ["M1"])
        self.assertEqual(m.patches[0][1]["function"], "avg")
        commit.assert_called_once()

    def test_dry_run_writes_nothing(self):
        m, commit = self.run_cmd({"metrics": [{"name": "Unit Price", "function": "avg"}]}, dry_run=True)
        self.assertEqual(m.patches, [])
        commit.assert_not_called()

    def test_unknown_metric_name_dies_before_any_write(self):
        with self.assertRaises(SystemExit):
            self.run_cmd({"metrics": [{"name": "Nope", "function": "avg"}]})


if __name__ == "__main__":
    unittest.main()
