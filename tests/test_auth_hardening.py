"""strategy_auth hardening from the round-2 review: locked file store, strict base URLs,
per-token reuse slots, cached sessions that survive a server hiccup."""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _hermetic  # noqa: E402,F401  (scrub MSTR_*/proxy env, private secret store)

import json
import os
import sys
import tempfile
import threading
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "strategy-platform", "scripts"))

import strategy_auth as sa  # noqa: E402


class _Resp:
    def __init__(self, status):
        self.status_code = status


class _Session:
    def __init__(self, status):
        self.status, self.headers, self.cookies = status, {}, _Jar()

    def get(self, url, **kw):
        if isinstance(self.status, Exception):
            raise self.status
        return _Resp(self.status)


class _Jar(list):
    def set(self, *a, **kw):
        pass

    def clear(self):
        pass


class StoreTestCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        patcher = mock.patch.dict(os.environ, {"MSTR_SECRET_STORE": "file", "XDG_CONFIG_HOME": tmp.name})
        patcher.start()
        self.addCleanup(patcher.stop)


class FileStoreTests(StoreTestCase):
    def test_parallel_writers_do_not_lose_entries(self):
        def writer(n):
            for i in range(40):
                self.assertTrue(sa.secret_set(f"k{n}-{i}", "v"))

        threads = [threading.Thread(target=writer, args=(n,)) for n in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(sa._read_file_store()), 200)

    def test_no_temp_files_are_left_behind(self):
        sa.secret_set("a", "1")
        sa.secret_delete("a")
        folder = os.path.dirname(sa._secrets_file())
        self.assertEqual(sorted(f for f in os.listdir(folder) if f.endswith(".tmp")), [])
        self.assertEqual(os.stat(sa._secrets_file()).st_mode & 0o777, 0o600)

    def test_corrupt_store_reads_as_empty(self):
        sa.secret_set("a", "1")
        with open(sa._secrets_file(), "w") as f:
            f.write("{not json")
        self.assertIsNone(sa.secret_get("a"))
        self.assertTrue(sa.secret_set("b", "2"))   # and recovers on the next write
        self.assertEqual(sa.secret_get("b"), "2")


class KeychainArgvTests(unittest.TestCase):
    def test_secret_never_appears_in_any_argv(self):
        calls = []

        def fake_run(argv, **kw):
            calls.append((argv, kw.get("input")))
            if argv[:2] == ["security", "find-generic-password"]:
                import base64
                return mock.Mock(returncode=0, stdout=base64.b64encode(b"s3cret").decode())
            return mock.Mock(returncode=0, stdout="")

        with mock.patch.dict(os.environ, {"MSTR_SECRET_STORE": "keychain"}), \
                mock.patch.object(sa.subprocess, "run", fake_run):
            self.assertTrue(sa.secret_set("session:https://h.example", "s3cret"))
            self.assertFalse(sa.secret_set('bad"account', "s3cret"))   # would break out of the quoted argument
        for argv, stdin in calls:
            self.assertNotIn("s3cret", " ".join(argv))
        self.assertTrue(any(stdin and "add-generic-password" in stdin for _, stdin in calls))


class BaseUrlTests(unittest.TestCase):
    def test_header_and_csp_breaking_characters_are_refused(self):
        for base in ("https://tenant.example.com;report-uri https://evil 'self'/MicroStrategyLibrary",
                     "https://tenant.example.com:abc/MicroStrategyLibrary",
                     'https://tenant.example.com"/MicroStrategyLibrary',
                     "https://tenant example.com/MicroStrategyLibrary",
                     "ftp://tenant.example.com/MicroStrategyLibrary",
                     "https://user:pw@tenant.example.com/MicroStrategyLibrary"):
            with self.assertRaises(sa.AuthError, msg=base):
                sa.check_base(base)

    def test_ordinary_hosts_pass(self):
        for base in ("https://tenant.example.com/MicroStrategyLibrary", "https://under_score.example.com/x",
                     "https://10.1.2.3:8443/MicroStrategyLibrary", "http://localhost:8080/MicroStrategyLibrary",
                     "http://[::1]:8080/MicroStrategyLibrary"):
            sa.check_base(base)


class ReuseSlotTests(StoreTestCase):
    def cfg(self, **kw):
        with mock.patch.dict(os.environ, {k: v for k, v in os.environ.items() if not k.startswith("MSTR_")},
                             clear=True):
            return sa.AuthConfig.from_env(base="https://h.example/MicroStrategyLibrary", **kw)

    def test_each_api_token_gets_its_own_slot(self):
        a = sa._reuse_account(self.cfg(api_token="token-A"), "api-token")
        b = sa._reuse_account(self.cfg(api_token="token-B"), "api-token")
        self.assertNotEqual(a, b)
        self.assertNotIn("token-A", a)   # the slot name never carries the token itself

    def test_password_slots_are_per_user(self):
        self.assertNotEqual(sa._reuse_account(self.cfg(username="Ann"), "password"),
                            sa._reuse_account(self.cfg(username="bob"), "password"))


class CachedSessionProbeTests(StoreTestCase):
    def setUp(self):
        super().setUp()
        sa.secret_set("session:https://h.example", json.dumps({"token": "T", "cookies": []}))

    def test_server_hiccup_keeps_the_cache(self):
        for status in (503, 500, Exception("connection reset")):
            self.assertIsNone(sa.load_cached_session(_Session(status), "https://h.example"))
            self.assertIsNotNone(sa.secret_get("session:https://h.example"), status)

    def test_expired_session_is_forgotten(self):
        self.assertIsNone(sa.load_cached_session(_Session(401), "https://h.example"))
        self.assertIsNone(sa.secret_get("session:https://h.example"))

    def test_live_session_is_restored(self):
        s = _Session(200)
        self.assertIsNotNone(sa.load_cached_session(s, "https://h.example"))
        self.assertEqual(s.headers["X-MSTR-AuthToken"], "T")


class HeadlessAutoTests(StoreTestCase):
    def cfg(self, **kw):
        return sa.AuthConfig.from_env(base="https://h.example/MicroStrategyLibrary", **kw)

    def test_auto_fails_fast_where_no_browser_can_answer(self):
        for env in ({"CI": "true"}, {"MSTR_NO_BROWSER": "1"}):
            with mock.patch.dict(os.environ, env), mock.patch.object(sa, "browser_sso") as browser:
                with self.assertRaisesRegex(sa.AuthError, "no credentials"):
                    sa.sign_in(object(), self.cfg())
                browser.assert_not_called()

    def test_explicit_sso_still_opens_the_browser(self):
        with mock.patch.dict(os.environ, {"CI": "true"}), \
                mock.patch.object(sa, "browser_sso", side_effect=sa.AuthError("cancelled")) as browser:
            with self.assertRaisesRegex(sa.AuthError, "cancelled"):
                sa.sign_in(object(), self.cfg(method="sso"))
            browser.assert_called_once()

    def test_login_mode_4096_takes_the_token_from_the_user_field(self):
        seen = {}
        with mock.patch.object(sa, "_login", lambda s, base, body: seen.update(body)):
            sa.sign_in(object(), self.cfg(username="tok-123", login_mode=4096))
        self.assertEqual(seen, {"loginMode": 4096, "username": "tok-123"})


class HttpStackTests(unittest.TestCase):
    def test_old_libraries_are_flagged_current_ones_are_not(self):
        import urllib3
        for version, flagged in (("1.26.11", True), ("2.6.3", False), ("2.8.0", False)):
            warnings = []
            with mock.patch.object(urllib3, "__version__", version), \
                    mock.patch.object(sa.requests, "__version__", "2.34.2"):
                stack = sa.http_stack(warnings)
            self.assertEqual(stack["urllib3"], version)
            self.assertEqual(bool(warnings), flagged, version)


if __name__ == "__main__":
    unittest.main()
