"""Shared Strategy REST client + helpers for every script in this repo (platform core).

Extracted to de-duplicate ~40 LOC of login/session/response_json/items_from_payload
boilerplate that previously lived in every inventory/validation/mining script. See
memory/feedback_build_mosaic_session_leak.md for the session-cap rules these scripts
all share.

Design: a thin BaseMSTR class + pure-function helpers. Subclass BaseMSTR when a
script needs specialized search/read helpers. build_mosaic.py keeps its own MSTR
class for the changeset/identity-token complexity. Sign-in for both goes through
strategy_auth.py next to this file.

Import pattern for a script in another skill (skills/<skill>/scripts/x.py):

    import os, sys
    sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                     os.pardir, os.pardir, "strategy-platform", "scripts")))
    from _client import BaseMSTR, response_json, items_from_payload, oid, oname
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Iterable

try:
    import requests
except ImportError:  # file-only consumers (strategy_validate_models) tolerate absence
    requests = None  # type: ignore[assignment]


# ── Payload helpers (pure functions) ─────────────────────────────────────────

def response_json(resp: requests.Response | None) -> Any:
    """Parse a response body as JSON; fall back to a compact text preview. Empty
    body → {}."""
    if resp is None or not resp.text:
        return {}
    try:
        return resp.json()
    except Exception:
        return {"_text": resp.text[:500]}


# Default list-container keys that Strategy REST payloads wrap rows in. Scripts
# can extend this when a specific endpoint wraps rows under a non-standard key.
DEFAULT_LIST_KEYS: tuple[str, ...] = (
    "result", "results", "objects", "items", "data",
    "attributes", "metrics", "factMetrics", "tables",
    "securityFilters", "links", "externalDataModels", "folders",
)

# Narrow key set for /api/searches/results envelopes — never the modeling-object
# containers, so a search payload's sub-lists don't get unwrapped by accident.
SEARCH_LIST_KEYS: tuple[str, ...] = ("result", "results", "objects", "items", "data")


def items_from_payload(payload: Any, keys: Iterable[str] = DEFAULT_LIST_KEYS) -> list[dict[str, Any]]:
    """Coerce a Strategy REST list response into a plain list[dict]. Accepts
    bare lists, payloads with a list under one of `keys`, or anything else (→[])."""
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if not isinstance(payload, dict):
        return []
    for key in keys:
        value = payload.get(key)
        if isinstance(value, list):
            return [x for x in value if isinstance(x, dict)]
    return []


def oid(obj: dict[str, Any] | None) -> str | None:
    """Object id accessor — checks `information.objectId`, then `id` / `objectId`."""
    if not isinstance(obj, dict):
        return None
    info = obj.get("information")
    if isinstance(info, dict) and info.get("objectId"):
        return str(info["objectId"])
    return obj.get("id") or obj.get("objectId") or obj.get("object_id")


def oname(obj: dict[str, Any] | None) -> str:
    """Object name accessor — checks `information.name`, then `name` / `display` / `title`."""
    if not isinstance(obj, dict):
        return ""
    info = obj.get("information")
    if isinstance(info, dict) and info.get("name"):
        return str(info["name"])
    return str(obj.get("name") or obj.get("display") or obj.get("title") or "")


def normalize_id(obj: dict[str, Any]) -> str | None:
    """Legacy alias for `oid` used by strategy_validate.py. Prefers flat id fields."""
    return obj.get("id") or obj.get("objectId") or obj.get("object_id")


def normalize_name(obj: dict[str, Any]) -> str:
    """Legacy alias for `oname` used by strategy_validate.py. Accepts username too."""
    return str(
        obj.get("name") or obj.get("username") or obj.get("display") or obj.get("title") or ""
    )


def ancestor_names(obj: dict[str, Any]) -> list[str]:
    ancestors = obj.get("ancestors")
    if not isinstance(ancestors, list):
        return []
    return [str(a.get("name") or "") for a in ancestors if isinstance(a, dict)]


def compact_json(value: Any, limit: int = 800) -> str:
    try:
        text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    except TypeError:
        text = str(value)
    return text if len(text) <= limit else text[: limit - 3] + "..."


def dedupe_by_id(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop rows whose oid() is missing or already seen, keeping first occurrence."""
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for row in rows:
        object_id = oid(row)
        if not object_id or object_id in seen:
            continue
        seen.add(object_id)
        out.append(row)
    return out


def now_id() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


# ── JSON-tree helpers (pure functions) ───────────────────────────────────────

def walk(value: Any):
    """Depth-first generator over every dict in a nested dict/list payload."""
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def collect_texts(value: Any, limit: int = 8) -> list[str]:
    """Unique `text` values found anywhere in the payload, in walk order."""
    texts: list[str] = []
    for node in walk(value):
        text = node.get("text")
        if isinstance(text, str) and text and text not in texts:
            texts.append(text)
            if len(texts) >= limit:
                break
    return texts


def collect_named_values(value: Any, key: str, limit: int = 20) -> list[str]:
    """Unique string values of `key` found anywhere in the payload, in walk order."""
    values: list[str] = []
    for node in walk(value):
        item = node.get(key)
        if isinstance(item, str) and item and item not in values:
            values.append(item)
            if len(values) >= limit:
                break
    return values


def expression_kind(value: Any) -> str:
    """Classify a modeling-object body's expression: tree type, 'text', or ''."""
    if not isinstance(value, dict):
        return ""
    expr = value.get("expression") or value.get("qualification") or value.get("definition") or value
    if isinstance(expr, dict):
        tree = expr.get("tree") or expr.get("predicateTree")
        if isinstance(tree, dict) and tree.get("type"):
            return str(tree["type"])
        if expr.get("text"):
            return "text"
    return ""


# ── Base HTTP client ─────────────────────────────────────────────────────────

class BaseMSTR:
    """Minimal Strategy REST client: login, logout, project resolution, and a
    `request`/`try_request` pair that consistently threads `X-MSTR-ProjectID` in.

    Subclass and add domain-specific helpers when a script needs them (see
    strategy_semantic_mine.py, strategy_validate.py).

    Contract:
        m = BaseMSTR(base, username, password, login_mode, project_name)
        m.login()              # → sets X-MSTR-AuthToken
        m.resolve_project()    # → sets X-MSTR-ProjectID (optional; skip for project-agnostic calls)
        m.request("GET", "/api/projects", project=False)
        m.logout()
    """

    def __init__(self, base: str, username: str, password: str,
                 login_mode: int, project_name: str, auth_method: str | None = None):
        if requests is None:
            raise SystemExit("requests is required for the REST client (pip install requests).")
        self.base = base.rstrip("/")
        self.username = username
        self.password = password
        self.login_mode = login_mode
        self.auth_method = auth_method
        self.signin: Any = None   # strategy_auth.SignIn once signed in
        self.project_name = project_name
        self.project_id: str | None = None
        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/json",
            "Content-Type": "application/json",
        })

    # Auth ─────────────────────────────────────────────────────────────────

    def login(self) -> None:
        """Sign in with any method strategy_auth supports (password, LDAP, API token,
        browser SSO, ...). Raises RuntimeError with a printable message."""
        import strategy_auth
        try:
            self.signin = strategy_auth.sign_in(self.session, strategy_auth.AuthConfig.from_env(
                base=self.base, method=self.auth_method, username=self.username,
                password=self.password, login_mode=self.login_mode))
        except strategy_auth.AuthError as e:
            raise RuntimeError(str(e)) from None

    def logout(self) -> None:
        """POST /api/auth/logout for sessions this client created; browser-shared or
        cached sessions stay open for the next command."""
        import strategy_auth
        strategy_auth.sign_out(self.session, self.base, self.signin)

    # Project ──────────────────────────────────────────────────────────────

    def resolve_project(self) -> dict[str, Any]:
        """Case-insensitive name or exact-id match against /api/projects. Sets
        `self.project_id` and the `X-MSTR-ProjectID` header. Raises if not found."""
        projects = response_json(self.request("GET", "/api/projects", project=False))
        if not isinstance(projects, list):
            raise RuntimeError(f"unexpected /api/projects payload: {compact_json(projects)}")
        want = (self.project_name or "").lower()
        for project in projects:
            if (project.get("name", "").lower() == want
                    or project.get("id") == self.project_name):
                self.project_id = project["id"]
                self.session.headers["X-MSTR-ProjectID"] = self.project_id
                return project
        raise RuntimeError(f"project not found: {self.project_name}")

    # Request wrappers ─────────────────────────────────────────────────────

    def request(self, method: str, path: str, *, project: bool = True,
                ok: tuple[int, ...] | None = None, timeout: int = 90,
                **kwargs) -> requests.Response:
        """Issue a request; raise RuntimeError on non-OK status. `project=True` threads
        the resolved X-MSTR-ProjectID in. `ok` overrides the default 2xx acceptance set."""
        headers = dict(kwargs.pop("headers", {}) or {})
        if project and self.project_id:
            headers.setdefault("X-MSTR-ProjectID", self.project_id)
        resp = self.session.request(method, f"{self.base}{path}",
                                    headers=headers, timeout=timeout, **kwargs)
        if ok is None:
            ok = tuple(range(200, 300))
        if resp.status_code not in ok:
            raise RuntimeError(f"{method} {path} -> {resp.status_code}: {resp.text[:600]}")
        return resp

    def try_request(self, method: str, path: str, **kwargs) -> requests.Response | None:
        """Non-raising variant. Returns None on any error."""
        try:
            return self.request(method, path, **kwargs)
        except Exception:
            return None

    # Search ───────────────────────────────────────────────────────────────

    def search_results(self, name: str = "", obj_type: int | None = None, *,
                       pattern: int = 4, limit: int = 200, get_ancestors: bool = True,
                       paginate: bool = True, keys: Iterable[str] = DEFAULT_LIST_KEYS,
                       timeout: int = 90) -> list[dict[str, Any]]:
        """GET /api/searches/results. With paginate=True follows offset pages until
        a short page; with paginate=False returns the single page (no offset param).
        `keys` picks the list-container keys to unwrap. Raises on non-2xx (via
        `request`); rows are NOT deduped — wrap with dedupe_by_id when needed."""
        out: list[dict[str, Any]] = []
        offset = 0
        while True:
            params: dict[str, Any] = {"name": name, "pattern": pattern, "limit": limit}
            if obj_type is not None:
                params["type"] = obj_type
            if paginate:
                params["offset"] = offset
            if get_ancestors:
                params["getAncestors"] = "true"
            resp = self.request("GET", "/api/searches/results", params=params, timeout=timeout)
            rows = items_from_payload(response_json(resp), keys)
            out.extend(rows)
            if not paginate or len(rows) < limit:
                return out
            offset += limit


# ── Shared parts of the inventory scripts ────────────────────────────────────

@dataclass
class Auth:
    """Session-auth snapshot for raw requests.get calls in worker threads."""
    base: str
    headers: dict[str, str]
    cookies: dict[str, str]
    project_id: str


class InventoryClient(BaseMSTR):
    """BaseMSTR + login-then-resolve + auth snapshot, shared by the inventory scripts."""

    def login(self) -> None:  # type: ignore[override]
        super().login()
        self.resolve_project()

    def auth(self) -> Auth:
        return Auth(self.base, {str(k): str(v) for k, v in self.session.headers.items()},
                    self.session.cookies.get_dict(), self.project_id or "")


_THREAD_LOCAL = threading.local()


def thread_session() -> "requests.Session":
    """A requests.Session per worker thread: connection reuse (no TCP+TLS handshake per call)
    without sharing one Session across threads."""
    session = getattr(_THREAD_LOCAL, "session", None)
    if session is None:
        session = requests.Session()
        _THREAD_LOCAL.session = session
    return session


def read_parallel(items: list[dict[str, Any]], reader: Callable[[dict[str, Any]], dict[str, Any]],
                  workers: int, progress_every: int = 0) -> dict[str, dict[str, Any]]:
    """Map `reader(item)` over a thread pool; key results by oid(item). When
    progress_every > 0, prints done/total to stderr every N completions and at the end."""
    definitions: dict[str, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {pool.submit(reader, item): item for item in items}
        done = 0
        for future in as_completed(futures):
            definitions[oid(futures[future]) or ""] = future.result()
            done += 1
            if progress_every and (done % progress_every == 0 or done == len(items)):
                print(f"  {done}/{len(items)}", file=sys.stderr)
    return definitions


def write_private_json(data: Any, path: str = "", prefix: str = "strategy") -> str:
    """Write JSON readable only by this user (0600). Without `path`, a new file in the temp
    dir is created with O_EXCL (no predictable name, no symlink overwrite). Returns the path.
    Inventories and ledgers carry security-filter definitions, SQL and owners."""
    if path:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    else:
        fd, path = tempfile.mkstemp(prefix=f"{prefix}-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    return path


def dump_inventory(inventory: Any, out: str, prefix: str, run_id: str) -> str:
    """Write inventory JSON to `out`, or to a new private temp file. Returns the path."""
    return write_private_json(inventory, out, prefix=f"{prefix}-{run_id}")


# ── CLI helpers ──────────────────────────────────────────────────────────────

def add_auth_args(parser: argparse.ArgumentParser, *, password: bool = True,
                  login_mode: bool = True, project_name: bool = True,
                  project_id: bool = False,
                  help_text: dict[str, str] | None = None) -> argparse.ArgumentParser:
    """Add the standard --base/--user/--password/--login-mode/--project-name auth
    flags with MSTR_* env defaults (read at call time, not import time). Keyword
    toggles drop/add flags per script; help_text overrides per-flag help, keyed
    by flag name without the leading dashes."""
    h = help_text or {}
    parser.add_argument("--base", default=os.environ.get("MSTR_BASE", ""), help=h.get("base"))
    parser.add_argument("--user", default=os.environ.get("MSTR_USER", ""), help=h.get("user"))
    if password:
        parser.add_argument("--password", default=os.environ.get("MSTR_PASSWORD", ""), help=h.get("password"))
    if login_mode:
        parser.add_argument("--login-mode", type=int, default=int(os.environ.get("MSTR_LOGIN_MODE", "1")),
                            help=h.get("login-mode") or "1 Standard (default), 16 LDAP, 8 Anonymous, 4096 API token")
        parser.add_argument("--auth-method", default=os.environ.get("MSTR_AUTH_METHOD", "auto"),
                            help=h.get("auth-method") or "auto (default), password, ldap, anonymous, api-token, "
                            "sso (browser single sign-on), identity-token, oidc — see strategy_auth.py")
    if project_name:
        parser.add_argument("--project-name", default=os.environ.get("MSTR_PROJECT_NAME", ""),
                            help=h.get("project-name"))
    if project_id:
        parser.add_argument("--project-id", default=os.environ.get("MSTR_PROJECT_ID", ""),
                            help=h.get("project-id"))
    return parser


def client_from_args(args: argparse.Namespace, cls: type = BaseMSTR) -> Any:
    """Build a `cls` client from add_auth_args flags. Prompts for a password only
    when password sign-in is what will run (a --user without a password, an API
    token or an identity token); otherwise strategy_auth signs in another way."""
    method = (getattr(args, "auth_method", None) or os.environ.get("MSTR_AUTH_METHOD") or "auto").lower()
    password = args.password
    other_credential = os.environ.get("MSTR_API_TOKEN") or os.environ.get("MSTR_DELEGATE_IDENTITY_TOKEN")
    if not password and (method in ("password", "ldap")
                         or (method == "auto" and args.user and not other_credential)):
        password = getpass.getpass("Password: ")
    return cls(args.base, args.user, password, args.login_mode, args.project_name, auth_method=method)
