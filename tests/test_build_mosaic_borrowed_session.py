"""Tests for the borrowed-session auth path (Studio Cloud / SSO tenants).

When the caller supplies --auth-token (+ cookies) on the CLI, MSTR.login() must:
  - Skip POST /api/auth/login entirely (the caller's session was minted elsewhere).
  - Set X-MSTR-AuthToken on the session.
  - Set the JSESSIONID and library-ingress cookies on the session.
  - Skip DELETE /api/auth/login on logout — that would log the human's UI out.
  - Honor --identity-token verbatim when present; only attempt to mint when asked.

These tests stub out requests.Session so they assert on side effects without
hitting the network.
"""
import contextlib
import io
import os
import sys
import types
import unittest


ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(ROOT, "skills", "build-mosaic-model", "scripts"))

import build_mosaic as bm  # noqa: E402


class _FakeSession:
    """Minimal requests.Session double — captures call sites + headers + cookies."""

    def __init__(self):
        self.headers = {}
        self.cookies = _FakeCookieJar()
        self.calls = []  # list of (method, url, kwargs)

    def post(self, url, **kw):
        self.calls.append(("POST", url, kw))
        return _FakeResp(200)

    def delete(self, url, **kw):
        self.calls.append(("DELETE", url, kw))
        return _FakeResp(204)


class _FakeCookieJar:
    def __init__(self):
        self.entries = {}

    def set(self, name, value, **kw):
        self.entries[(name, kw.get("domain"))] = value


class _FakeResp:
    def __init__(self, status):
        self.ok = 200 <= status < 300
        self.status_code = status
        self.text = ""
        self.headers = {}

    def raise_for_status(self):
        if not self.ok:
            raise RuntimeError(f"HTTP {self.status_code}")


def _args(**overrides):
    """Build an argparse.Namespace-like object with sensible defaults."""
    defaults = dict(
        base="https://studio.example.com/MicroStrategyLibrary",
        project_id="ABCD" * 8,
        user="",
        password="",
        login_mode=1,
        verbose=False,
        auth_token="",
        identity_token="",
        session_cookie="",
        ingress_cookie="",
    )
    defaults.update(overrides)
    return types.SimpleNamespace(**defaults)


class BorrowedSessionAuthTests(unittest.TestCase):
    def test_login_with_auth_token_skips_post_auth_login(self):
        m = bm.MSTR(_args(auth_token="TOK123"))
        m.s = _FakeSession()
        m.login(identity=False)
        # No /api/auth/login POST should have happened.
        self.assertFalse(any("/api/auth/login" in url for _, url, _ in m.s.calls))
        # AuthToken header should be set.
        self.assertEqual(m.s.headers.get("X-MSTR-AuthToken"), "TOK123")
        self.assertTrue(m.borrowed_session)
        self.assertTrue(m.logged_in)

    def test_logout_does_not_call_delete_for_borrowed_session(self):
        m = bm.MSTR(_args(auth_token="TOK123"))
        m.s = _FakeSession()
        m.login(identity=False)
        m.logout()
        # No /api/auth/login DELETE.
        self.assertFalse(
            any(method == "DELETE" and "/api/auth/login" in url
                for method, url, _ in m.s.calls),
            "borrowed-session logout must NOT call DELETE /api/auth/login "
            "— it would log the external session owner out of their UI",
        )

    def test_cookies_set_on_session_when_provided(self):
        m = bm.MSTR(_args(
            auth_token="TOK",
            session_cookie="JSESSION_VAL",
            ingress_cookie="INGRESS_VAL",
        ))
        # The cookies were set in __init__ before our _FakeSession swap, so the
        # real requests.Session jar has them. Replace and check the jar.
        cookies = {(c.name, c.domain): c.value for c in m.s.cookies}
        self.assertIn(("JSESSIONID", "studio.example.com"), cookies)
        self.assertEqual(cookies[("JSESSIONID", "studio.example.com")], "JSESSION_VAL")
        self.assertIn(("library-ingress", "studio.example.com"), cookies)
        self.assertEqual(cookies[("library-ingress", "studio.example.com")], "INGRESS_VAL")

    def test_identity_token_used_verbatim_when_provided(self):
        m = bm.MSTR(_args(auth_token="TOK", identity_token="IDTOK"))
        m.s = _FakeSession()
        m.login(identity=True)
        # Should not attempt to mint when one is already given.
        self.assertFalse(any("/auth/identityToken" in url for _, url, _ in m.s.calls))
        self.assertEqual(m.s.headers.get("X-MSTR-IdentityToken"), "IDTOK")

    def test_direct_login_path_still_works_without_borrowed_token(self):
        # Sanity: when no auth-token is supplied, MSTR.login() falls through to
        # the standard username/password path. The fake response has no auth
        # header, so login() will die() — we only care that POST /api/auth/login
        # was attempted and that the borrowed branch wasn't taken.
        m = bm.MSTR(_args(user="alice", password="hunter2"))
        m.s = _FakeSession()
        try:
            # die() prints "FATAL: login: ..." to stderr before raising —
            # swallow it so the suite output stays clean.
            with contextlib.redirect_stderr(io.StringIO()):
                m.login(identity=False)
        except (Exception, SystemExit):
            pass  # die() raises SystemExit when there's no auth-token header
        self.assertFalse(m.borrowed_session)
        self.assertTrue(
            any("/api/auth/login" in url and method == "POST"
                for method, url, _ in m.s.calls),
            "non-borrowed login() should POST /api/auth/login",
        )


if __name__ == "__main__":
    unittest.main()
