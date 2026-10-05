"""strategy_library_publications.py (and its mstrio-py twin) against real sockets: the parallel
export's re-login, base-URL policy, retry pacing, connection pool, redirects and private files."""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _hermetic  # noqa: E402,F401  (scrub MSTR_*/proxy env, private secret store)

import contextlib
import csv
import datetime
import email.utils
import io
import json
import os
import stat
import sys
import tempfile
import threading
import time
import types
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "skills", "build-mosaic-model", "scripts"))
sys.path.insert(0, os.path.join(ROOT, "skills", "strategy-platform", "scripts"))

from fake_tenant import PROJECT_ID, FakeTenant  # noqa: E402

import strategy_auth  # noqa: E402
import strategy_library_publications as lp  # noqa: E402
import strategy_library_publications_mstrio as lpm  # noqa: E402

PASSWORD = "correct horse"
USER_ID = "1" * 32
DASHBOARD_VIEW_MEDIA = 0x60000000


def private(path):
    return stat.S_IMODE(os.stat(path).st_mode) == 0o600


class LibraryTenant:
    """Routes the export needs on top of fake_tenant's sign-in: metadata search, Library
    recipients and object ancestors. `expire_on` ends the caller's session at that /api/library
    call, as a server-side timeout would."""

    def __init__(self, tenant, n_objects=40, expire_on=None):
        self.tenant, self.lock, self.library_calls = tenant, threading.Lock(), 0
        self.objects = [{"id": "%032X" % (0xD000 + i), "name": "Dash %02d" % i, "type": 55,
                         "subtype": 14081, "viewMedia": DASHBOARD_VIEW_MEDIA} for i in range(n_objects)]

        def authed(fn):
            def wrapper(call, m):
                if tenant._user(call) is None:
                    return 401, {"code": "ERR009", "message": "The user's session has expired"}, {}
                return fn(call, m)
            return wrapper

        @tenant.route("POST", r"/api/metadataSearches/results")
        @authed
        def start_search(call, m):
            return 200, {"id": "SEARCH1", "totalItems": len(self.objects)}, {}

        @tenant.route("GET", r"/api/metadataSearches/results")
        @authed
        def search_page(call, m):
            offset, limit = int(call.query.get("offset") or 0), int(call.query.get("limit") or 50)
            return 200, {"result": self.objects[offset:offset + limit]}, {}

        @tenant.route("GET", r"/api/library/(\w+)")
        def library(call, m):
            with self.lock:
                self.library_calls += 1
                if self.library_calls == expire_on:
                    tenant.state.sessions.pop(call.headers.get("X-MSTR-AuthToken", ""), None)
            if tenant._user(call) is None:
                return 401, {"code": "ERR009", "message": "The user's session has expired"}, {}
            return 200, {"id": m.group(1), "recipients": [{"id": USER_ID, "name": "Analyst", "subtype": 8704}]}, {}

        @tenant.route("GET", r"/api/objects/(\w+)")
        @authed
        def get_object(call, m):
            return 200, {"id": m.group(1), "ancestors": [{"name": "Tutorial", "level": 2},
                                                         {"name": "Shared Reports", "level": 1}]}, {}


class TenantCase(unittest.TestCase):
    def setUp(self):
        self.tenant = FakeTenant()
        self.addCleanup(self.tenant.close)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = tmp.name
        env = mock.patch.dict(os.environ, {"MSTR_BASE": self.tenant.base, "MSTR_USER": "alice",
                                           "MSTR_PASSWORD": PASSWORD, "MSTR_HTTP_TIMEOUT": "10"})
        env.start()
        self.addCleanup(env.stop)

    def run_main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = lp.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def client(self, **kw):
        return lp.Client(self.tenant.base, "alice", PASSWORD, **kw)


class ParallelExportTests(TenantCase):
    def test_session_expiry_mid_export_costs_one_relogin_and_loses_nothing(self):
        lib = LibraryTenant(self.tenant, n_objects=40, expire_on=10)
        out = os.path.join(self.tmp, "map.csv")
        code, stdout, stderr = self.run_main("export", "--project", "Tutorial", "--types", "dashboards",
                                             "--workers", "8", "--skip-content-groups", "--out", out)
        self.assertEqual(code, lp.EXIT_OK, stderr)
        self.assertEqual(self.tenant.count("POST", r"/api/auth/login"), 2)      # first + one re-login
        self.assertEqual(stderr.count("session expired, logging in again"), 1)
        self.assertEqual(self.tenant.open_sessions, 0)                          # the new one logged out
        with open(out, encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
        self.assertEqual(sorted(r["document_id"] for r in rows), sorted(o["id"] for o in lib.objects))
        self.assertEqual({r["folder_path"] for r in rows}, {"Shared Reports"})  # parallel path lookups
        self.assertEqual(self.tenant.count("GET", r"/api/objects/\w+"), 40)
        if os.name == "posix":
            self.assertTrue(private(out) and private(out[:-4] + ".json"))
        with open(out[:-4] + ".json", encoding="utf-8") as f:
            exported = json.load(f)
        self.assertEqual(exported["base_url"], self.tenant.base)                 # schema unchanged
        self.assertEqual(exported["exported_by"], "Alice Example")

    def test_relogin_swaps_sessions_instead_of_modifying_one_in_use(self):
        LibraryTenant(self.tenant)
        c = self.client(pool_size=8)
        c.login()
        first = c.session
        before = dict(first.headers)
        c.login()
        self.assertIsNot(c.session, first)
        self.assertEqual(dict(first.headers), before)       # never touched after it was published

        errors, statuses, stop = [], [], threading.Event()

        def worker():
            while not stop.is_set():
                try:
                    statuses.append(c.request("GET", "/api/sessions/userInfo").status_code)
                except Exception as e:   # the old in-place re-login raised RuntimeError / KeyError here
                    errors.append(repr(e))

        threads = [threading.Thread(target=worker) for _ in range(6)]
        for t in threads:
            t.start()
        for _ in range(15):
            c.login()
            time.sleep(0.01)
        stop.set()
        for t in threads:
            t.join(10)
        c.logout()
        self.assertEqual(errors, [])
        self.assertTrue(statuses and set(statuses) == {200})


class BaseUrlPolicyTests(TenantCase):
    def refused(self, base):
        with mock.patch.object(strategy_auth.SafeSession, "request",
                               side_effect=AssertionError("no request may be sent")):
            with contextlib.redirect_stderr(io.StringIO()) as err, self.assertRaises(SystemExit) as cm:
                lp.main(["export", "--project", "P", "--base-url", base, "--username", "u"])
        self.assertEqual(cm.exception.code, 2)
        return err.getvalue()

    def test_cleartext_and_credential_urls_are_refused_before_any_request(self):
        self.assertIn("plain http", self.refused("http://tenant.invalid/MicroStrategyLibrary"))
        self.assertIn("credentials", self.refused("https://u:p@tenant.invalid/MicroStrategyLibrary"))

    def test_lab_override_and_localhost_are_allowed(self):
        with mock.patch.dict(os.environ, {"MSTR_ALLOW_HTTP": "1"}):
            lp.Client("http://lab.invalid/MicroStrategyLibrary").logout()
        lp.Client(self.tenant.base).logout()


class RetryPacingTests(TenantCase):
    def test_retry_after_is_honoured_jittered_and_capped(self):
        for _ in range(50):
            self.assertTrue(7 <= lp._retry_delay(0, "7") <= 8)
            self.assertEqual(lp._retry_delay(0, "120"), lp.MAX_BACKOFF)
            self.assertTrue(1 <= lp._retry_delay(0) <= 2)
            self.assertTrue(8 <= lp._retry_delay(3) <= 16)
            self.assertTrue(15 <= lp._retry_delay(9) <= lp.MAX_BACKOFF)
            self.assertTrue(1 <= lp._retry_delay(0, "soon") <= 2)          # unparsable: backoff
        when = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=5)
        self.assertTrue(3 <= lp._retry_delay(0, email.utils.format_datetime(when, usegmt=True)) <= 6.5)
        spread = {round(lp._retry_delay(2), 3) for _ in range(20)}
        self.assertGreater(len(spread), 1)                                     # jitter, not lockstep

    def test_a_429_waits_for_the_servers_retry_after(self):
        hits = []

        @self.tenant.route("GET", r"/api/projects")
        def throttled(call, m):
            hits.append(1)
            if len(hits) == 1:
                return 429, {"code": "ERR_THROTTLED", "message": "slow down"}, {"Retry-After": "2"}
            return 200, [{"id": PROJECT_ID, "name": "Tutorial"}], {}

        c = self.client()
        c.login()
        slept = []
        with mock.patch.object(lp.time, "sleep", slept.append), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(c.get_json("/api/projects")[0]["id"], PROJECT_ID)
        c.logout()
        self.assertEqual(len(hits), 2)
        self.assertEqual(len(slept), 1)
        self.assertTrue(2 <= slept[0] <= 3)


class TransportTests(TenantCase):
    def test_pool_holds_a_connection_per_worker(self):
        c = self.client(pool_size=32)
        self.assertEqual(c.session.get_adapter(self.tenant.base)._pool_maxsize, 32)
        c.login()                                           # the swapped-in session too
        self.assertEqual(c.session.get_adapter(self.tenant.base)._pool_maxsize, 32)
        c.logout()
        self.assertEqual(lp.Client(self.tenant.base, pool_size=1).session.get_adapter(self.tenant.base)._pool_maxsize, 10)

    def test_redirect_to_another_origin_is_final(self):
        @self.tenant.route("GET", r"/api/projects")
        def bounce(call, m):
            port = self.tenant.httpd.server_address[1]
            return 302, None, {"Location": f"http://localhost:{port}/elsewhere"}

        c = self.client()
        c.login()
        with self.assertRaises(lp.ApiError) as cm:
            c.request("GET", "/api/projects")
        c.logout()
        self.assertIn("CrossOriginRedirect", str(cm.exception))
        self.assertEqual(self.tenant.count("GET", r"/api/projects"), 1)          # not retried
        self.assertEqual(self.tenant.count("GET", r"/elsewhere"), 0)

    @unittest.skipUnless(os.name == "posix", "file modes")
    def test_csv_over_an_existing_readable_file_becomes_private(self):
        path = os.path.join(self.tmp, "old.csv")
        with open(path, "w") as f:
            f.write("old")
        os.chmod(path, 0o644)
        lp.write_csv(path, ["a"], [{"a": "=1"}])
        self.assertTrue(private(path))
        with open(path, encoding="utf-8-sig") as f:
            self.assertEqual(f.read().splitlines(), ["a", "'=1"])


class FakeResponse:
    def __init__(self, status, body):
        self.status_code, self._body = status, body
        self.text = json.dumps(body)

    def json(self):
        return self._body


class MstrioVariantTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = tmp.name

    def test_missing_or_old_mstrio_is_a_clear_usage_failure(self):
        err = io.StringIO()
        with mock.patch.dict(sys.modules, {"mstrio": None}), contextlib.redirect_stderr(err):
            code = lpm.main(["export", "--project", "P"])
        self.assertEqual(code, 2)
        self.assertIn("FATAL: needs mstrio-py >= %s" % lpm.MIN_MSTRIO, err.getvalue())

    def test_bad_types_fail_before_mstrio_or_sign_in(self):
        with mock.patch.object(lpm, "load_mstrio", side_effect=AssertionError("not reached")), \
                contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as cm:
            lpm.main(["export", "--project", "P", "--types", "bogus"])
        self.assertEqual(cm.exception.code, 2)

    def test_cleartext_base_is_refused_before_connecting(self):
        made = []
        ms = types.SimpleNamespace(Connection=lambda *a, **k: made.append(a))
        with mock.patch.dict(os.environ, {"MSTR_BASE": "http://tenant.invalid/MicroStrategyLibrary",
                                          "MSTR_USER": "u", "MSTR_PASSWORD": "p"}):
            with self.assertRaises(SystemExit) as cm:
                lpm.connect(ms)
        self.assertIn("plain http", str(cm.exception.code))
        self.assertEqual(made, [])

    def test_export_csv_is_private_and_interchangeable(self):
        dash = "D" * 32

        class Conn:
            def get(self, endpoint, headers=None, params=None):
                if endpoint == "/api/projects":
                    return FakeResponse(200, [{"id": PROJECT_ID, "name": "Tutorial"}])
                return FakeResponse(200, {"recipients": [{"id": USER_ID, "name": "=Analyst", "subtype": 8704}]})

        ms = types.SimpleNamespace(list_dashboards=lambda conn, **kw: [{"id": dash, "name": "D", "subtype": 14081}])
        out = os.path.join(self.tmp, "m.csv")
        args = types.SimpleNamespace(project="Tutorial", types="dashboards", out=out, by_recipient=False)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(lpm.cmd_export(Conn(), args, ms), 0)
        if os.name == "posix":
            self.assertTrue(private(out))
        _src, objects, problems = lp.load_mapping(out)          # the requests script reads it back
        self.assertEqual(problems, [])
        self.assertEqual(objects[dash]["recipients"][USER_ID]["name"], "=Analyst")


class RecipientPayloadTests(unittest.TestCase):
    def test_a_non_object_payload_is_an_error_not_a_crash(self):
        class Resp:
            status_code = 200

            def json(self):
                return ["not", "an", "object"]

        class Client:
            def request(self, *a, **kw):
                return Resp()

        recipients, error = lp.get_recipients(Client(), PROJECT_ID, "O1")
        self.assertIsNone(recipients)
        self.assertIn("expected a JSON object", error)


if __name__ == "__main__":
    unittest.main()
