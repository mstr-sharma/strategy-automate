"""Shared Strategy REST client + helpers for the scripts under skill/scripts/.

Extracted to de-duplicate ~40 LOC of login/session/response_json/items_from_payload
boilerplate that previously lived in every inventory/validation/mining script. See
memory/feedback_build_mosaic_session_leak.md for the session-cap rules these scripts
all share.

Design: a thin BaseMSTR class + pure-function helpers. Subclass BaseMSTR when a
script needs specialized search/read helpers. build_mosaic.py keeps its own MSTR
class for the changeset/identity-token complexity — it imports only the helpers
from here.

Import pattern for a sibling script:

    import os, sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _client import BaseMSTR, response_json, items_from_payload, oid, oname
"""
from __future__ import annotations

import json
from typing import Any, Iterable

import requests


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
                 login_mode: int, project_name: str):
        self.base = base.rstrip("/")
        self.username = username
        self.password = password
        self.login_mode = login_mode
        self.project_name = project_name
        self.project_id: str | None = None
        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/json",
            "Content-Type": "application/json",
        })

    # Auth ─────────────────────────────────────────────────────────────────

    def login(self) -> None:
        resp = self.session.post(
            f"{self.base}/api/auth/login",
            json={"username": self.username, "password": self.password,
                  "loginMode": self.login_mode},
            timeout=60,
        )
        if resp.status_code != 204:
            raise RuntimeError(f"login failed: {resp.status_code} {resp.text[:300]}")
        token = resp.headers.get("X-MSTR-AuthToken") or resp.headers.get("X-Mstr-Authtoken")
        if not token:
            raise RuntimeError("login succeeded but no X-MSTR-AuthToken header returned")
        self.session.headers["X-MSTR-AuthToken"] = token

    def logout(self) -> None:
        try:
            self.session.delete(f"{self.base}/api/auth/login", timeout=20)
        except Exception:
            pass

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
