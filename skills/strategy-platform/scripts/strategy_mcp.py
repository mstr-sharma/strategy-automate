"""Call the tenant's Mosaic MCP server from scripts, signed in the way the Mosaic MCP
connector in Claude signs in: OAuth 2.1 authorization code + PKCE through the tenant's own
single sign-on, with dynamic client registration and refresh tokens.

  python3 strategy_mcp.py login                    # browser sign-in once; tokens go to the OS secret store
  python3 strategy_mcp.py tools                    # list the server's tools
  python3 strategy_mcp.py call get_models --args '{"project": "<project>"}'
  python3 strategy_mcp.py query --project "<project>" --sql 'SELECT ... LIMIT 100'
  python3 strategy_mcp.py logout                   # revoke the refresh token and forget everything

The tenant runs two MCP servers: the Mosaic one ({host}/collaboration/mcp/mosaic — get_projects,
get_models, get_semantics, query; the default here) and the agent one ({host}/collaboration/mcp/agent).
Pick with --server mosaic|agent, or name any endpoint with MSTR_MCP_URL / --mcp-url. The token is
scoped to that MCP server:
the Strategy REST API does not accept it, so REST scripts sign in with strategy_auth.py
(`--auth-method sso` uses the same single sign-on through the browser).

Tokens and the registered client live in the OS secret store (see strategy_auth.py); nothing
secret is printed. The redirect is http://127.0.0.1:<MSTR_SSO_PORT, default 8753>/oauth/callback.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import sys
import time
import urllib.parse
from typing import Any, Iterable, Iterator

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import strategy_auth as sa  # noqa: E402

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None  # type: ignore[assignment]
NETWORK_ERRORS: tuple = (requests.RequestException,) if requests is not None else ()

PROTOCOL_VERSION = "2025-06-18"
SCOPES = ("openid", "profile", "email", "offline_access", "mcp:stream")
TIMEOUT = 120


class McpError(RuntimeError):
    """MCP or OAuth failure; the message is safe to print."""


def _origin(url: str) -> str:
    parts = urllib.parse.urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


SERVERS = {"mosaic": "/collaboration/mcp/mosaic", "agent": "/collaboration/mcp/agent"}


def _metadata_from_challenge(http: Any, mcp_url: str) -> str:
    """The MCP way: an unauthenticated call answers 401 with
    WWW-Authenticate: Bearer resource_metadata="<url>"."""
    try:
        r = http.post(mcp_url, timeout=30, json={"jsonrpc": "2.0", "id": 0, "method": "ping"},
                      headers={"Accept": "application/json, text/event-stream"})
    except Exception:
        return ""
    m = re.search(r'resource_metadata="([^"]+)"', r.headers.get("WWW-Authenticate", ""))
    return m.group(1) if m and sa.same_origin(m.group(1), mcp_url) else ""


def _require_secure(url: str, what: str) -> str:
    """OAuth endpoints carry codes, client secrets and refresh tokens: https only (loopback aside)."""
    parts = urllib.parse.urlsplit(url or "")
    if parts.scheme == "https" or (parts.scheme == "http" and parts.hostname in ("127.0.0.1", "localhost", "::1")):
        return url
    raise McpError(f"the authorization server's {what} is not an https URL: {url!r}")


def discover(http: Any, mcp_url: str = "", base: str = "", server: str = "mosaic") -> dict:
    """{resource, issuer, authorization_endpoint, token_endpoint, registration_endpoint, ...}."""
    if not mcp_url:
        if not base:
            raise McpError("set MSTR_MCP_URL or MSTR_BASE")
        mcp_url = _origin(base) + SERVERS.get(server, SERVERS["mosaic"])
    origin, path = _origin(mcp_url), urllib.parse.urlsplit(mcp_url).path
    first, _, rest = path.lstrip("/").partition("/")
    candidates = [c for c in (
        _metadata_from_challenge(http, mcp_url),
        f"{origin}/.well-known/oauth-protected-resource{path}",
        f"{origin}/{first}/.well-known/oauth-protected-resource/{rest}" if rest else "",
    ) if c]
    resource_meta = None
    for url in candidates:
        r = http.get(url, timeout=30)
        if r.ok and "json" in r.headers.get("Content-Type", ""):
            resource_meta = r.json()
            break
    if not resource_meta or not resource_meta.get("authorization_servers"):
        raise McpError(f"no OAuth protected-resource metadata for {mcp_url}")
    resource = resource_meta.get("resource") or mcp_url
    if not sa.same_origin(resource, mcp_url):
        # RFC 9728: a resource that is not the one asked about must not be used — otherwise a
        # look-alike server could name the real tenant and collect its stored tokens.
        raise McpError(f"{mcp_url} describes itself as {resource!r}, another origin; refusing")
    issuer = resource_meta["authorization_servers"][0].rstrip("/")
    issuer_path = urllib.parse.urlsplit(issuer).path
    for url in (f"{_origin(issuer)}/.well-known/oauth-authorization-server{issuer_path}",
                f"{issuer}/.well-known/oauth-authorization-server"):
        r = http.get(url, timeout=30)
        if r.ok and "json" in r.headers.get("Content-Type", ""):
            meta = dict(r.json())
            if meta.get("issuer", "").rstrip("/") == issuer:
                for key in ("authorization_endpoint", "token_endpoint", "registration_endpoint",
                            "revocation_endpoint"):
                    if meta.get(key):
                        _require_secure(meta[key], key)
                meta["resource"] = resource
                meta["mcp_url"] = mcp_url
                return meta
    raise McpError(f"no authorization-server metadata for {issuer}")


class Tokens:
    """Registered client + tokens for one MCP endpoint, kept in the OS secret store. Both are
    bound to the authorization server that issued them and are never offered to another one."""

    def __init__(self, resource: str, redirect_uri: str, issuer: str = ""):
        self.resource, self.redirect_uri = resource, redirect_uri
        self.issuer = issuer.rstrip("/")
        self.client_account = f"mcp-client:{resource}|{redirect_uri}"
        self.token_account = f"mcp-token:{resource}"

    @classmethod
    def for_meta(cls, meta: dict, redirect_uri: str) -> "Tokens":
        """Keyed by the endpoint the user asked for, bound to the issuer that answered."""
        return cls(meta.get("mcp_url") or meta["resource"], redirect_uri, meta.get("issuer", ""))

    def _load(self, account: str) -> dict | None:
        raw = sa.secret_get(account)
        try:
            data = json.loads(raw) if raw else None
        except ValueError:
            return None
        if not isinstance(data, dict) or str(data.get("issuer", "")).rstrip("/") != self.issuer:
            return None
        return data

    def client(self) -> dict | None:
        return self._load(self.client_account)

    def save_client(self, data: dict) -> None:
        sa.secret_set(self.client_account, json.dumps(dict(data, issuer=self.issuer)))

    def tokens(self) -> dict | None:
        return self._load(self.token_account)

    def save_tokens(self, data: dict) -> bool:
        data = dict(data, issuer=self.issuer)
        if "expires_in" in data:
            data["expires_at"] = time.time() + int(data.pop("expires_in"))
        if not sa.secret_set(self.token_account, json.dumps(data)):
            print("[mcp] could not store the tokens; the next command will ask the browser again.", file=sys.stderr)
            return False
        return True

    def forget(self) -> None:
        sa.secret_delete(self.token_account)
        sa.secret_delete(self.client_account)


def register_client(http: Any, meta: dict, redirect_uri: str) -> dict:
    endpoint = meta.get("registration_endpoint")
    if not endpoint:
        raise McpError("the authorization server has no dynamic client registration endpoint")
    r = http.post(endpoint, timeout=30, json={
        "client_name": "strategy-automate command line",
        "redirect_uris": [redirect_uri],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "client_secret_post",
        "scope": " ".join(SCOPES)})
    if r.status_code not in (200, 201) or not (r.json() or {}).get("client_id"):
        raise McpError(f"client registration failed: HTTP {r.status_code}")
    data = r.json()
    return {"client_id": data["client_id"], "client_secret": data.get("client_secret", "")}


def authorize_url(meta: dict, client_id: str, redirect_uri: str, state: str, challenge: str) -> str:
    return meta["authorization_endpoint"] + "?" + urllib.parse.urlencode({
        "response_type": "code", "client_id": client_id, "redirect_uri": redirect_uri,
        "scope": " ".join(SCOPES), "state": state, "code_challenge": challenge,
        "code_challenge_method": "S256", "resource": meta["resource"]})


def _token_request(http: Any, meta: dict, client: dict, form: dict) -> dict:
    form = dict(form, client_id=client["client_id"], resource=meta["resource"])
    if client.get("client_secret"):
        form["client_secret"] = client["client_secret"]
    r = http.post(meta["token_endpoint"], data=form, timeout=30,
                  headers={"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"})
    try:
        body = r.json()
    except ValueError:
        body = {}
    if not r.ok or not body.get("access_token"):
        raise McpError(f"token request ({form['grant_type']}) failed: HTTP {r.status_code} {body.get('error', '')}")
    return body


def login(http: Any, meta: dict, cfg: sa.AuthConfig) -> dict:
    """Browser sign-in; returns the token response (also stored when the store allows)."""
    redirect_uri = f"http://{cfg.sso_host}:{cfg.sso_port}/oauth/callback"
    store = Tokens.for_meta(meta, redirect_uri)
    client = store.client()
    if client is None:
        client = register_client(http, meta, redirect_uri)
        store.save_client(client)
    verifier, challenge = sa.pkce_pair()
    state = secrets.token_urlsafe(24)
    try:
        server = sa._Loopback(cfg.sso_port, state, None, "")
    except OSError:
        raise McpError(f"port {cfg.sso_port} is busy; the registered redirect needs it (or set MSTR_SSO_PORT)") from None
    result = sa._run_loopback(cfg, server, authorize_url(meta, client["client_id"], redirect_uri, state, challenge),
                              "sign in to the MCP server with your browser")
    if "error" in result or not result.get("code"):
        raise McpError(f"sign-in refused: {result.get('error', 'no code')} {result.get('error_description', '')[:200]}")
    tokens = _token_request(http, meta, client, {
        "grant_type": "authorization_code", "code": result["code"], "redirect_uri": redirect_uri,
        "code_verifier": verifier})
    store.save_tokens(tokens)
    return tokens


def access_token(http: Any, meta: dict, cfg: sa.AuthConfig, force_refresh: bool = False) -> str:
    """A live access token: cached, refreshed, or (last resort) a new browser sign-in."""
    redirect_uri = f"http://{cfg.sso_host}:{cfg.sso_port}/oauth/callback"
    store = Tokens.for_meta(meta, redirect_uri)
    tokens, client = store.tokens(), store.client()
    if tokens and not force_refresh and tokens.get("expires_at", 0) > time.time() + 60:
        return tokens["access_token"]
    if tokens and client and tokens.get("refresh_token"):
        try:
            fresh = _token_request(http, meta, client, {"grant_type": "refresh_token",
                                                        "refresh_token": tokens["refresh_token"]})
            fresh.setdefault("refresh_token", tokens["refresh_token"])
            store.save_tokens(fresh)
            return fresh["access_token"]
        except McpError:
            pass
    fresh = login(http, meta, cfg)
    if not fresh or not fresh.get("access_token"):
        raise McpError("signed in, but the authorization server returned no access token")
    return fresh["access_token"]


def _sse_messages(lines: Iterable[str]) -> Iterator[dict]:
    """JSON-RPC messages from a text/event-stream body, yielded as each event completes
    (the caller stops reading once its reply arrives, so an open stream can't hang it)."""
    data: list[str] = []

    def flush() -> Iterator[dict]:
        if data:
            try:
                yield json.loads("\n".join(data))
            except ValueError:
                pass
            data.clear()

    for line in lines:
        if line == "":
            yield from flush()
        elif line.startswith("data:"):
            data.append(line[5:].lstrip())
    yield from flush()


def _is_reply(msg: Any, request_id: Any) -> bool:
    """A JSON-RPC response to our request — not a server-initiated request that reuses the id."""
    return (isinstance(msg, dict) and msg.get("id") == request_id and "method" not in msg
            and ("result" in msg or "error" in msg))


class McpClient:
    """Minimal streamable-HTTP MCP client: initialize, tools/list, tools/call."""

    def __init__(self, http: Any, meta: dict, cfg: sa.AuthConfig):
        self.http, self.meta, self.cfg = http, meta, cfg
        self.url = meta.get("mcp_url") or meta["resource"]   # the endpoint asked for, not a claimed one
        self.session_id = ""
        self._id = 0
        self._token = ""

    def _post(self, body: dict, retry: bool = True) -> Any:
        if not self._token:
            self._token = access_token(self.http, self.meta, self.cfg)
        headers = {"Authorization": f"Bearer {self._token}", "Content-Type": "application/json",
                   "Accept": "application/json, text/event-stream", "MCP-Protocol-Version": PROTOCOL_VERSION}
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        r = self.http.post(self.url, json=body, headers=headers, timeout=TIMEOUT, stream=True)
        if r.status_code == 401 and retry:
            self._token = access_token(self.http, self.meta, self.cfg, force_refresh=True)
            return self._post(body, retry=False)
        if r.headers.get("Mcp-Session-Id"):
            self.session_id = r.headers["Mcp-Session-Id"]
        if "id" not in body:
            return None
        if not r.ok:
            raise McpError(f"MCP {body['method']} failed: HTTP {r.status_code}")
        if "text/event-stream" in r.headers.get("Content-Type", ""):
            r.encoding = "utf-8"   # SSE is always UTF-8; requests would assume ISO-8859-1 for text/*
            try:
                for msg in _sse_messages(r.iter_lines(decode_unicode=True)):
                    if _is_reply(msg, body["id"]):
                        return self._result(body["method"], msg)
            finally:
                r.close()
            raise McpError(f"MCP {body['method']}: the stream ended without a reply")
        try:
            return self._result(body["method"], r.json())
        except ValueError:
            raise McpError(f"MCP {body['method']}: the reply is not JSON") from None

    @staticmethod
    def _result(method: str, msg: dict) -> Any:
        if "error" in msg:
            raise McpError(f"MCP {method} error: {msg['error'].get('message', msg['error'])}")
        return msg.get("result")

    def request(self, method: str, params: dict | None = None) -> Any:
        self._id += 1
        return self._post({"jsonrpc": "2.0", "id": self._id, "method": method, "params": params or {}})

    def start(self) -> dict:
        info = self.request("initialize", {"protocolVersion": PROTOCOL_VERSION, "capabilities": {},
                                           "clientInfo": {"name": "strategy-automate", "version": "1"}})
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return info or {}

    def tools(self) -> list[dict]:
        return (self.request("tools/list") or {}).get("tools", [])

    def call(self, name: str, arguments: dict) -> dict:
        return self.request("tools/call", {"name": name, "arguments": arguments}) or {}


def tool_text(result: dict) -> str:
    """The text a tools/call result carries (structured content as JSON when present)."""
    if result.get("structuredContent") is not None:
        return json.dumps(result["structuredContent"], indent=2)
    return "\n".join(c.get("text", "") for c in result.get("content", []) if c.get("type") == "text")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--base", default="", help="Library URL used to find the MCP server (env MSTR_BASE)")
    ap.add_argument("--mcp-url", default=os.environ.get("MSTR_MCP_URL", ""), help="MCP endpoint (env MSTR_MCP_URL)")
    ap.add_argument("--server", choices=sorted(SERVERS), default="mosaic",
                    help="which of the tenant's MCP servers when --mcp-url is not given (default mosaic)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("login", help="sign in through the browser and keep the tokens")
    sub.add_parser("tools", help="list the MCP server's tools")
    cp = sub.add_parser("call", help="call one tool")
    cp.add_argument("tool")
    cp.add_argument("--args", default="{}", help="tool arguments as a JSON object")
    qp = sub.add_parser("query", help="run read-only SQL through the server's `query` tool")
    qp.add_argument("--project", required=True)
    qp.add_argument("--sql", required=True, help="read-only Trino-compatible SQL; include a LIMIT")
    sub.add_parser("logout", help="revoke the refresh token and forget the client")
    args = ap.parse_args(argv)
    if requests is None:
        raise SystemExit("requests is required (pip install requests)")
    http = sa.SafeSession()
    try:
        cfg = sa.AuthConfig.from_env(base=args.base)
        meta = discover(http, args.mcp_url, cfg.base, args.server)
        if args.cmd == "login":
            login(http, meta, cfg)
            print(json.dumps({"ok": True, "mcp": meta["resource"]}, indent=2))
            return 0
        if args.cmd == "logout":
            store = Tokens.for_meta(meta, f"http://{cfg.sso_host}:{cfg.sso_port}/oauth/callback")
            tokens, registered = store.tokens(), store.client()
            revoked = None
            try:
                if tokens and registered and meta.get("revocation_endpoint") and tokens.get("refresh_token"):
                    form = {"token": tokens["refresh_token"], "token_type_hint": "refresh_token",
                            "client_id": registered["client_id"],
                            "client_secret": registered.get("client_secret", "")}
                    revoked = http.post(meta["revocation_endpoint"], data=form, timeout=30).ok
            except requests.RequestException:
                revoked = False   # the local copy is forgotten anyway; the refresh token expires on its own
            finally:
                store.forget()
            print(json.dumps({"ok": True, "forgotten": meta["resource"], "revoked": revoked}, indent=2))
            return 0
        client = McpClient(http, meta, cfg)
        client.start()
        if args.cmd == "tools":
            out: Any = [{"name": t.get("name"), "description": (t.get("description") or "")[:160],
                         "arguments": sorted(((t.get("inputSchema") or {}).get("properties") or {}).keys())}
                        for t in client.tools()]
            print(json.dumps(out, indent=2))
            return 0
        if args.cmd == "call":
            try:
                tool_args = json.loads(args.args)
            except ValueError as e:
                raise McpError(f"--args is not valid JSON: {e}") from None
            result = client.call(args.tool, tool_args)
        else:
            result = client.call("query", {"project": args.project, "query": args.sql})
        print(tool_text(result))
        return 1 if result.get("isError") else 0
    except (McpError, sa.AuthError) as e:
        print(f"FATAL: {e}", file=sys.stderr)
        return 2
    except NETWORK_ERRORS as e:
        print(f"FATAL: network error: {type(e).__name__}: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
