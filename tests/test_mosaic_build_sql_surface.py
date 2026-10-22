import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _hermetic  # noqa: E402,F401  (scrub MSTR_*/proxy env, private secret store)

# mosaic_build's wait for the SQL surface: seen live, the endpoint can miss one publish of a sound model, so a build that
# is not listed in time is published once more before the proof is called failed.
import contextlib  # noqa: E402
import io  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import sys  # noqa: E402
import tempfile  # noqa: E402
import types  # noqa: E402
import unittest  # noqa: E402
from unittest import mock  # noqa: E402

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "skills", "build-mosaic-model", "scripts"))
import mosaic_build as mb  # noqa: E402


class Clock:
    """time.time/time.sleep for the wait loop: each sleep moves the clock on."""

    def __init__(self):
        self.now = 1000.0

    def time(self):
        return self.now

    def sleep(self, s):
        self.now += s


class SqlSurfaceWaitTests(unittest.TestCase):
    def run_build(self, listed_after_publishes, serve_mode="in_memory", probes=None, error="Table 'zz' does not exist"):
        publishes = []
        clock = Clock()

        def sql(statement):
            if statement.startswith("SHOW COLUMNS") and len(publishes) < listed_after_publishes:
                raise RuntimeError(error)
            return []

        plan = {"name": "ZZ", "serve_mode": serve_mode}
        ma = types.SimpleNamespace(
            ApplyError=Exception,
            apply=lambda *a, **k: {"model_id": "M1"},
            readback=lambda *a, **k: [],
            publish=lambda m, mid, rows: publishes.append(mid),
            prove=lambda *a, **k: {"probes": [{"name": "total", "ok": True, "detail": ""}] if probes is None else probes},
            bm=types.SimpleNamespace(resolve_dest_folder=lambda m, f: "F"))
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            json.dump({"name": "ZZ", "sources": []}, fh)
        self.addCleanup(os.unlink, fh.name)
        args = types.SimpleNamespace(spec=fh.name, name=None, dest_folder="F")
        out = io.StringIO()
        with mock.patch.object(mb, "ma", ma), mock.patch.object(mb, "_sql", lambda m: sql), \
                mock.patch.object(mb, "plan_for", lambda m, spec: (plan, [], {"T": {"rows": 10}})), \
                mock.patch.object(mb.live, "sign_in_from_env", lambda: object()), \
                mock.patch.object(mb.time, "time", clock.time), mock.patch.object(mb.time, "sleep", clock.sleep), \
                contextlib.redirect_stdout(out):
            code = mb.cmd_build(args)
        lines = out.getvalue().splitlines()
        return code, publishes, lines, json.loads(lines[-1])

    def test_listed_after_the_first_publish_needs_nothing_more(self):
        code, publishes, lines, summary = self.run_build(1)
        self.assertEqual(code, 0)
        self.assertEqual(publishes, ["M1"])
        self.assertTrue(summary["proven"])

    def test_not_listed_in_time_is_published_once_more_then_proven(self):
        code, publishes, lines, summary = self.run_build(2)
        self.assertEqual(code, 0)
        self.assertEqual(publishes, ["M1", "M1"])
        self.assertTrue(any("publishing it again once" in ln for ln in lines))
        self.assertTrue(summary["proven"])

    def test_still_not_listed_after_the_second_publish_fails_the_proof(self):
        code, publishes, lines, summary = self.run_build(99)
        self.assertEqual(code, 1)
        self.assertEqual(publishes, ["M1", "M1"])
        self.assertTrue(any("and a second publish" in ln for ln in lines))
        self.assertEqual(summary["failures"]["post_build"], 1)

    def test_a_proof_that_checked_nothing_is_not_called_proven(self):
        code, publishes, lines, summary = self.run_build(1, probes=[{"name": "x total (source)", "ok": None, "detail": "not measurable"}])
        self.assertEqual(code, 0)
        self.assertTrue(summary["ok"])
        self.assertFalse(summary["proven"])
        self.assertTrue(any("not marked proven" in ln for ln in lines))

    def test_a_name_still_linked_to_a_deleted_model_is_said_and_not_republished(self):
        old = "5D961C2CB4EA40109D61178F9F7874B3"
        code, publishes, lines, summary = self.run_build(99, error=f"Strategy Metadata Error: Failed to get the cube object by its ID: {old}.")
        self.assertEqual(code, 1)
        self.assertEqual(publishes, ["M1"])                                   # publishing again would not help
        self.assertTrue(any(old in ln and "Rename the model" in ln for ln in lines))

    def test_a_live_model_is_not_published(self):
        code, publishes, lines, summary = self.run_build(99, serve_mode="connect_live")
        self.assertEqual(code, 1)
        self.assertEqual(publishes, [])


if __name__ == "__main__":
    unittest.main()
