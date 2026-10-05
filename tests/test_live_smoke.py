"""The live smoke script (tests/live/smoke.py) run against the fake tenant, so it can't rot
between the rare runs against a real one."""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _hermetic  # noqa: E402,F401  (scrub MSTR_*/proxy env, private secret store)

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "live"))

import smoke  # noqa: E402
from fake_tenant import PROJECT_ID, FakeTenant  # noqa: E402


class LiveSmokeSelfTest(unittest.TestCase):
    def setUp(self):
        self.tenant = FakeTenant()
        self.addCleanup(self.tenant.close)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def run_smoke(self, password, *extra):
        env = {"MSTR_BASE": self.tenant.base, "MSTR_USER": "alice", "MSTR_PASSWORD": password,
               "MSTR_SESSION_CACHE": "0"}
        report = os.path.join(self.tmp.name, "report.json")
        out = io.StringIO()
        with mock.patch.dict(os.environ, env), contextlib.redirect_stdout(out):
            code = smoke.main(["--no-mcp", "--no-contract", "--json", report, *extra])
        with open(report, encoding="utf-8") as f:
            return code, out.getvalue(), {s["step"]: s for s in json.load(f)["steps"]}

    def test_passes_against_a_healthy_tenant_and_leaves_no_session(self):
        code, out, steps = self.run_smoke("correct horse", "--project", "Tutorial")
        self.assertEqual(code, 0, out)
        for name in ("reachable", "sign in", "session", "projects", "spec", "api read", "search", "logout",
                     "session hygiene"):
            self.assertEqual(steps[name]["status"], "ok", (name, steps[name]))
        self.assertEqual(self.tenant.open_sessions, 0)
        self.assertEqual(self.tenant.count("POST", "/api/auth/login"), 1)
        # nothing a CI log must not show
        for secret in ("correct horse", "127.0.0.1", PROJECT_ID):
            self.assertNotIn(secret, out)

    def test_a_bad_credential_fails_the_run_cleanly(self):
        code, out, steps = self.run_smoke("wrong")
        self.assertEqual(code, 1)
        self.assertEqual(steps["sign in"]["status"], "FAIL")
        self.assertNotIn("projects", steps)
        self.assertNotIn("wrong", out.replace("wrong-", ""))

    def test_writes_are_never_sent(self):
        self.run_smoke("correct horse", "--project", "Tutorial")
        writes = [(c.method, c.path) for c in self.tenant.calls if c.method not in ("GET", "HEAD", "OPTIONS")]
        self.assertEqual(writes, [("POST", "/api/auth/login"), ("POST", "/api/auth/logout")])


if __name__ == "__main__":
    unittest.main()
