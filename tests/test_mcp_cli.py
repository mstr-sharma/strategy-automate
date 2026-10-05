"""strategy_mcp.py's command line end to end against a loopback MCP server + OAuth authorization
server: discovery, cached and refreshed tokens, tools/call/query, logout with revocation, and
clean failures. (The browser login itself is covered by the loopback tests in test_strategy_auth.)"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _hermetic  # noqa: E402,F401  (scrub MSTR_*/proxy env, private secret store)

import contextlib
import http.server
import io
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "strategy-platform", "scripts"))

import strategy_mcp as sm  # noqa: E402

REDIRECT = "http://127.0.0.1:8753/oauth/callback"


class FakeMcpTenant:
    def __init__(self):
        self.calls = []
        self.valid = {"A1"}
        self.refreshes = 0
        self.revoked = []
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, status, body=None, headers=None, ctype="application/json"):
                payload = b"" if body is None else json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(payload)))
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(payload)

            def do_GET(self):
                outer.calls.append(("GET", self.path))
                if self.path == "/.well-known/oauth-protected-resource/collaboration/mcp/mosaic":
                    return self._send(200, {"resource": outer.mcp_url, "authorization_servers": [outer.issuer]})
                if self.path == "/.well-known/oauth-authorization-server/collaboration":
                    return self._send(200, {"issuer": outer.issuer,
                                            "authorization_endpoint": outer.issuer + "/authorize",
                                            "token_endpoint": outer.issuer + "/token",
                                            "registration_endpoint": outer.issuer + "/register",
                                            "revocation_endpoint": outer.issuer + "/revoke"})
                return self._send(404, {})

            def do_POST(self):
                raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                outer.calls.append(("POST", self.path))
                if self.path == "/collaboration/token":
                    form = dict(p.split("=", 1) for p in raw.decode().split("&"))
                    if form.get("grant_type") == "refresh_token" and form.get("refresh_token") == "R1":
                        outer.refreshes += 1
                        outer.valid.add("A2")
                        return self._send(200, {"access_token": "A2", "expires_in": 600})
                    return self._send(400, {"error": "invalid_grant"})
                if self.path == "/collaboration/revoke":
                    outer.revoked.append(raw.decode())
                    return self._send(200, {})
                if self.path != "/collaboration/mcp/mosaic":
                    return self._send(404, {})
                token = (self.headers.get("Authorization") or "").replace("Bearer ", "")
                if token not in outer.valid:
                    return self._send(401, {}, {"WWW-Authenticate": 'Bearer resource_metadata="%s"' % (
                        outer.root + "/.well-known/oauth-protected-resource/collaboration/mcp/mosaic")})
                msg = json.loads(raw)
                if "id" not in msg:
                    return self._send(202)
                if msg["method"] == "initialize":
                    result = {"protocolVersion": sm.PROTOCOL_VERSION, "capabilities": {}}
                elif msg["method"] == "tools/list":
                    result = {"tools": [{"name": "query", "description": "run SQL",
                                         "inputSchema": {"properties": {"project": {}, "query": {}}}}]}
                else:
                    args = msg["params"]["arguments"]
                    result = {"content": [{"type": "text", "text": "rows for " + json.dumps(args, sort_keys=True)}]}
                self._send(200, {"jsonrpc": "2.0", "id": msg["id"], "result": result}, {"Mcp-Session-Id": "S1"})

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.httpd.daemon_threads = True
        self.root = "http://127.0.0.1:%d" % self.httpd.server_address[1]
        self.base = self.root + "/MicroStrategyLibrary"
        self.mcp_url = self.root + "/collaboration/mcp/mosaic"
        self.issuer = self.root + "/collaboration"
        threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


class McpCliTests(unittest.TestCase):
    def setUp(self):
        self.tenant = FakeMcpTenant()
        self.addCleanup(self.tenant.close)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        patcher = mock.patch.dict(os.environ, {"MSTR_BASE": self.tenant.base, "XDG_CONFIG_HOME": tmp.name})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.store = sm.Tokens(self.tenant.mcp_url, REDIRECT, self.tenant.issuer)
        self.store.save_client({"client_id": "CID", "client_secret": "CS"})

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), \
                mock.patch.object(sm, "login", side_effect=AssertionError("no browser in tests")):
            code = sm.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_tools_with_a_cached_token(self):
        self.store.save_tokens({"access_token": "A1", "refresh_token": "R1", "expires_in": 600})
        code, out, err = self.run_cli("tools")
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out), [{"name": "query", "description": "run SQL",
                                            "arguments": ["project", "query"]}])
        self.assertNotIn("A1", out + err)

    def test_query_and_call(self):
        self.store.save_tokens({"access_token": "A1", "refresh_token": "R1", "expires_in": 600})
        code, out, _ = self.run_cli("query", "--project", "P", "--sql", "SELECT 1 LIMIT 1")
        self.assertEqual((code, out.strip()), (0, 'rows for {"project": "P", "query": "SELECT 1 LIMIT 1"}'))
        code, out, _ = self.run_cli("call", "get_models", "--args", '{"project": "P"}')
        self.assertEqual(code, 0)

    def test_expired_token_is_refreshed_without_a_browser(self):
        self.store.save_tokens({"access_token": "OLD", "refresh_token": "R1", "expires_at": time.time() - 10})
        code, out, err = self.run_cli("tools")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.tenant.refreshes, 1)
        self.assertEqual(self.store.tokens()["access_token"], "A2")

    def test_bad_arguments_and_network_failures_are_clean(self):
        self.store.save_tokens({"access_token": "A1", "refresh_token": "R1", "expires_in": 600})
        code, _, err = self.run_cli("call", "query", "--args", "{not json")
        self.assertEqual(code, 2)
        self.assertIn("--args is not valid JSON", err)
        self.tenant.close()
        code, _, err = self.run_cli("tools")
        self.assertEqual(code, 2)
        self.assertIn("FATAL", err)

    def test_logout_revokes_and_forgets(self):
        self.store.save_tokens({"access_token": "A1", "refresh_token": "R1", "expires_in": 600})
        code, out, _ = self.run_cli("logout")
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(out)["revoked"])
        self.assertIn("token=R1", self.tenant.revoked[0])
        self.assertIsNone(self.store.tokens())
        self.assertIsNone(self.store.client())

    def test_logout_forgets_even_when_revocation_fails(self):
        self.store.save_tokens({"access_token": "A1", "refresh_token": "R1", "expires_in": 600})
        with mock.patch.object(sm.sa.SafeSession, "post", side_effect=sm.requests.ConnectionError("down")):
            code, out, _ = self.run_cli("logout")
        self.assertEqual(code, 0)
        self.assertFalse(json.loads(out)["revoked"])
        self.assertIsNone(self.store.tokens())


if __name__ == "__main__":
    unittest.main()
