"""SafeSession against real sockets: retries only where repeating is safe, default timeouts,
and Strategy tokens never following a redirect to another origin."""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _hermetic  # noqa: E402,F401  (scrub MSTR_*/proxy env, private secret store)

import http.server
import json
import os
import sys
import threading
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(ROOT, "skills", "strategy-platform", "scripts"))

import requests  # noqa: E402

import strategy_auth as sa  # noqa: E402


class _Server:
    """A loopback HTTP server whose behaviour is chosen per path:
    /flaky/N   -> 503 for the first N hits, then 200
    /down      -> always 503
    /slow      -> sleeps 0.8 s before answering
    /redirect?to=URL -> 302 to URL
    anything else -> 200 echoing the request headers
    """

    def __init__(self):
        self.hits: dict = {}
        self.headers_seen: list = []
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _answer(self):
                path = self.path.split("?")[0]
                outer.hits[path] = outer.hits.get(path, 0) + 1
                outer.headers_seen.append(dict(self.headers))
                length = int(self.headers.get("Content-Length") or 0)
                if length:
                    self.rfile.read(length)
                if path.startswith("/flaky/"):
                    status = 503 if outer.hits[path] <= int(path.rsplit("/", 1)[1]) else 200
                elif path == "/down":
                    status = 503
                elif path == "/slow":
                    time.sleep(0.8)
                    status = 200
                elif path == "/redirect":
                    target = self.path.split("to=", 1)[1]
                    self.send_response(302)
                    self.send_header("Location", target)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                else:
                    status = 200
                body = json.dumps({"path": path, "hit": outer.hits[path]}).encode()
                try:
                    self.send_response(status)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                except OSError:
                    pass   # the client gave up (read-timeout test)

            do_GET = do_POST = do_HEAD = _answer

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.httpd.daemon_threads = True
        self.url = "http://127.0.0.1:%d" % self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": 0.05},
                                       daemon=True)
        self.thread.start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


class RetryPolicyTests(unittest.TestCase):
    def setUp(self):
        self.server = _Server()
        self.addCleanup(self.server.close)
        self.session = sa.SafeSession(retries=2)
        self.addCleanup(self.session.close)

    def test_get_is_retried_through_transient_503(self):
        r = self.session.get(self.server.url + "/flaky/2", timeout=5)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.server.hits["/flaky/2"], 3)

    def test_exhausted_retries_return_the_last_response(self):
        r = self.session.get(self.server.url + "/down", timeout=5)
        self.assertEqual(r.status_code, 503)        # no exception: callers handle the status
        self.assertEqual(self.server.hits["/down"], 3)

    def test_writes_that_reached_the_server_are_not_repeated(self):
        r = self.session.post(self.server.url + "/flaky/1", json={"x": 1}, timeout=5)
        self.assertEqual(r.status_code, 503)
        self.assertEqual(self.server.hits["/flaky/1"], 1)

    def test_read_timeouts_are_not_repeated_and_keep_their_type(self):
        with self.assertRaises(requests.ReadTimeout):
            self.session.get(self.server.url + "/slow", timeout=(2, 0.2))
        self.assertEqual(self.server.hits["/slow"], 1)

    def test_connection_refused_raises_connection_error(self):
        dead = sa.SafeSession(retries=1)
        self.addCleanup(dead.close)
        port = self.server.httpd.server_address[1]
        self.server.close()
        started = time.monotonic()
        with self.assertRaises(requests.ConnectionError):
            dead.get("http://127.0.0.1:%d/x" % port, timeout=2)
        self.assertLess(time.monotonic() - started, 5)
        self.server = _Server()   # cleanup closes this fresh one

    def test_retries_off_for_callers_with_their_own_loop(self):
        plain = sa.SafeSession(retries=0)
        self.addCleanup(plain.close)
        r = plain.get(self.server.url + "/flaky/1", timeout=5)
        self.assertEqual(r.status_code, 503)
        self.assertEqual(self.server.hits["/flaky/1"], 1)

    def test_env_sets_the_retry_budget(self):
        with mock.patch.dict(os.environ, {"MSTR_HTTP_RETRIES": "0"}):
            s = sa.SafeSession()
        self.addCleanup(s.close)
        self.assertEqual(s.get(self.server.url + "/flaky/1", timeout=5).status_code, 503)


class DefaultTimeoutTests(unittest.TestCase):
    def setUp(self):
        self.server = _Server()
        self.addCleanup(self.server.close)

    def test_default_read_timeout_applies_when_none_is_given(self):
        with mock.patch.dict(os.environ, {"MSTR_HTTP_TIMEOUT": "0.2"}):
            s = sa.SafeSession(retries=0)
            self.addCleanup(s.close)
            started = time.monotonic()
            with self.assertRaises(requests.ReadTimeout):
                s.get(self.server.url + "/slow")
            self.assertLess(time.monotonic() - started, 0.75)

    def test_explicit_timeout_wins(self):
        seen = []
        with mock.patch("requests.Session.request", lambda self, m, u, *a, **kw: seen.append(kw.get("timeout"))):
            s = sa.SafeSession(retries=0)
            s.get("https://x.example/api")
            s.get("https://x.example/api", timeout=5)
            s.request("GET", "https://x.example/api", timeout=None)
        self.assertEqual(seen[0], sa.http_timeout())
        self.assertEqual(seen[1], 5)
        self.assertEqual(seen[2], sa.http_timeout())   # None never means "wait forever"


class RedirectTokenTests(unittest.TestCase):
    def setUp(self):
        self.a, self.b = _Server(), _Server()
        self.addCleanup(self.a.close)
        self.addCleanup(self.b.close)
        self.session = sa.SafeSession(retries=0)
        self.addCleanup(self.session.close)
        self.session.headers.update({"X-MSTR-AuthToken": "tok-123", "X-MSTR-IdentityToken": "id-456"})

    def test_cross_origin_redirect_is_refused_before_anything_is_sent(self):
        # A 307 would resend the body (a password, an identity token) and dict cookies have no
        # domain, so stripping headers is not enough: the redirect is not followed at all.
        for verb, kw in (("GET", {"cookies": {"JSESSIONID": "jar-less"}}),
                         ("POST", {"json": {"username": "u", "password": "fake-pw-secret"}})):
            with self.assertRaises(sa.CrossOriginRedirect) as ctx:
                self.session.request(verb, self.a.url + "/redirect?to=" + self.b.url + "/landing", timeout=5, **kw)
            self.assertIn("point MSTR_BASE at it", str(ctx.exception))
        self.assertEqual(self.b.headers_seen, [])   # the other origin saw nothing
        self.assertTrue(issubclass(sa.CrossOriginRedirect, requests.RequestException))

    def test_scheme_change_counts_as_another_origin(self):
        self.assertFalse(sa.same_origin("https://h.example/a", "http://h.example/a"))
        self.assertFalse(sa.same_origin("http://h.example/a", "https://h.example/a"))
        self.assertTrue(sa.same_origin("https://h.example/a", "https://H.example:443/b"))
        self.assertFalse(sa.same_origin("https://h.example/a", "https://h.example:8443/a"))
        self.assertFalse(sa.same_origin("https://h.example/a", "https://u:p@h.example/a"))
        self.assertFalse(sa.same_origin("https://h.example/a", "https://h.example:x/a"))

    def test_same_origin_redirect_keeps_the_session(self):
        self.session.get(self.a.url + "/redirect?to=" + self.a.url + "/landing", timeout=5)
        self.assertEqual(self.a.headers_seen[-1].get("X-MSTR-AuthToken"), "tok-123")


if __name__ == "__main__":
    unittest.main()
