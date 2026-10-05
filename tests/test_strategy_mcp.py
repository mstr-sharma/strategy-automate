import json
import os
import sys
import tempfile
import time
import unittest
import urllib.parse
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(ROOT, "skills", "build-mosaic-model", "scripts"))

from requests.structures import CaseInsensitiveDict  # noqa: E402

import strategy_auth as sa  # noqa: E402
import strategy_mcp as sm  # noqa: E402

HOST = "https://tenant.example.com"
RESOURCE = f"{HOST}/collaboration/mcp/agent"
ISSUER = f"{HOST}/collaboration"
META = {"issuer": ISSUER, "authorization_endpoint": f"{ISSUER}/authorize", "token_endpoint": f"{ISSUER}/token",
        "registration_endpoint": f"{ISSUER}/register", "revocation_endpoint": f"{ISSUER}/revoke"}


class Resp:
    def __init__(self, status=200, body=None, headers=None, lines=None):
        self.status_code, self.ok = status, 200 <= status < 300
        self._body, self._lines = body, lines
        self.headers = CaseInsensitiveDict(headers or {"Content-Type": "application/json"})
        self.closed = False

    def json(self):
        if self._body is None:
            raise ValueError("empty")
        return self._body

    def iter_lines(self, decode_unicode=False):
        yield from self._lines or []

    def close(self):
        self.closed = True


class FakeHttp:
    def __init__(self):
        self.calls = []
        self.handlers = {}

    def on(self, verb, url, fn):
        self.handlers[(verb, url)] = fn

    def _do(self, verb, url, **kw):
        self.calls.append((verb, url, kw))
        fn = self.handlers.get((verb, url))
        return fn(**kw) if fn else Resp(404, {})

    def get(self, url, **kw):
        return self._do("GET", url, **kw)

    def post(self, url, **kw):
        return self._do("POST", url, **kw)


def cfg():
    with mock.patch.dict(os.environ, {}, clear=True):
        return sa.AuthConfig.from_env(base=f"{HOST}/MicroStrategyLibrary")


class McpTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"MSTR_SECRET_STORE": "file", "XDG_CONFIG_HOME": self.tmp.name})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()


class DiscoveryTests(McpTestCase):
    def test_discover_from_library_base(self):
        http = FakeHttp()
        http.on("GET", f"{HOST}/.well-known/oauth-protected-resource",
                lambda **kw: Resp(body={"resource": RESOURCE, "authorization_servers": [ISSUER]}))
        http.on("GET", f"{HOST}/.well-known/oauth-authorization-server/collaboration", lambda **kw: Resp(body=META))
        meta = sm.discover(http, base=f"{HOST}/MicroStrategyLibrary")
        self.assertEqual((meta["resource"], meta["token_endpoint"]), (RESOURCE, META["token_endpoint"]))

    def test_issuer_mismatch_is_rejected(self):
        http = FakeHttp()
        http.on("GET", f"{HOST}/.well-known/oauth-protected-resource",
                lambda **kw: Resp(body={"resource": RESOURCE, "authorization_servers": [ISSUER]}))
        http.on("GET", f"{HOST}/.well-known/oauth-authorization-server/collaboration",
                lambda **kw: Resp(body=dict(META, issuer="https://elsewhere.example")))
        with self.assertRaises(sm.McpError):
            sm.discover(http, base=f"{HOST}/MicroStrategyLibrary")

    def test_authorize_url_carries_pkce_resource_and_scopes(self):
        url = sm.authorize_url(dict(META, resource=RESOURCE), "CID", "http://127.0.0.1:8753/oauth/callback",
                               "STATE", "CHALLENGE")
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
        self.assertEqual((q["code_challenge_method"], q["code_challenge"], q["resource"]), ("S256", "CHALLENGE", RESOURCE))
        self.assertIn("offline_access", q["scope"])
        self.assertIn("mcp:stream", q["scope"])


class TokenTests(McpTestCase):
    def setUp(self):
        super().setUp()
        self.meta = dict(META, resource=RESOURCE)
        self.store = sm.Tokens(RESOURCE, "http://127.0.0.1:8753/oauth/callback")
        self.store.save_client({"client_id": "CID", "client_secret": "CS"})

    def test_cached_token_is_reused(self):
        self.store.save_tokens({"access_token": "A1", "refresh_token": "R1", "expires_in": 3600})
        self.assertEqual(sm.access_token(FakeHttp(), self.meta, cfg()), "A1")

    def test_expired_token_is_refreshed_with_client_secret_and_resource(self):
        self.store.save_tokens({"access_token": "A0", "refresh_token": "R1", "expires_at": time.time() - 5})
        http = FakeHttp()
        http.on("POST", META["token_endpoint"], lambda **kw: Resp(body={"access_token": "A2", "expires_in": 60}))
        self.assertEqual(sm.access_token(http, self.meta, cfg()), "A2")
        form = http.calls[0][2]["data"]
        self.assertEqual((form["grant_type"], form["refresh_token"], form["client_secret"], form["resource"]),
                         ("refresh_token", "R1", "CS", RESOURCE))
        self.assertEqual(self.store.tokens()["refresh_token"], "R1")   # kept when not rotated

    def test_failed_refresh_falls_back_to_browser_login(self):
        self.store.save_tokens({"access_token": "A0", "refresh_token": "R1", "expires_at": 0})
        http = FakeHttp()
        http.on("POST", META["token_endpoint"], lambda **kw: Resp(400, {"error": "invalid_grant"}))

        def fake_login(h, meta, c):
            self.store.save_tokens({"access_token": "A3", "refresh_token": "R3", "expires_in": 60})

        with mock.patch.object(sm, "login", fake_login):
            self.assertEqual(sm.access_token(http, self.meta, cfg()), "A3")


class McpClientTests(McpTestCase):
    def setUp(self):
        super().setUp()
        self.meta = dict(META, resource=RESOURCE)
        store = sm.Tokens(RESOURCE, "http://127.0.0.1:8753/oauth/callback")
        store.save_client({"client_id": "CID", "client_secret": "CS"})
        store.save_tokens({"access_token": "A1", "refresh_token": "R1", "expires_in": 3600})

    def server(self, sse=False, first_401=False):
        http = FakeHttp()
        state = {"n": 0}

        def handle(json=None, headers=None, **kw):
            state["n"] += 1
            if first_401 and state["n"] == 1:
                return Resp(401, {})
            if "id" not in json:
                return Resp(202, None, {"Content-Type": "text/plain"})
            if json["method"] == "initialize":
                result = {"protocolVersion": sm.PROTOCOL_VERSION, "capabilities": {}}
            elif json["method"] == "tools/list":
                result = {"tools": [{"name": "query", "inputSchema": {"properties": {"project": {}, "query": {}}}}]}
            else:
                result = {"content": [{"type": "text", "text": "| a |\n| 1 |"}], "isError": False}
            reply = {"jsonrpc": "2.0", "id": json["id"], "result": result}
            hdrs = {"Mcp-Session-Id": "SID"}
            if sse:
                hdrs["Content-Type"] = "text/event-stream"
                return Resp(200, None, hdrs, lines=[": ping", "", "event: message",
                                                    "data: " + __import__("json").dumps(reply), ""])
            hdrs["Content-Type"] = "application/json"
            return Resp(200, reply, hdrs)

        http.on("POST", RESOURCE, handle)
        http.on("POST", META["token_endpoint"], lambda **kw: Resp(body={"access_token": "A9", "expires_in": 60}))
        return http

    def test_initialize_list_and_call_over_json(self):
        http = self.server()
        c = sm.McpClient(http, self.meta, cfg())
        c.start()
        self.assertEqual(c.session_id, "SID")
        self.assertEqual([t["name"] for t in c.tools()], ["query"])
        self.assertIn("| 1 |", sm.tool_text(c.call("query", {"project": "P", "query": "SELECT 1"})))
        sent = [kw["headers"] for verb, url, kw in http.calls if url == RESOURCE]
        self.assertEqual(sent[-1]["Mcp-Session-Id"], "SID")
        self.assertEqual(sent[-1]["Authorization"], "Bearer A1")

    def test_event_stream_replies(self):
        c = sm.McpClient(self.server(sse=True), self.meta, cfg())
        c.start()
        self.assertEqual([t["name"] for t in c.tools()], ["query"])

    def test_401_refreshes_once(self):
        http = self.server(first_401=True)
        c = sm.McpClient(http, self.meta, cfg())
        c.start()
        auths = [kw["headers"]["Authorization"] for verb, url, kw in http.calls if url == RESOURCE]
        self.assertEqual(auths[:2], ["Bearer A1", "Bearer A9"])

    def test_sse_parser_joins_multiline_data_and_skips_comments(self):
        msgs = list(sm._sse_messages([": hi", 'data: {"id": 1,', 'data: "result": {}}', "", "data: not json", ""]))
        self.assertEqual(msgs, [{"id": 1, "result": {}}])

    def test_structured_content_is_preferred(self):
        self.assertEqual(sm.tool_text({"structuredContent": {"rows": 2}}), json.dumps({"rows": 2}, indent=2))


if __name__ == "__main__":
    unittest.main()
