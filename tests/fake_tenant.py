"""An in-process stand-in for a Strategy Library REST server, for end-to-end tests.

    with FakeTenant() as t:
        os.environ["MSTR_BASE"] = t.base          # http://127.0.0.1:<port>/MicroStrategyLibrary
        ...run a CLI...
        t.count("POST", "/api/auth/login")         # what the scripts actually sent
        t.open_sessions                            # sessions they left behind

It speaks the subset of the REST API the platform core uses — sign-in and logout, session
checks, projects, API tokens, Modeling changesets, user groups, data models, an export, the
CORS preflights `strategy_auth.py methods` probes, and its own OpenAPI document — and records
every request. `fail(...)` injects faults: an HTTP status, a delay, or a dropped connection.
Not a test module itself (no `test` prefix); test files import it.
"""
from __future__ import annotations

import http.server
import json
import re
import secrets
import threading
import time
import urllib.parse
from dataclasses import dataclass, field
from typing import Any, Callable

PREFIX = "/MicroStrategyLibrary"
PROJECT_ID = "B19DEDCC11D4E0EFC000EB9495D0F44F"


@dataclass
class Call:
    method: str
    path: str            # without the /MicroStrategyLibrary prefix
    query: dict
    headers: dict
    body: Any


@dataclass
class Fault:
    method: str
    path: str            # regex, full match against the path
    status: int = 503
    times: int = 1
    delay: float = 0.0
    drop: bool = False   # close the connection without answering
    body: Any = None


@dataclass
class _State:
    users: dict = field(default_factory=lambda: {"alice": "correct horse"})
    api_tokens: dict = field(default_factory=lambda: {"api-token-alice": "alice"})
    identity_tokens: dict = field(default_factory=dict)
    sessions: dict = field(default_factory=dict)       # auth token -> user
    changesets: dict = field(default_factory=dict)     # id -> {"state", "project"}
    groups: list = field(default_factory=lambda: [{"id": "G1", "name": "Analysts"}])
    search_items: list = field(default_factory=list)


def spec() -> dict:
    """The OpenAPI document the fake serves at /api/openapi.json."""
    project = {"name": "X-MSTR-ProjectID", "in": "header", "required": True, "schema": {"type": "string"}}
    changeset = {"name": "X-MSTR-MS-Changeset", "in": "header", "required": True, "schema": {"type": "string"}}
    json_ok = {"200": {"description": "ok", "content": {"application/json": {}}}}
    return {
        "openapi": "3.0.1", "info": {"title": "Fake Strategy REST API", "version": "11.5"},
        "paths": {
            "/api/projects": {"get": {"operationId": "getProjects", "tags": ["Projects"], "responses": json_ok}},
            "/api/usergroups": {
                "get": {"operationId": "getUserGroups", "tags": ["User Management"], "responses": json_ok,
                        "parameters": [{"name": "limit", "in": "query", "schema": {"type": "integer"}}]},
                "post": {"operationId": "createUserGroup", "tags": ["User Management"], "responses": {
                    "201": {"description": "created", "content": {"application/json": {}}}},
                    "requestBody": {"required": True, "content": {"application/json": {"schema": {
                        "$ref": "#/components/schemas/GroupCreate"}}}}}},
            "/api/usergroups/{id}": {"delete": {"operationId": "deleteUserGroup", "tags": ["User Management"],
                                                "parameters": [{"name": "id", "in": "path", "required": True,
                                                                "schema": {"type": "string"}}],
                                                "responses": {"204": {"description": "deleted"}}}},
            "/api/model/dataModels": {"post": {
                "operationId": "createDataModel", "tags": ["Data Models"], "parameters": [project, changeset],
                "responses": {"201": {"description": "created", "content": {"application/json": {}}}},
                "requestBody": {"required": True, "content": {"application/json": {"schema": {
                    "type": "object", "required": ["information"],
                    "properties": {"information": {"type": "object"}}}}}}}},
            "/api/model/dataModels/{dataModelId}": {"get": {
                "operationId": "getDataModel", "tags": ["Data Models"], "responses": json_ok,
                "parameters": [{"name": "dataModelId", "in": "path", "required": True, "schema": {"type": "string"}},
                               project, changeset]}},
            "/api/reports/{reportId}/export": {"get": {
                "operationId": "exportReport", "tags": ["Reports"],
                "parameters": [{"name": "reportId", "in": "path", "required": True, "schema": {"type": "string"}}],
                "responses": {"200": {"description": "pdf", "content": {"application/pdf": {}}}}}},
        },
        "components": {"schemas": {"GroupCreate": {"type": "object", "required": ["name"], "properties": {
            "name": {"type": "string"}, "description": {"type": "string"}}}}},
    }


class FakeTenant:
    def __init__(self, *, cors_any_origin: bool = False, require_auth_for_spec: bool = False):
        self.state = _State()
        self.calls: list[Call] = []
        self.faults: list[Fault] = []
        self.cors_any_origin = cors_any_origin
        self.require_auth_for_spec = require_auth_for_spec
        self.routes: list[tuple[str, re.Pattern, Callable]] = []
        self._lock = threading.Lock()
        self.spec = spec()
        self._register_defaults()
        tenant = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def _handle(self):
                tenant._dispatch(self)

            do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = do_HEAD = _handle

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.httpd.daemon_threads = True
        self.root = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self.base = self.root + PREFIX
        self._thread = threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": 0.05},
                                        daemon=True)
        self._thread.start()

    # ── test-facing helpers ──────────────────────────────────────────────────
    def __enter__(self) -> "FakeTenant":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()

    def fail(self, method: str, path: str, **kw: Any) -> Fault:
        fault = Fault(method.upper(), path, **kw)
        self.faults.append(fault)
        return fault

    def count(self, method: str | None = None, path: str | None = None) -> int:
        return len(self.calls_to(method, path))

    def calls_to(self, method: str | None = None, path: str | None = None) -> list[Call]:
        return [c for c in self.calls if (method is None or c.method == method.upper())
                and (path is None or re.fullmatch(path, c.path))]

    @property
    def open_sessions(self) -> int:
        return len(self.state.sessions)

    def route(self, method: str, pattern: str):
        """Register a handler (call, match) -> (status, body, headers) ahead of the defaults."""
        def deco(fn: Callable) -> Callable:
            self.routes.insert(0, (method.upper(), re.compile(pattern), fn))
            return fn
        return deco

    # ── request handling ─────────────────────────────────────────────────────
    def _dispatch(self, h: http.server.BaseHTTPRequestHandler) -> None:
        url = urllib.parse.urlsplit(h.path)
        length = int(h.headers.get("Content-Length") or 0)
        raw = h.rfile.read(length) if length else b""
        try:
            body: Any = json.loads(raw) if raw and "json" in (h.headers.get("Content-Type") or "") else raw
        except ValueError:
            body = raw
        path = url.path[len(PREFIX):] if url.path.startswith(PREFIX) else url.path
        call = Call(h.command, path, {k: v if len(v) > 1 else v[0] for k, v in
                                      urllib.parse.parse_qs(url.query).items()}, dict(h.headers), body)
        with self._lock:
            self.calls.append(call)
            fault = next((f for f in self.faults if f.times > 0 and f.method in (h.command, "*")
                          and re.fullmatch(f.path, path)), None)
            if fault:
                fault.times -= 1
        if fault:
            if fault.delay:
                time.sleep(fault.delay)
            if fault.drop:
                h.close_connection = True
                try:
                    h.connection.shutdown(2)
                except OSError:
                    pass
                return
            if fault.status:
                return self._send(h, fault.status, fault.body if fault.body is not None
                                  else {"code": "ERR_FAKE", "message": "injected fault"})
        for method, pattern, fn in self.routes:
            m = pattern.fullmatch(path)
            if m and method in (h.command, "*"):
                status, out, headers = fn(call, m)
                return self._send(h, status, out, headers)
        self._send(h, 404, {"code": "ERR001", "message": f"no fake route for {h.command} {path}"})

    @staticmethod
    def _send(h, status: int, body: Any, headers: dict | None = None) -> None:
        headers = dict(headers or {})
        if isinstance(body, (bytes, bytearray)):
            payload = bytes(body)
            headers.setdefault("Content-Type", "application/octet-stream")
        elif body is None:
            payload = b""
        else:
            payload = json.dumps(body).encode()
            headers.setdefault("Content-Type", "application/json")
        h.send_response(status)
        for k, v in headers.items():
            h.send_header(k, v)
        h.send_header("Content-Length", str(len(payload)))
        h.end_headers()
        if h.command != "HEAD":
            h.wfile.write(payload)

    def _user(self, call: Call) -> str | None:
        return self.state.sessions.get(call.headers.get("X-MSTR-AuthToken", ""))

    def _new_session(self, user: str) -> tuple[int, Any, dict]:
        token = secrets.token_hex(16)
        self.state.sessions[token] = user
        return 204, None, {"X-MSTR-AuthToken": token, "Set-Cookie": f"JSESSIONID={secrets.token_hex(8)}; Path=/"}

    def _register_defaults(self) -> None:
        st = self.state

        def authed(fn):
            def wrapper(call, m):
                if self._user(call) is None:
                    return 401, {"code": "ERR009", "message": "The user's session has expired, please reauthenticate"}, {}
                return fn(call, m)
            return wrapper

        def route(method, pattern):
            def deco(fn):
                self.routes.append((method, re.compile(pattern), fn))
                return fn
            return deco

        @route("POST", r"/api/auth/login")
        def login(call, m):
            b = call.body if isinstance(call.body, dict) else {}
            mode = int(b.get("loginMode") or 1)
            if mode in (1, 16) and st.users.get(b.get("username")) == b.get("password") and b.get("password"):
                return self._new_session(b["username"])
            if mode == 4096 and b.get("username") in st.api_tokens:
                return self._new_session(st.api_tokens[b["username"]])
            if mode == 8:
                return self._new_session("guest")
            return 401, {"code": "ERR003", "iServerCode": -2147216959, "message": "Login failure"}, {}

        @route("POST", r"/api/auth/delegate")
        def delegate(call, m):
            b = call.body if isinstance(call.body, dict) else {}
            user = st.identity_tokens.pop(b.get("identityToken"), None)
            if b.get("loginMode") != -1 or not user:
                return 401, {"code": "ERR003", "message": "invalid identity token"}, {}
            return self._new_session(user)

        @route("POST", r"/api/auth/logout")
        def logout(call, m):
            st.sessions.pop(call.headers.get("X-MSTR-AuthToken", ""), None)
            return 204, None, {}

        @route("GET", r"/api/sessions")
        @authed
        def sessions(call, m):
            return 200, {"locale": 1033}, {}

        @route("GET", r"/api/sessions/userInfo")
        @authed
        def user_info(call, m):
            user = self._user(call)
            return 200, {"id": "U-" + user, "fullName": user.title() + " Example", "username": user}, {}

        @route("GET", r"/api/config/authModes")
        def auth_modes(call, m):
            return 200, {"modes": [1, 16, 4096, 1048576]}, {}

        @route("GET", r"/api/config/oidc/native")
        def oidc(call, m):
            return 404, {"code": "ERR001", "message": "not configured"}, {}

        @route("*", r"/api/(auth/token|v2/auth/identityToken)")
        def cors_probe(call, m):
            origin = call.headers.get("Origin", "")
            allowed = self.cors_any_origin or origin.startswith("http://127.0.0.1:")
            headers = {"Access-Control-Allow-Origin": origin, "Access-Control-Allow-Credentials": "true",
                       "Access-Control-Expose-Headers": "X-MSTR-AuthToken"} if allowed and origin else {}
            if call.method == "OPTIONS":
                return 204, None, headers
            if self._user(call) is None:
                return 401, {"code": "ERR009", "message": "no session"}, headers
            return 204, None, {**headers, "X-MSTR-AuthToken": call.headers.get("X-MSTR-AuthToken", "")}

        @route("GET", r"/api/openapi.json")
        def openapi(call, m):
            if self.require_auth_for_spec and self._user(call) is None:
                return 401, {"code": "ERR009", "message": "sign in first"}, {}
            return 200, self.spec, {}

        @route("GET", r"/api/projects")
        @authed
        def projects(call, m):
            return 200, [{"id": PROJECT_ID, "name": "Tutorial", "status": 0}], {}

        @route("GET", r"/api/auth/apiTokens")
        @authed
        def get_tokens(call, m):
            mine = [t for t, u in st.api_tokens.items() if u == self._user(call)]
            return 200, [{"id": "T1"}] if mine else [], {}

        @route("POST", r"/api/auth/apiTokens")
        @authed
        def new_token(call, m):
            user = self._user(call)
            for t in [t for t, u in st.api_tokens.items() if u == user]:
                del st.api_tokens[t]
            token = "api-" + secrets.token_hex(12)
            st.api_tokens[token] = user
            return 201, {"apiToken": token, "expireTime": "2099-01-01T00:00:00.000+0000"}, {}

        @route("DELETE", r"/api/auth/apiTokens")
        @authed
        def revoke_tokens(call, m):
            user = self._user(call)
            for t in [t for t, u in st.api_tokens.items() if u == user]:
                del st.api_tokens[t]
            return 204, None, {}

        @route("POST", r"/api/model/changesets")
        @authed
        def open_changeset(call, m):
            cs = secrets.token_hex(16).upper()
            st.changesets[cs] = {"state": "open", "project": call.headers.get("X-MSTR-ProjectID")}
            return 201, {"id": cs}, {}

        @route("POST", r"/api/model/changesets/(\w+)/commit")
        @authed
        def commit(call, m):
            cs = st.changesets.get(m.group(1))
            if not cs or cs["state"] != "open":
                return 404, {"code": "ERR004", "message": "no such changeset"}, {}
            cs["state"] = "committed"
            return 200, {"id": m.group(1)}, {}

        @route("DELETE", r"/api/model/changesets/(\w+)")
        @authed
        def discard(call, m):
            cs = st.changesets.get(m.group(1))
            if not cs or cs["state"] != "open":
                return 404, {"code": "ERR004", "message": "no such changeset"}, {}
            cs["state"] = "discarded"
            return 204, None, {}

        def _changeset_ok(call) -> bool:
            cs = st.changesets.get(call.headers.get("X-MSTR-MS-Changeset", ""))
            return bool(cs and cs["state"] == "open")

        @route("POST", r"/api/model/dataModels")
        @authed
        def create_model(call, m):
            if not call.headers.get("X-MSTR-ProjectID"):
                return 400, {"code": "ERR006", "message": "X-MSTR-ProjectID is required"}, {}
            if not _changeset_ok(call):
                return 400, {"code": "ERR006", "message": "a changeset is required"}, {}
            return 201, {"information": {"objectId": "M" + secrets.token_hex(15).upper(),
                                         "name": (call.body or {}).get("information", {}).get("name", "")}}, {}

        @route("GET", r"/api/model/dataModels/(\w+)")
        @authed
        def get_model(call, m):
            if not _changeset_ok(call):
                return 400, {"code": "ERR006", "message": "a changeset is required"}, {}
            return 200, {"information": {"objectId": m.group(1)}}, {}

        @route("GET", r"/api/usergroups")
        @authed
        def groups(call, m):
            limit = int(call.query.get("limit") or 1000)
            return 200, st.groups[:limit], {}

        @route("POST", r"/api/usergroups")
        @authed
        def new_group(call, m):
            group = {"id": "G" + str(len(st.groups) + 1), "name": call.body["name"]}
            st.groups.append(group)
            return 201, group, {}

        @route("DELETE", r"/api/usergroups/(\w+)")
        @authed
        def drop_group(call, m):
            st.groups[:] = [g for g in st.groups if g["id"] != m.group(1)]
            return 204, None, {}

        @route("GET", r"/api/reports/(\w+)/export")
        @authed
        def export(call, m):
            return 200, b"%PDF-1.7 fake report " + m.group(1).encode(), {"Content-Type": "application/pdf"}

        @route("GET", r"/api/searches/results")
        @authed
        def search(call, m):
            offset, limit = int(call.query.get("offset") or 0), int(call.query.get("limit") or 50)
            page = st.search_items[offset:offset + limit]
            return 200, {"totalItems": len(st.search_items), "result": page}, {}
