"""End-to-end runs of the platform CLIs against an in-process fake tenant (tests/fake_tenant.py).

What these pin down, beyond the unit tests:
- session hygiene: every command logs out what it signed in, and nothing else;
- request budgets: a read is login + call + logout; reuse saves the logins; paging stops on time;
- changeset safety: commits on success, discards on failure, on a failed commit and on a dropped
  connection, and never leaves a changeset open;
- secrets: never printed, stored 0600, dry runs send nothing;
- resilience: transient 503s on reads are absorbed, network failures end in a clean FATAL.
"""
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

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "skills", "strategy-platform", "scripts"))

import fake_tenant  # noqa: E402
from fake_tenant import FakeTenant  # noqa: E402

import _client  # noqa: E402
import strategy_api  # noqa: E402
import strategy_auth  # noqa: E402

PASSWORD = "correct horse"


class TenantTestCase(unittest.TestCase):
    """Fresh fake tenant, private config/cache dirs, file secret store, no MSTR_* leaking in."""

    def setUp(self):
        self.tenant = FakeTenant()
        self.addCleanup(self.tenant.close)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = tmp.name
        env = {k: v for k, v in os.environ.items() if not k.startswith("MSTR_")}
        env.update({"MSTR_BASE": self.tenant.base, "MSTR_SECRET_STORE": "file",
                    "XDG_CONFIG_HOME": os.path.join(self.tmp, "config"),
                    "XDG_CACHE_HOME": os.path.join(self.tmp, "cache"),
                    "MSTR_HTTP_TIMEOUT": "10", "TMPDIR": self.tmp})
        patcher = mock.patch.dict(os.environ, env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        tempfile.tempdir = None   # re-read TMPDIR
        self.addCleanup(setattr, tempfile, "tempdir", None)

    def password_env(self):
        return mock.patch.dict(os.environ, {"MSTR_USER": "alice", "MSTR_PASSWORD": PASSWORD})

    def run_cli(self, main, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def api(self, *argv):
        return self.run_cli(strategy_api.main, *argv)

    def auth(self, *argv):
        return self.run_cli(strategy_auth.main, *argv)

    def assert_no_secret(self, *texts):
        for text in texts:
            self.assertNotIn(PASSWORD, text)
            for token in list(self.tenant.state.sessions) + list(self.tenant.state.api_tokens):
                self.assertNotIn(token, text)


class AuthCliTests(TenantTestCase):
    def test_methods_needs_no_credentials_and_reports_the_tenant(self):
        code, out, err = self.auth("methods")
        self.assertEqual(code, 0, err)
        report = json.loads(out)
        self.assertIn("4096 API token", report["tenant_login_modes"])
        self.assertEqual(report["this_machine"]["secret_store"], "file")
        self.assertFalse([w for w in report["warnings"] if "Origin" in w])   # CORS is locked down
        self.assertEqual(set(report["this_machine"]["http_stack"]), {"python", "requests", "urllib3", "tls"})
        self.assertEqual(self.tenant.count("POST", "/api/auth/login"), 0)

    def test_methods_warns_when_cors_echoes_any_origin(self):
        self.tenant.cors_any_origin = True
        code, out, _ = self.auth("methods")
        self.assertEqual(code, 0)
        self.assertTrue(any("ANY Origin" in w for w in json.loads(out)["warnings"]))

    def test_password_login_leaves_no_session_and_prints_no_secret(self):
        with self.password_env():
            code, out, err = self.auth("login", "--method", "password")
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)["user"], "Alice Example")
        self.assertEqual(self.tenant.open_sessions, 0)
        self.assert_no_secret(out, err)

    def test_wrong_password_is_a_clean_failure(self):
        with mock.patch.dict(os.environ, {"MSTR_USER": "alice", "MSTR_PASSWORD": "wrong-password"}):
            code, out, err = self.auth("login", "--method", "password")
        self.assertEqual(code, 2)
        self.assertIn("FATAL: sign-in with loginMode 1", err)
        self.assertNotIn("wrong-password", err + out)

    def test_api_token_lifecycle_is_private_and_revocable(self):
        with self.password_env():
            code, out, err = self.auth("login", "--method", "password", "--save-api-token")
            self.assertEqual(code, 0, err)
            # alice already has a token: creating one would replace it, so that needs consent
            self.assertIn("already has an API token", json.loads(out)["api_token"])
            self.assertIn("api-token-alice", self.tenant.state.api_tokens)
            code, out, err = self.auth("login", "--method", "password", "--save-api-token",
                                       "--replace-api-token")
        self.assertEqual(code, 0, err)
        self.assertIn("saved to the file store", json.loads(out)["api_token"])
        self.assertNotIn("api-token-alice", self.tenant.state.api_tokens)
        secrets_file = os.path.join(self.tmp, "config", "strategy-automate", "secrets.json")
        self.assertEqual(stat.S_IMODE(os.stat(secrets_file).st_mode), 0o600)
        with open(secrets_file, encoding="utf-8") as f:
            self.assertNotIn(PASSWORD, f.read())
        self.assert_no_secret(out, err)

        code, out, _ = self.auth("status")
        self.assertTrue(json.loads(out)["saved_api_token"]["usable"])

        # a later command signs in with the saved token, without a password
        code, out, err = self.api("call", "getProjects")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.tenant.calls_to("POST", "/api/auth/login")[-1].body["loginMode"], 4096)

        code, out, _ = self.auth("logout", "--forget-api-token")
        self.assertEqual(json.loads(out)["api_token"], "revoked")
        self.assertNotIn("alice", self.tenant.state.api_tokens.values())
        code, out, _ = self.auth("status")
        self.assertIsNone(json.loads(out)["saved_api_token"])
        self.assertEqual(self.tenant.open_sessions, 0)

    def test_unreachable_tenant_is_a_clean_failure(self):
        self.tenant.close()
        code, out, err = self.auth("methods")
        self.assertEqual(code, 2)
        self.assertIn("FATAL: network error", err)

    def test_not_a_library_url(self):
        with mock.patch.dict(os.environ, {"MSTR_BASE": self.tenant.root + "/wrong"}):
            code, _, err = self.auth("methods")
        self.assertEqual(code, 2)
        self.assertIn("answered 404; check MSTR_BASE is the Library URL", err)


class ApiCliTests(TenantTestCase):
    def setUp(self):
        super().setUp()
        p = self.password_env()
        p.start()
        self.addCleanup(p.stop)

    def test_sync_then_offline_lookups(self):
        code, out, err = self.api("sync")
        self.assertEqual(code, 0, err)
        self.assertTrue(json.loads(out)["cached"].startswith(os.path.join(self.tmp, "cache")))
        calls = self.tenant.count()
        code, out, _ = self.api("ops", "--search", "group")
        self.assertEqual({o["operation"] if "operation" in o else o.get("id") for o in json.loads(out)},
                         {"getUserGroups", "createUserGroup", "deleteUserGroup"})
        code, out, _ = self.api("describe", "createUserGroup")
        self.assertIn("name", json.dumps(json.loads(out)))
        self.assertEqual(self.tenant.count(), calls, "lookups must come from the cache")

    def test_spec_behind_sign_in_is_fetched_after_signing_in(self):
        self.tenant.require_auth_for_spec = True
        code, out, err = self.api("sync")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.tenant.open_sessions, 0)

    def test_a_read_costs_login_call_logout(self):
        self.api("sync")
        before = len(self.tenant.calls)
        code, out, err = self.api("call", "getUserGroups", "-p", "limit=5")
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)["body"], [{"id": "G1", "name": "Analysts"}])
        sent = [(c.method, c.path) for c in self.tenant.calls[before:]]
        self.assertEqual(sent, [("POST", "/api/auth/login"), ("GET", "/api/usergroups"),
                                ("POST", "/api/auth/logout")])
        self.assertEqual(self.tenant.open_sessions, 0)
        self.assert_no_secret(out, err)

    def test_writes_without_yes_send_nothing(self):
        self.api("sync")
        before = len(self.tenant.calls)
        code, out, _ = self.api("call", "createUserGroup", "--body", '{"name": "Ops"}')
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(out)["dry_run"])
        self.assertEqual(len(self.tenant.calls), before)

    def test_write_with_yes_then_read_back(self):
        self.api("sync")
        code, out, err = self.api("call", "createUserGroup", "--body", '{"name": "Ops"}', "--yes")
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)["status"], 201)
        code, out, _ = self.api("call", "getUserGroups")
        self.assertIn("Ops", [g["name"] for g in json.loads(out)["body"]])

    def test_spec_validation_stops_bad_requests_before_sign_in(self):
        self.api("sync")
        before = len(self.tenant.calls)
        code, _, err = self.api("call", "createUserGroup", "--body", '{"description": "no name"}', "--yes")
        self.assertEqual(code, 2)
        self.assertIn("missing required field(s): name", err)
        code, _, err = self.api("call", "getUserGroups", "-p", "limt=5")
        self.assertEqual(code, 2)
        self.assertIn("unknown parameter 'limt'", err)
        sent = [c.path for c in self.tenant.calls[before:]]
        self.assertNotIn("/api/usergroups", sent)

    def test_changeset_is_opened_in_the_project_and_committed(self):
        self.api("sync")
        code, out, err = self.api("call", "createDataModel", "--project", "Tutorial", "--yes",
                                  "--body", '{"information": {"name": "Sales"}}')
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)["changeset"], "committed")
        (cs,) = self.tenant.state.changesets.values()
        self.assertEqual(cs, {"state": "committed", "project": fake_tenant.PROJECT_ID})
        self.assertEqual(self.tenant.open_sessions, 0)

    def test_failed_write_discards_the_changeset(self):
        self.api("sync")
        self.tenant.fail("POST", "/api/model/dataModels", status=400)
        code, out, _ = self.api("call", "createDataModel", "--project", fake_tenant.PROJECT_ID, "--yes",
                                "--body", '{"information": {}}')
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(out)["changeset"], "discarded")
        self.assertEqual([c["state"] for c in self.tenant.state.changesets.values()], ["discarded"])

    def test_failed_commit_discards_the_changeset(self):
        self.api("sync")
        self.tenant.fail("POST", r"/api/model/changesets/\w+/commit", status=500)
        code, out, _ = self.api("call", "createDataModel", "--project", fake_tenant.PROJECT_ID, "--yes",
                                "--body", '{"information": {}}')
        self.assertIn("commit failed", json.loads(out)["changeset"])
        self.assertEqual([c["state"] for c in self.tenant.state.changesets.values()], ["discarded"])

    def test_dropped_connection_discards_the_changeset_and_fails_cleanly(self):
        self.api("sync")
        self.tenant.fail("POST", "/api/model/dataModels", drop=True)
        code, out, err = self.api("call", "createDataModel", "--project", fake_tenant.PROJECT_ID, "--yes",
                                  "--body", '{"information": {}}')
        self.assertEqual(code, 2)
        self.assertIn("FATAL: network error", err)
        self.assertEqual([c["state"] for c in self.tenant.state.changesets.values()], ["discarded"])
        self.assertEqual(self.tenant.open_sessions, 0)

    def test_reads_that_need_a_changeset_always_discard_it(self):
        self.api("sync")
        code, out, err = self.api("call", "getDataModel", "-p", "dataModelId=ABC", "--project",
                                  fake_tenant.PROJECT_ID)
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)["changeset"], "discarded")

    def test_binary_export_goes_to_a_private_file(self):
        self.api("sync")
        code, out, err = self.api("call", "exportReport", "-p", "reportId=R1")
        self.assertEqual(code, 0, err)
        result = json.loads(out)
        self.assertEqual(result["content_type"], "application/pdf")
        self.assertIsNone(result["body_preview"])
        self.assertNotIn("%PDF", out)
        path = result["body_written_to"]
        self.addCleanup(os.remove, path)
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
        self.assertEqual(self.tenant.calls_to("GET", "/api/reports/R1/export")[0].headers["Accept"],
                         "application/pdf")

    def test_transient_503_on_a_read_is_absorbed(self):
        self.api("sync")
        self.tenant.fail("GET", "/api/usergroups", status=503, times=2)
        code, out, err = self.api("call", "getUserGroups")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.tenant.count("GET", "/api/usergroups"), 3)

    def test_reused_session_spans_calls_until_logout(self):
        self.api("sync")
        for _ in range(3):
            code, _, err = self.api("call", "getUserGroups", "--reuse-session")
            self.assertEqual(code, 0, err)
        self.assertEqual(self.tenant.count("POST", "/api/auth/login"), 1)
        self.assertEqual(self.tenant.open_sessions, 1)
        code, out, _ = self.auth("logout")
        self.assertEqual(json.loads(out)["reused_sessions_ended"], ["password"])
        self.assertEqual(self.tenant.open_sessions, 0)

    def test_expired_reused_session_is_replaced(self):
        self.api("sync")
        self.api("call", "getUserGroups", "--reuse-session")
        self.tenant.state.sessions.clear()          # the server timed the session out
        code, _, err = self.api("call", "getUserGroups", "--reuse-session")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.tenant.count("POST", "/api/auth/login"), 2)


class BaseClientTests(TenantTestCase):
    def client(self):
        c = _client.BaseMSTR(self.tenant.base, "alice", PASSWORD, 1, "tutorial")
        c.login()
        self.addCleanup(c.logout)
        return c

    def test_project_resolution_and_logout(self):
        c = self.client()
        self.assertEqual(c.resolve_project()["id"], fake_tenant.PROJECT_ID)
        c.logout()
        self.assertEqual(self.tenant.open_sessions, 0)

    def test_search_paging_stops_at_total_items(self):
        self.tenant.state.search_items = [{"id": f"O{i}", "name": f"obj {i}"} for i in range(1000)]
        rows = self.client().search_results("obj", limit=200)
        self.assertEqual(len(rows), 1000)
        self.assertEqual(self.tenant.count("GET", "/api/searches/results"), 5)   # no trailing empty page

    def test_search_paging_survives_a_server_that_ignores_offset(self):
        @self.tenant.route("GET", r"/api/searches/results")
        def same_page(call, m):
            return 200, {"result": [{"id": f"O{i}"} for i in range(50)]}, {}
        rows = self.client().search_results("obj", limit=50)
        self.assertEqual(len(rows), 50)
        self.assertEqual(self.tenant.count("GET", "/api/searches/results"), 2)

    def test_http_errors_raise_with_the_status(self):
        c = self.client()
        with self.assertRaisesRegex(RuntimeError, "404"):
            c.request("GET", "/api/nothing-here", project=False)
        self.assertIsNone(c.try_request("GET", "/api/nothing-here", project=False))


if __name__ == "__main__":
    unittest.main()
