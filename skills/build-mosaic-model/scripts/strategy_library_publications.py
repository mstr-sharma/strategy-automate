#!/usr/bin/env python3
"""
strategy_library_publications.py - find out which dashboards, documents, agents and
reports were published to which users and user groups in a
Strategy (MicroStrategy) project, and republish the same grants in another
project, for example a duplicated copy of it.

Requirements: Python 3.8+ and the `requests` package. Nothing else.

Connection settings (command-line flags override environment variables):
    MSTR_BASE        Library URL, e.g. https://host/MicroStrategyLibrary
    MSTR_USER        user name
    MSTR_PASSWORD    password (you are prompted for it when it is not set)
    MSTR_LOGIN_MODE  1 = standard (default), 16 = LDAP, 4096 = API token, 8 = guest
    MSTR_API_TOKEN   API token, used when the login mode is 4096
    MSTR_SSL_VERIFY  "0" to skip TLS certificate checks, or a path to a CA bundle

Examples:
    # 1. inventory of the source project (read-only; dashboards, documents,
    #    agents and reports by default - reports can be in Library too)
    python strategy_library_publications.py export --project "Sales Project" --out mapping.csv
    python strategy_library_publications.py export --project 0123...CDEF --types dashboards,documents --by-recipient

    # 1b. run the same export against the COPY first: depending on how it was
    #     duplicated, some or all publications may already be there
    python strategy_library_publications.py export --project "Sales Project Copy" --out copy_before.csv

    # 2. what would be published in the copy (read-only dry run, the default)
    python strategy_library_publications.py replicate --mapping mapping.csv --target-project "Sales Project Copy"

    # 3. publish the missing grants in the copy
    python strategy_library_publications.py replicate --mapping mapping.csv --target-project "Sales Project Copy" --apply

How it works (Strategy REST API):
    * There is no endpoint that lists "everything published to user/group X".
      The publication list lives on each object, so `export` enumerates every
      dashboard/document in the project (metadata search, type 55; reports are
      type 3) and calls, for each one,
          GET /api/library/{objectId}      header X-MSTR-ProjectID: <project>
          -> {"id": ..., "recipients": [{"id", "name", "subtype"}]}
      subtype 8704 = user, 8705 = user group. Groups come back as the group
      itself (members are not expanded). A never-published object returns 200
      with an empty list. The per-user / per-group view is the inverted list.
    * A duplicated project keeps the object IDs, and users/groups are shared
      by all projects of the environment, so the same IDs are replayed in the
      target project:
          GET  /api/objects/{id}?type=55   (target header)  -> does the object exist?
          GET  /api/library/{id}           (target header)  -> who has it already?
          POST /api/library {"id": id, "recipients": [{"id": userOrGroupId}, ...]}
                                           (target header)  -> 204, missing grants only
      Group IDs are sent as groups, so people who join the group later get the
      content too. POST is additive (existing recipients are kept) and
      re-posting an existing recipient is a no-op - both verified live. After
      publishing, the list is read back to verify.

Safety:
    * `export` and a `replicate` dry run are read-only.
    * `replicate --apply` only ever ADDS recipients. The script never
      unpublishes and never calls DELETE /api/library/{id} (that endpoint
      removes an object from EVERY recipient's Library).
    * Passwords and tokens are never printed or written to disk. Recipient
      descriptions are deliberately not exported (they can hold free text).

Exit codes: 0 success; 1 fatal error (login, project, bad input); 2 usage
error; 3 finished, but some objects or recipients could not be read or
resolved (see the report); 4 (--apply only) a publish or its verification
failed.
"""

from __future__ import annotations

import argparse
import collections
import csv
import datetime as _dt
import getpass
import json
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

try:
    import requests
except ImportError:  # pragma: no cover
    sys.exit("This script needs the 'requests' package:  pip install requests")

__version__ = "1.0.0"

EXIT_OK, EXIT_FATAL, EXIT_PARTIAL, EXIT_APPLY_FAILED = 0, 1, 3, 4

ID_RE = re.compile(r"^[0-9A-Fa-f]{32}$")

# Object type / subtype codes (EnumDSSXMLObjectTypes / EnumDSSXMLObjectSubTypes)
TYPE_REPORT = 3                 # report definitions (grids, graphs, ... and cubes)
TYPE_USER_OR_GROUP = 34         # users (subtype 8704) and user groups (8705)
TYPE_DOCUMENT = 55              # document definitions: dashboards, documents, agents
SUBTYPE_RWD = 14081             # report writing document = dashboards AND documents
AGENT_SUBTYPES = {14084, 14087, 14091}      # bot, bot 2.0 / agent, universal agent
CUBE_SUBTYPES = {776, 779, 780, 784, 785, 786}  # cubes / models: never Library items
RECIPIENT_TYPE = {8704: "user", 8705: "group"}

# Dashboards and documents share subtype 14081; viewMedia tells them apart
# (same test as mstrio.utils.helper.is_dashboard).
DASHBOARD_MASK, DASHBOARD_BITS = 0xE8000000, 0x60000000

TYPE_CHOICES = ("dashboards", "documents", "agents", "reports")
DEFAULT_TYPES = TYPE_CHOICES    # Library parity; narrow with --types for a faster scan
KIND_OBJECT_TYPE = {"dashboard": TYPE_DOCUMENT, "document": TYPE_DOCUMENT,
                    "agent": TYPE_DOCUMENT, "report": TYPE_REPORT}

CSV_FIELDS = ["document_id", "document_name", "document_kind", "subtype",
              "recipient_id", "recipient_name", "recipient_type",
              "object_type", "folder_path", "source_project_id", "source_project_name"]

LOGIN_MODES = {"standard": 1, "guest": 8, "anonymous": 8, "ldap": 16, "apitoken": 4096,
               "api_token": 4096, "token": 4096}


# --------------------------------------------------------------------------- utils

def log(msg: str = "") -> None:
    """Progress and warnings go to stderr so stdout stays a clean report."""
    print(msg, file=sys.stderr, flush=True)


def usage_error(msg: str):
    log(msg)
    raise SystemExit(2)


def is_dashboard(view_media) -> bool:
    return (int(view_media or 0) & DASHBOARD_MASK) == DASHBOARD_BITS


def classify(obj: dict, default_type: int | None = None) -> str | None:
    """Return 'dashboard' | 'document' | 'agent' | 'report' or None."""
    obj_type = obj.get("type", default_type)
    subtype = obj.get("subtype")
    if obj_type == TYPE_DOCUMENT:
        if subtype == SUBTYPE_RWD:
            return "dashboard" if is_dashboard(obj.get("viewMedia")) else "document"
        if subtype in AGENT_SUBTYPES:
            return "agent"
        return None  # HTML documents (14080), themes (14082), AI dataset collections (14088) ...
    if obj_type == TYPE_REPORT:
        return None if subtype in CUBE_SUBTYPES else "report"
    return None


def recipient_type(subtype) -> str:
    return RECIPIENT_TYPE.get(subtype, "other:%s" % subtype)


def folder_path(ancestors) -> str:
    """'Public Objects/Reports/Sales' from an ancestors list, without the project
    root folder (its name differs between a project and its copy)."""
    if not ancestors:
        return ""
    ordered = sorted(ancestors, key=lambda a: a.get("level", 0), reverse=True)
    return "/".join(a.get("name", "") for a in ordered[1:])


def describe(resp) -> str:
    """Short, secret-free description of an error response."""
    try:
        j = resp.json()
    except ValueError:
        j = None
    if isinstance(j, dict) and (j.get("code") or j.get("message")):
        parts = [str(resp.status_code)] + [str(j[k]) for k in ("code", "iServerCode") if j.get(k) is not None]
        msg = str(j.get("message") or "").strip().replace("\n", " ")
        return " ".join(parts) + (": " + msg[:300] if msg else "")
    return "%s: %s" % (resp.status_code, (resp.text or "").strip().replace("\n", " ")[:300])


def normalize_base_url(url: str) -> str:
    url = (url or "").strip().rstrip("/")
    if not re.match(r"^https?://", url):
        usage_error("Base URL must look like https://host/MicroStrategyLibrary (got %r)" % url)
    url = re.sub(r"/app(/.*)?$", "", url)          # pasted a Library page URL
    url = re.sub(r"/api(-docs)?(/.*)?$", "", url)  # pasted the REST root
    return url.rstrip("/")


def stem_of(path: str) -> str:
    root, ext = os.path.splitext(path)
    return root if ext.lower() in (".csv", ".json") else path


_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")
_ESCAPE_START = _FORMULA_START + ("'",)   # a leading quote is escaped too, so it round-trips


def _csv_safe(v):
    """Names are author-controlled; keep Excel from running one as a formula."""
    return "'" + v if isinstance(v, str) and v.startswith(_ESCAPE_START) else v


def _csv_unsafe(v: str) -> str:
    return v[1:] if v.startswith("'") and v[1:].startswith(_ESCAPE_START) else v


def write_csv(path: str, fields, rows) -> None:
    # utf-8-sig so Excel shows non-ASCII names correctly
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows({k: _csv_safe(v) for k, v in row.items()} for row in rows)


def now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()


# --------------------------------------------------------------------------- REST client

class ApiError(Exception):
    pass


class Client:
    """Thin requests-based REST client. Every project-scoped call passes its
    project explicitly, so there is never a "currently selected" project."""

    RETRY_STATUS = {429, 502, 503, 504}

    def __init__(self, base_url, username=None, password=None, login_mode=1, api_token=None,
                 verify=True, timeout=120.0, retries=4, auth_method=None):
        self.base = normalize_base_url(base_url)
        self.username = username
        self._password = password
        self._api_token = api_token
        # "sso" / "identity-token" / "oidc" / "auto" sign in through strategy_auth
        # (browser single sign-on, cached sessions, saved API tokens).
        self.auth_method = auth_method
        self._signin = None
        self.login_mode = int(login_mode)
        self.timeout = timeout
        self.retries = max(0, int(retries))
        self.session = requests.Session()
        self.session.headers["Accept"] = "application/json"
        self.session.verify = verify
        self.user_id = None
        self.user_name = None
        self._lock = threading.Lock()
        self._relogins = 0

    # -- auth
    def login(self) -> None:
        if self.auth_method:
            return self._login_via_strategy_auth()
        body = {"loginMode": self.login_mode}
        if self.login_mode == 4096:
            body["username"] = self._api_token       # API-token login, same as mstrio-py
        elif self.login_mode != 8:
            body.update(username=self.username, password=self._password)
        self.session.headers.pop("X-MSTR-AuthToken", None)
        self.session.cookies.clear()
        # retried on 502/503/504 and connect errors only; a read timeout is not
        # retried, since the first login may have created a session (see _send)
        r = self._send("POST", "/api/auth/login", retry=True, json=body)
        token = r.headers.get("X-MSTR-AuthToken")
        if r.status_code not in (200, 204) or not token:
            raise ApiError("login failed: %s" % describe(r))
        self.session.headers["X-MSTR-AuthToken"] = token
        r = self._send("GET", "/api/sessions/userInfo", retry=True)
        if r.ok:
            info = r.json()
            self.user_id, self.user_name = info.get("id"), info.get("fullName")

    def _login_via_strategy_auth(self) -> None:
        sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                         os.pardir, os.pardir, "strategy-platform", "scripts")))
        import strategy_auth
        self.session.headers.pop("X-MSTR-AuthToken", None)
        self.session.cookies.clear()
        try:
            self._signin = strategy_auth.sign_in(self.session, strategy_auth.AuthConfig.from_env(
                base=self.base, method=self.auth_method))
        except strategy_auth.AuthError as e:
            raise ApiError("sign-in failed: %s" % e) from None
        r = self._send("GET", "/api/sessions/userInfo", retry=True)
        if r.ok:
            info = r.json()
            self.user_id, self.user_name = info.get("id"), info.get("fullName")

    def logout(self) -> None:
        if self._signin is not None and not self._signin.owns_session:
            self.session.close()   # shared with a browser or cached for the next command
            return
        if "X-MSTR-AuthToken" in self.session.headers:
            try:
                self.session.post(self.base + "/api/auth/logout", timeout=30)  # POST, not DELETE
            except requests.RequestException:
                pass
            self.session.headers.pop("X-MSTR-AuthToken", None)
        self.session.close()

    # -- transport
    def _send(self, method, path, project_id=None, retry=True, headers=None, **kw):
        hdrs = dict(headers or {})
        if project_id:
            hdrs["X-MSTR-ProjectID"] = project_id
        attempts = self.retries + 1 if retry else 1
        for attempt in range(attempts):
            try:
                r = self.session.request(method, self.base + path, headers=hdrs, timeout=self.timeout, **kw)
            except requests.RequestException as err:
                # Retry transient network errors only. A non-GET is re-sent only when it
                # cannot have reached the server (connect-phase failure), so a login is
                # never repeated after the server may already have created a session.
                transient = isinstance(err, (requests.ConnectionError, requests.Timeout,
                                             requests.exceptions.ChunkedEncodingError))
                unsent = isinstance(err, requests.ConnectionError)   # includes ConnectTimeout
                if not transient or (method != "GET" and not unsent) or attempt + 1 >= attempts:
                    raise ApiError("%s %s: %s: %s" % (method, path, type(err).__name__, err)) from err
                self._backoff(attempt, type(err).__name__)
                continue
            if r.status_code in self.RETRY_STATUS and attempt + 1 < attempts:
                self._backoff(attempt, str(r.status_code))
                continue
            return r
        raise ApiError("%s %s: no response" % (method, path))  # not reached

    @staticmethod
    def _backoff(attempt, why):
        delay = min(30, 2 ** (attempt + 1))
        log("  ... %s, retrying in %ss" % (why, delay))
        time.sleep(delay)

    def request(self, method, path, project_id=None, retry=None, **kw):
        """GETs are retried on 429/502/503/504 and network errors; writes are not
        (their effect is verified by reading back instead). On 401 (session
        expired) the client logs in again once and repeats the call."""
        if retry is None:
            retry = method == "GET"
        token = self.session.headers.get("X-MSTR-AuthToken")
        r = self._send(method, path, project_id, retry=retry, **kw)
        if r.status_code == 401:
            with self._lock:
                if self.session.headers.get("X-MSTR-AuthToken") == token:
                    if self._relogins >= 3:
                        return r
                    self._relogins += 1
                    log("  ... session expired, logging in again")
                    self.login()
            r = self._send(method, path, project_id, retry=retry, **kw)
        return r

    def get_json(self, path, project_id=None, **kw):
        r = self.request("GET", path, project_id, **kw)
        if r.status_code != 200:
            raise ApiError("GET %s: %s" % (path, describe(r)))
        return r.json()


# --------------------------------------------------------------------------- REST helpers

def resolve_project(client: Client, ref: str):
    """Project ID or exact name -> (id, name)."""
    projects = client.get_json("/api/projects")
    by_id = {p["id"].upper(): p for p in projects}
    listing = "\n  ".join(sorted("%s  %s" % (p["id"], p["name"]) for p in projects))
    if ID_RE.match(ref):
        p = by_id.get(ref.upper())
        if p:
            return p["id"], p["name"]
        raise SystemExit("Project id %s is not available to this user (wrong id, no access, or the "
                         "project is not loaded). Projects visible to this user:\n  %s" % (ref, listing))
    hits = [p for p in projects if p["name"] == ref] or \
           [p for p in projects if p["name"].lower() == ref.lower()]
    if len(hits) == 1:
        return hits[0]["id"], hits[0]["name"]
    if len(hits) > 1:
        raise SystemExit("Project name %r is ambiguous; use one of the IDs: %s"
                         % (ref, ", ".join(p["id"] for p in hits)))
    raise SystemExit("No project named %r. Projects visible to this user:\n  %s" % (ref, listing))


def search_objects(client: Client, project_id: str, obj_type: int, engine="metadata",
                   name=None, page=1000):
    """All objects of one type in a project.

    engine="metadata": POST+GET /api/metadataSearches/results. This is the
      Intelligence Server metadata search (what mstrio-py uses). It also
      returns hidden objects and does not depend on the search index.
    engine="quick": GET /api/searches/results (index-based quick search).
    """
    out = []
    if engine == "metadata":
        params = {"type": obj_type, "domain": 2}  # 2 = project domain
        if name is not None:
            params.update(name=name, pattern=2)   # 2 = exactly
        r = client.request("POST", "/api/metadataSearches/results", project_id, retry=True, params=params)
        if r.status_code not in (200, 201):
            raise ApiError("metadata search failed: %s (you can try --search quick)" % describe(r))
        created = r.json()
        search_id = created["id"]
        total = _int_or_none(created.get("totalItems"))   # authoritative count
        offset = 0
        while True:
            r = client.request("GET", "/api/metadataSearches/results", project_id,
                               params={"searchId": search_id, "offset": offset, "limit": page})
            if r.status_code != 200:
                raise ApiError("metadata search results failed: %s" % describe(r))
            j = r.json()
            res = j if isinstance(j, list) else j.get("result", [])
            out.extend(res)
            offset += len(res)
            if total is None:
                total = _int_or_none(r.headers.get("x-mstr-total-count"))
            if not res or (total is not None and offset >= total):
                break
    else:
        offset = 0
        while True:
            params = {"type": obj_type, "offset": offset, "limit": page, "getAncestors": "false"}
            if name is not None:
                params.update(name=name, pattern=2)
            j = client.get_json("/api/searches/results", project_id, params=params)
            res = j.get("result", [])
            out.extend(res)
            offset += len(res)
            if not res or offset >= int(j.get("totalItems") or 0):
                break
    seen, unique = set(), []
    for o in out:
        if o.get("id") not in seen:
            seen.add(o.get("id"))
            o.setdefault("type", obj_type)
            unique.append(o)
    return unique


def get_recipients(client: Client, project_id: str, object_id: str):
    """-> (recipients list, None) or (None, error text)."""
    try:
        r = client.request("GET", "/api/library/%s" % object_id, project_id)
        if r.status_code == 200:
            return r.json().get("recipients") or [], None
    except (ApiError, ValueError) as err:
        return None, str(err)
    return None, describe(r)


def get_object(client: Client, project_id: str | None, object_id: str, obj_type: int):
    """-> (info dict | None, status, error text | None). status is 200, "missing"
    (404 ERR004: no such object) or the HTTP status of any other failure. Other
    404s (e.g. ERR001 "project not loaded") are failures, not a missing object."""
    try:
        r = client.request("GET", "/api/objects/%s" % object_id, project_id, params={"type": obj_type})
        if r.status_code == 200:
            return r.json(), 200, None
    except (ApiError, ValueError) as err:
        return None, 0, str(err)
    code = None
    try:
        code = (r.json() or {}).get("code")
    except ValueError:
        pass
    if r.status_code == 404 and code == "ERR004":
        return None, "missing", describe(r)
    return None, r.status_code, describe(r)


def run_parallel(func, items, workers, label):
    """Map func over items (order kept) with a progress line every 50 items."""
    results = [None] * len(items)
    done = [0]
    lock = threading.Lock()

    def one(i):
        results[i] = func(items[i])
        with lock:
            done[0] += 1
            if done[0] % 50 == 0 or done[0] == len(items):
                log("  %s: %d/%d" % (label, done[0], len(items)))

    if workers <= 1:
        for i in range(len(items)):
            one(i)
    else:
        pool = ThreadPoolExecutor(max_workers=workers)
        try:
            list(pool.map(one, range(len(items))))
        except KeyboardInterrupt:
            try:
                pool.shutdown(wait=False, cancel_futures=True)   # Python 3.9+
            except TypeError:
                pool.shutdown(wait=False)
            raise
        pool.shutdown()
    return results


# --------------------------------------------------------------------------- export

def parse_types(value: str):
    parts = [p.strip().lower() for p in (value or "").split(",") if p.strip()]
    if "all" in parts:
        return list(TYPE_CHOICES)
    bad = [p for p in parts if p not in TYPE_CHOICES]
    if bad or not parts:
        usage_error("--types takes a comma list of %s (or 'all'); got %r" % (", ".join(TYPE_CHOICES), value))
    return parts


def content_group_note(client: Client, project_id: str):
    """Content groups are a second, separate way to put items in Library. This
    only reports whether any exist for the project; it does not copy them."""
    try:
        r = client.request("GET", "/api/contentGroups")
        if r.status_code != 200:
            return {"checked": False, "detail": describe(r)}
        j = r.json()
        if isinstance(j, dict):
            groups = j.get("contentGroups", [])
        else:   # the spec documents a bare array of {contentGroups: [...]}
            groups = [g for x in j if isinstance(x, dict) for g in x.get("contentGroups", [])]
        found = []
        for g in groups:
            rr = client.request("GET", "/api/contentGroups/%s/contents" % g["id"], params={"projectId": project_id})
            if rr.status_code != 200:
                continue
            j = rr.json() or {}
            items = next((v for k, v in j.items() if k.upper() == project_id.upper()), []) if isinstance(j, dict) else []
            if items:
                found.append({"id": g["id"], "name": g.get("name"), "items": len(items),
                              "recipients": len(g.get("recipients") or [])})
        return {"checked": True, "groups_with_content": found}
    except Exception as err:   # optional check: never lose the export over it
        return {"checked": False, "detail": "%s: %s" % (type(err).__name__, err)}


def cmd_export(args, client: Client) -> int:
    project_id, project_name = resolve_project(client, args.project)
    kinds = [t[:-1] for t in parse_types(args.types)]   # 'dashboards' -> 'dashboard'
    log("Source project: %s (%s)" % (project_name, project_id))

    objects = []
    for obj_type in sorted({KIND_OBJECT_TYPE[k] for k in kinds}, reverse=True):
        found = search_objects(client, project_id, obj_type, engine=args.search)
        for o in found:
            kind = classify(o, obj_type)
            if kind in kinds:
                objects.append({"id": o["id"], "name": o.get("name") or "", "kind": kind,
                                "type": o.get("type", obj_type), "subtype": o.get("subtype")})
    per_kind = collections.Counter(o["kind"] for o in objects)
    log("Objects to check: %d (%s)" % (len(objects), ", ".join("%s %d" % kv for kv in sorted(per_kind.items()))))

    results = run_parallel(lambda o: get_recipients(client, project_id, o["id"]),
                           objects, args.workers, "recipients read")

    published, errors = [], []
    for o, (recips, err) in zip(objects, results):
        if err is not None:
            errors.append({"document_id": o["id"], "document_name": o["name"], "document_kind": o["kind"],
                           "error": err})
            continue
        if recips:
            o["recipients"] = [{"id": x["id"], "name": x.get("name") or "",
                                "type": recipient_type(x.get("subtype")), "subtype": x.get("subtype")}
                               for x in recips]
            published.append(o)

    if not args.no_paths:
        for o in published:
            info, _status, _err = get_object(client, project_id, o["id"], o["type"])
            o["path"] = folder_path(info.get("ancestors")) if info else ""

    rows = [{"document_id": o["id"], "document_name": o["name"], "document_kind": o["kind"],
             "subtype": o["subtype"], "recipient_id": r["id"], "recipient_name": r["name"],
             "recipient_type": r["type"], "object_type": o["type"], "folder_path": o.get("path", ""),
             "source_project_id": project_id, "source_project_name": project_name}
            for o in published for r in o["recipients"]]

    by_recipient = collections.OrderedDict()
    for o in published:
        for r in o["recipients"]:
            entry = by_recipient.setdefault(r["id"], {"id": r["id"], "name": r["name"], "type": r["type"],
                                                      "documents": []})
            entry["documents"].append({"id": o["id"], "name": o["name"], "kind": o["kind"],
                                       "path": o.get("path", "")})
    recipients_sorted = sorted(by_recipient.values(),
                               key=lambda e: (e["type"] != "group", -len(e["documents"]), e["name"].lower()))

    cg = None if args.skip_content_groups else content_group_note(client, project_id)

    stem = stem_of(args.out)
    csv_path, json_path = stem + ".csv", stem + ".json"
    os.makedirs(os.path.dirname(os.path.abspath(csv_path)), exist_ok=True)
    write_csv(csv_path, CSV_FIELDS, rows)
    summary = {
        "objects_checked": len(objects),
        "objects_by_kind": dict(per_kind),
        "published_objects": len(published),
        "publication_rows": len(rows),
        "user_grants": sum(r["recipient_type"] == "user" for r in rows),
        "group_grants": sum(r["recipient_type"] == "group" for r in rows),
        "distinct_recipients": len(by_recipient),
        "read_errors": len(errors),
    }
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({"tool": "strategy_library_publications.py %s" % __version__, "generated_at": now_iso(),
                   "base_url": client.base, "exported_by": client.user_name,
                   "source_project": {"id": project_id, "name": project_name},
                   "types": kinds, "search_engine": args.search, "summary": summary,
                   "objects": published, "by_recipient": recipients_sorted,
                   "errors": errors, "content_groups": cg}, f, indent=1, ensure_ascii=False)
    written = [csv_path, json_path]
    if errors:
        write_csv(stem + ".errors.csv", ["document_id", "document_name", "document_kind", "error"], errors)
        written.append(stem + ".errors.csv")
    if args.by_recipient:
        brows = [{"recipient_type": e["type"], "recipient_id": e["id"], "recipient_name": e["name"],
                  "document_count": len(e["documents"]), "document_id": d["id"], "document_name": d["name"],
                  "document_kind": d["kind"], "folder_path": d["path"]}
                 for e in recipients_sorted for d in e["documents"]]
        write_csv(stem + ".by_recipient.csv", ["recipient_type", "recipient_id", "recipient_name",
                                               "document_count", "document_id", "document_name",
                                               "document_kind", "folder_path"], brows)
        written.append(stem + ".by_recipient.csv")

    # ---- report
    print("Library publications in project '%s' (%s)" % (project_name, project_id))
    print("  objects checked:        %d  (%s)" % (len(objects), ", ".join("%s %d" % kv for kv in sorted(per_kind.items()))))
    print("  published objects:      %d" % len(published))
    print("  publication rows:       %d  (users %d, groups %d)" % (len(rows), summary["user_grants"], summary["group_grants"]))
    print("  distinct recipients:    %d" % len(by_recipient))
    print("  read errors:            %d%s" % (len(errors), "  (see %s.errors.csv)" % stem if errors else ""))
    if cg and cg.get("checked") and cg.get("groups_with_content"):
        print("  NOTE: %d content group(s) also place items from this project in Library; content groups "
              "are separate and are not covered by this export." % len(cg["groups_with_content"]))
    print()
    print("Per-recipient rollup (direct grants only; members of a group are not listed individually):")
    if not recipients_sorted:
        print("  (nothing is published in this project)")
    limit = None if args.by_recipient else 40
    print("  %-6s %-32s  %-34s %s" % ("TYPE", "RECIPIENT ID", "NAME", "OBJECTS"))
    for e in recipients_sorted[:limit]:
        print("  %-6s %-32s  %-34s %d" % (e["type"], e["id"], e["name"][:34], len(e["documents"])))
        if args.by_recipient:
            for d in sorted(e["documents"], key=lambda d: (d["kind"], d["name"].lower())):
                print("         - [%s] %s  (%s)%s" % (d["kind"], d["name"], d["id"],
                                                     "  in " + d["path"] if d["path"] else ""))
    if limit and len(recipients_sorted) > limit:
        print("  ... %d more recipients (use --by-recipient, or see the CSV/JSON)" % (len(recipients_sorted) - limit))
    unchecked = [t for t in TYPE_CHOICES if t[:-1] not in kinds]
    if unchecked:
        print("\n(Not checked: %s. These can be in Library too; use --types all to include them.)"
              % ", ".join(unchecked))
    print("\nWritten: " + ", ".join(written))
    return EXIT_PARTIAL if errors else EXIT_OK


# --------------------------------------------------------------------------- replicate

_ALIASES = {
    "document_id": ("document_id", "object_id", "id"),
    "document_name": ("document_name", "object_name", "name"),
    "document_kind": ("document_kind", "object_kind", "kind"),
    "subtype": ("subtype", "object_subtype"),
    "object_type": ("object_type", "type"),
    "folder_path": ("folder_path", "path"),
    "recipient_id": ("recipient_id",),
    "recipient_name": ("recipient_name",),
    "recipient_type": ("recipient_type",),
    "source_project_id": ("source_project_id",),
    "source_project_name": ("source_project_name",),
}


_TEXT_FIELDS = {"document_name", "folder_path", "recipient_name", "source_project_name"}


def _field(row: dict, key: str) -> str:
    """IDs, codes and numbers are stripped; names and paths are kept as written
    (an object name can legitimately start or end with a space)."""
    for alias in _ALIASES[key]:
        v = row.get(alias)
        if v not in (None, ""):
            return _csv_unsafe(str(v)) if key in _TEXT_FIELDS else str(v).strip()
    return ""


def _int_or_none(v):
    """'55' / 55 / '55.0' (a CSV re-saved by Excel) -> 55; anything else -> None."""
    try:
        return int(v)
    except (TypeError, ValueError):
        try:
            return int(float(v))
        except (TypeError, ValueError, OverflowError):
            return None


def load_mapping(path: str):
    """Read the export CSV (or JSON). Returns (source dict, objects, problems)."""
    objects = collections.OrderedDict()
    problems = []
    source = {"id": "", "name": ""}

    def add(oid, name, kind, obj_type, subtype, fpath, rid, rname, rtype, where):
        if not ID_RE.match(oid or ""):
            problems.append("%s: invalid document id %r (skipped)" % (where, oid))
            return
        if not ID_RE.match(rid or ""):
            problems.append("%s: invalid recipient id %r (skipped)" % (where, rid))
            return
        oid, rid = oid.upper(), rid.upper()
        # type_known=False: a trimmed mapping without object_type/kind. Such a row
        # is tried as a document (55) first and as a report (3) in replicate.
        known = _int_or_none(obj_type) or KIND_OBJECT_TYPE.get(kind)
        o = objects.setdefault(oid, {"id": oid, "name": name, "kind": kind, "type": known or TYPE_DOCUMENT,
                                     "type_known": bool(known), "subtype": _int_or_none(subtype),
                                     "path": fpath, "recipients": collections.OrderedDict()})
        o["recipients"].setdefault(rid, {"id": rid, "name": rname, "type": rtype})

    if path.lower().endswith(".json"):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        source = data.get("source_project") or source
        for i, o in enumerate(data.get("objects", [])):
            for r in o.get("recipients", []):
                add(o.get("id"), o.get("name", ""), o.get("kind", ""), o.get("type"), o.get("subtype"),
                    o.get("path", ""), r.get("id"), r.get("name", ""), r.get("type", ""), "objects[%d]" % i)
    else:
        with open(path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            if not reader.fieldnames or not any(a in reader.fieldnames for a in _ALIASES["document_id"]) \
                    or "recipient_id" not in reader.fieldnames:
                raise SystemExit("%s: needs at least the columns document_id and recipient_id" % path)
            for n, row in enumerate(reader, start=2):
                if not any((v or "").strip() for v in row.values() if isinstance(v, str)):
                    continue
                if not source["id"] and _field(row, "source_project_id"):
                    source = {"id": _field(row, "source_project_id"), "name": _field(row, "source_project_name")}
                add(_field(row, "document_id"), _field(row, "document_name"), _field(row, "document_kind"),
                    _field(row, "object_type"), _field(row, "subtype"), _field(row, "folder_path"),
                    _field(row, "recipient_id"), _field(row, "recipient_name"), _field(row, "recipient_type"),
                    "line %d" % n)
    return source, objects, problems


def find_by_name_and_path(client: Client, project_id: str, obj: dict):
    """Fallback when the object id does not exist in the target: same type,
    exact name and (when the mapping has it) the same folder path."""
    if not obj["name"]:
        return None, "no name in the mapping to match on"
    try:
        cands = search_objects(client, project_id, obj["type"], engine="metadata", name=obj["name"])
    except ApiError as err:
        return None, "name search failed: %s" % err
    cands = [c for c in cands if c.get("name") == obj["name"]
             and (not obj["kind"] or classify(c, obj["type"]) == obj["kind"])]
    if obj["path"]:
        with_path = []
        for c in cands:
            info, _s, _e = get_object(client, project_id, c["id"], obj["type"])
            if info and folder_path(info.get("ancestors")) == obj["path"]:
                with_path.append(c)
        cands, how = with_path, "name + folder path"
    else:
        how = "name only (the mapping has no folder path)"
    if len(cands) == 1:
        return cands[0]["id"], "matched by %s" % how
    if not cands:
        return None, "no object with the same %s" % how.split(" (")[0]
    return None, "ambiguous: %d objects with the same %s" % (len(cands), how.split(" (")[0])


def publish_missing(client: Client, project_id: str, obj: dict, target_obj_id: str, missing, current_ids):
    """POST the missing recipients (groups stay groups), then read back.
    Returns (after_ids | None, notes list)."""
    notes = []
    body = {"id": target_obj_id, "recipients": [{"id": rid} for rid in missing]}
    if obj["type"] == TYPE_REPORT:
        body["type"] = "report_definition"
    try:
        r = client.request("POST", "/api/library", project_id, json=body)
        if r.status_code not in (200, 201, 204):
            notes.append("POST /api/library returned %s" % describe(r))
    except ApiError as err:
        notes.append("POST /api/library: %s" % err)
    after, err = get_recipients(client, project_id, target_obj_id)
    if err is not None:
        notes.append("verification read failed: %s" % err)
        return None, notes
    after_ids = {x["id"].upper() for x in after}
    lost = set(current_ids) - after_ids
    if lost:
        # POST /api/library is additive (verified live, 2026). Defensive only: if
        # a server ever treats it as "replace", put back what was there before.
        notes.append("POST dropped %d existing recipient(s); restoring them" % len(lost))
        log("WARNING: publishing %s removed %d existing recipient(s); restoring them" % (target_obj_id, len(lost)))
        body["recipients"] = [{"id": rid} for rid in sorted(set(current_ids) | set(missing))]
        try:
            client.request("POST", "/api/library", project_id, json=body)
        except ApiError as err2:
            notes.append("restore POST: %s" % err2)
        after, err = get_recipients(client, project_id, target_obj_id)
        if err is not None:
            notes.append("verification read failed: %s" % err)
            return None, notes
        after_ids = {x["id"].upper() for x in after}
        still_lost = set(current_ids) - after_ids
        if still_lost:
            notes.append("COULD NOT RESTORE: %s" % ", ".join(sorted(still_lost)))
    return after_ids, notes


def cmd_replicate(args, client: Client) -> int:
    source, objects, problems = load_mapping(args.mapping)
    target_id, target_name = resolve_project(client, args.target_project)
    mode = "APPLY" if args.apply else "DRY RUN (read-only; add --apply to publish)"
    log("Mapping: %s  (%d objects, %d grants; source project %s)"
        % (args.mapping, len(objects), sum(len(o["recipients"]) for o in objects.values()),
           source.get("name") or source.get("id") or "unknown"))
    log("Target project: %s (%s)   Mode: %s" % (target_name, target_id, mode))
    if source.get("id") and source["id"].upper() == target_id.upper():
        log("NOTE: the target is the same project as the source, so nothing should be missing.")
    for p in problems:
        log("WARNING: mapping " + p)

    # 1. do the recipients exist in this environment? (users/groups are type 34)
    recipient_status = {}
    all_rids = collections.OrderedDict((rid, r) for o in objects.values() for rid, r in o["recipients"].items())
    if not args.skip_recipient_check:
        for rid in all_rids:
            info, status, _err = get_object(client, None, rid, TYPE_USER_OR_GROUP)
            if info:
                recipient_status[rid] = "ok"
                actual = recipient_type(info.get("subtype"))
                if all_rids[rid]["type"] and all_rids[rid]["type"] != actual:
                    log("WARNING: recipient %s is a %s, the mapping says %s" % (rid, actual, all_rids[rid]["type"]))
                all_rids[rid]["type"] = actual
                all_rids[rid]["name"] = all_rids[rid]["name"] or info.get("name", "")
            elif status == "missing":
                recipient_status[rid] = "not_found"
            else:
                recipient_status[rid] = "unverified"   # e.g. 403 for a non-admin: still attempted
        nf = [r for r, s in recipient_status.items() if s == "not_found"]
        unv = [r for r, s in recipient_status.items() if s == "unverified"]
        if nf:
            log("WARNING: %d recipient(s) do not exist in this environment and will be skipped" % len(nf))
        if unv:
            log("NOTE: %d recipient(s) could not be looked up (no permission?); they will still be tried" % len(unv))

    # 2. per object: exists? current recipients? diff; optionally publish + verify
    report = []
    c = collections.Counter()
    todo_lines, problem_lines = [], []
    for obj in objects.values():
        c["objects"] += 1
        info, status, err = get_object(client, target_id, obj["id"], obj["type"])
        if status == "missing" and not obj["type_known"]:
            info, status, err = get_object(client, target_id, obj["id"], TYPE_REPORT)
            if info:
                obj["type"], obj["kind"] = TYPE_REPORT, "report"
        if info:   # a trimmed mapping has no name/kind: take them from the target
            obj["name"] = obj["name"] or info.get("name", "")
            obj["kind"] = obj["kind"] or classify(info, obj["type"]) or ""
        base = {"document_id": obj["id"], "document_name": obj["name"], "document_kind": obj["kind"]}

        def emit(rid, status, detail="", target_obj_id=""):
            r = all_rids[rid]
            report.append(dict(base, target_document_id=target_obj_id, recipient_id=rid,
                               recipient_name=r["name"], recipient_type=r["type"], status=status, detail=detail))
            c["grant:" + status] += 1

        target_obj_id, match_note = None, ""
        if info:
            target_obj_id = obj["id"]
            c["found_same_id"] += 1
            if obj["name"] and info.get("name") != obj["name"]:
                match_note = "same id, renamed in target to %r" % info.get("name")
        elif status == "missing":
            if args.match_by_name:
                target_obj_id, match_note = find_by_name_and_path(client, target_id, obj)
            else:
                match_note = "not in target project (try --match-by-name)"
            if target_obj_id:
                c["found_by_name"] += 1
                match_note = "id %s not in target; %s -> %s" % (obj["id"], match_note, target_obj_id)
        else:
            match_note = "lookup failed: %s" % err
        if not target_obj_id:
            c["objects_unresolved"] += 1
            problem_lines.append("  [object missing] %s (%s): %s" % (obj["name"], obj["id"], match_note))
            for rid in obj["recipients"]:
                emit(rid, "object_missing", match_note)
            continue
        if match_note:
            log("  %s (%s): %s" % (obj["name"], obj["id"], match_note))

        current, err = get_recipients(client, target_id, target_obj_id)
        if err is not None:
            c["objects_unresolved"] += 1
            problem_lines.append("  [read error] %s (%s): %s" % (obj["name"], target_obj_id, err))
            for rid in obj["recipients"]:
                emit(rid, "read_error", err, target_obj_id)
            continue
        current_ids = {x["id"].upper() for x in current}
        extra = current_ids - set(obj["recipients"])
        c["extra_in_target"] += len(extra)

        missing = []
        for rid in obj["recipients"]:
            if recipient_status.get(rid) == "not_found":
                emit(rid, "recipient_not_found", "no such user/group in this environment", target_obj_id)
                problem_lines.append("  [recipient missing] %s (%s) on %s" % (all_rids[rid]["name"], rid, obj["name"]))
            elif rid in current_ids:
                emit(rid, "already_present", "", target_obj_id)
            else:
                missing.append(rid)
        if not missing:
            continue
        c["objects_needing_publish"] += 1
        names = ", ".join("%s %s" % (all_rids[r]["type"] or "?", all_rids[r]["name"] or r) for r in missing)
        line = "  %s (%s) <- %s" % (obj["name"], target_obj_id, names)

        if not args.apply:
            todo_lines.append(line)
            for rid in missing:
                emit(rid, "to_add", "dry run", target_obj_id)
            continue

        after_ids, notes = publish_missing(client, target_id, obj, target_obj_id, missing, current_ids)
        detail = "; ".join(notes)
        if after_ids is None:
            c["objects_failed"] += 1
            todo_lines.append(line + "   [NOT VERIFIED]")
            problem_lines.append("  [not verified] %s (%s): %s" % (obj["name"], target_obj_id, detail))
            for rid in missing:
                emit(rid, "not_verified", detail, target_obj_id)
            continue
        ok = [rid for rid in missing if rid in after_ids]
        bad = [rid for rid in missing if rid not in after_ids]
        todo_lines.append(line + ("   [ok, verified]" if not bad else "   [FAILED for %d]" % len(bad)))
        for rid in ok:
            emit(rid, "added_verified", detail, target_obj_id)
        for rid in bad:
            emit(rid, "add_failed", detail or "recipient not present after POST", target_obj_id)
        if bad or "COULD NOT RESTORE" in detail:
            c["objects_failed"] += 1
            problem_lines.append("  [publish failed] %s (%s): %s" % (obj["name"], target_obj_id, detail or "not verified"))

    report_path = args.report or (stem_of(args.mapping) + ".replicate_report.csv")
    write_csv(report_path, ["document_id", "document_name", "document_kind", "target_document_id",
                            "recipient_id", "recipient_name", "recipient_type", "status", "detail"], report)

    grants = sum(len(o["recipients"]) for o in objects.values())
    print("Replicate %s -> target project '%s' (%s)" % ("APPLY" if args.apply else "DRY RUN", target_name, target_id))
    print("  objects in mapping:                 %d" % c["objects"])
    print("    found in target (same id):        %d" % c["found_same_id"])
    if args.match_by_name:
        print("    found by name/path:               %d" % c["found_by_name"])
    print("    missing / unreadable in target:   %d" % c["objects_unresolved"])
    print("  grants in mapping (object x recipient): %d" % grants)
    print("    already present in target:        %d" % c["grant:already_present"])
    if args.apply:
        print("    added and verified:               %d" % c["grant:added_verified"])
        print("    failed / not verified:            %d" % (c["grant:add_failed"] + c["grant:not_verified"]))
    else:
        print("    missing -> would be added:        %d  (on %d objects; run with --apply)"
              % (c["grant:to_add"], c["objects_needing_publish"]))
    print("    recipient not found:              %d" % c["grant:recipient_not_found"])
    print("    object missing / read error:      %d" % (c["grant:object_missing"] + c["grant:read_error"]))
    print("  recipients in target but not in mapping: %d (left as is; this tool never unpublishes)"
          % c["extra_in_target"])
    if problems:
        print("  mapping rows skipped (invalid ids): %d" % len(problems))
    if todo_lines:
        print("\n%s:" % ("Publish results" if args.apply else "Would publish (missing in target)"))
        print("\n".join(todo_lines[:60]))
        if len(todo_lines) > 60:
            print("  ... %d more (see the report)" % (len(todo_lines) - 60))
    if problem_lines:
        print("\nProblems:")
        print("\n".join(problem_lines[:60]))
        if len(problem_lines) > 60:
            print("  ... %d more (see the report)" % (len(problem_lines) - 60))
    print("\nReport: %s" % report_path)

    if c["objects_failed"] or c["grant:add_failed"] or c["grant:not_verified"]:
        return EXIT_APPLY_FAILED
    if c["objects_unresolved"] or c["grant:recipient_not_found"] or problems:
        return EXIT_PARTIAL
    return EXIT_OK


# --------------------------------------------------------------------------- CLI

def parse_login_mode(value) -> int:
    v = str(value).strip().lower()
    if v.isdigit():
        return int(v)
    if v in LOGIN_MODES:
        return LOGIN_MODES[v]
    usage_error("Unknown login mode %r (use 1, 16, 4096, 8 or standard/ldap/apitoken/guest)" % value)


def ssl_setting(value):
    if value is None:
        return True
    v = str(value).strip()
    if v.lower() in ("0", "false", "no", "off"):
        return False
    if v.lower() in ("", "1", "true", "yes", "on"):
        return True
    return v  # path to a CA bundle


def build_parser():
    p = argparse.ArgumentParser(
        description="Export which dashboards/documents are published to which users and user groups "
                    "in a Strategy project, and replicate those Library publications in another project.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Environment: MSTR_BASE, MSTR_USER, MSTR_PASSWORD, MSTR_LOGIN_MODE, MSTR_API_TOKEN, "
               "MSTR_SSL_VERIFY.\nExit codes: 0 ok, 1 fatal, 2 usage, 3 some items unresolved/unreadable, "
               "4 publish or verification failed.")
    p.add_argument("--version", action="version", version="%(prog)s " + __version__)
    common = argparse.ArgumentParser(add_help=False)
    g = common.add_argument_group("connection")
    g.add_argument("--base-url", default=os.environ.get("MSTR_BASE"),
                   help="Library URL, e.g. https://host/MicroStrategyLibrary (env MSTR_BASE)")
    g.add_argument("--username", default=os.environ.get("MSTR_USER"), help="(env MSTR_USER)")
    g.add_argument("--login-mode", default=os.environ.get("MSTR_LOGIN_MODE", "1"),
                   help="1 standard, 16 LDAP, 4096 API token, 8 guest (env MSTR_LOGIN_MODE; default 1)")
    g.add_argument("--auth-method", default=os.environ.get("MSTR_AUTH_METHOD", "auto"),
                   choices=("auto", "password", "ldap", "anonymous", "api-token", "sso", "identity-token", "oidc"),
                   help="auto (default: --login-mode / credentials, else a cached browser session or saved API "
                        "token, else browser single sign-on), or force one (env MSTR_AUTH_METHOD)")
    g.add_argument("--ssl-verify", default=os.environ.get("MSTR_SSL_VERIFY"),
                   help="'0' to disable certificate checks, or a CA bundle path (env MSTR_SSL_VERIFY)")
    g.add_argument("--timeout", type=float, default=120.0, help="seconds per request (default 120)")
    g.add_argument("--retries", type=int, default=4, help="retries for 429/502/503/504 on reads (default 4)")

    sub = p.add_subparsers(dest="command", metavar="{export,replicate}")
    sub.required = True
    e = sub.add_parser("export", parents=[common], help="list who each object is published to (read-only)",
                       description="Enumerate the project's objects, read GET /api/library/{id} for each, "
                                   "and write one row per (object, recipient).")
    e.add_argument("--project", required=True, help="source project ID or exact name")
    e.add_argument("--types", default=",".join(DEFAULT_TYPES),
                   help="comma list of %s, or 'all' (default: %s)" % ("/".join(TYPE_CHOICES), ",".join(DEFAULT_TYPES)))
    e.add_argument("--out", default="library_publications.csv",
                   help="CSV path; a .json with the same name is written next to it (default library_publications.csv)")
    e.add_argument("--by-recipient", action="store_true",
                   help="print every recipient's objects and write <out>.by_recipient.csv")
    e.add_argument("--workers", type=int, default=1,
                   help="parallel GET /api/library calls (default 1 = sequential, gentlest on the server)")
    e.add_argument("--search", choices=("metadata", "quick"), default="metadata",
                   help="object enumeration: metadata search (default, includes hidden objects) or quick search")
    e.add_argument("--no-paths", action="store_true", help="skip the folder-path lookup for published objects")
    e.add_argument("--skip-content-groups", action="store_true", help="skip the content-group check")

    r = sub.add_parser("replicate", parents=[common],
                       help="publish the mapping's grants in a target project (dry run unless --apply)",
                       description="For each object in the mapping: check it exists in the target project, read "
                                   "its current recipients there, and add only the missing ones. Never unpublishes.")
    r.add_argument("--mapping", required=True, help="CSV (or JSON) written by 'export', optionally hand-edited")
    r.add_argument("--target-project", required=True, help="target project ID or exact name")
    r.add_argument("--apply", action="store_true", help="actually publish (default is a read-only dry run)")
    r.add_argument("--match-by-name", action="store_true",
                   help="if an object id is not in the target, look for exactly one object with the same "
                        "type, name and folder path")
    r.add_argument("--skip-recipient-check", action="store_true",
                   help="do not look up each user/group before publishing")
    r.add_argument("--report", help="result CSV (default: <mapping>.replicate_report.csv)")
    return p


def main(argv=None) -> int:
    try:   # a name outside the console code page must not crash the report
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass
    args = build_parser().parse_args(argv)
    if not args.base_url:
        usage_error("Set MSTR_BASE or pass --base-url")
    login_mode = parse_login_mode(args.login_mode)
    api_token = os.environ.get("MSTR_API_TOKEN")
    password = None
    method = (args.auth_method or "auto").lower()
    if method == "ldap":
        method, login_mode = "password", 16
    elif method == "anonymous":
        method, login_mode = "password", 8
    elif method == "api-token" and api_token:
        method, login_mode = "password", 4096
    # Browser single sign-on, cached sessions and saved API tokens go through strategy_auth;
    # explicit credentials keep this script's own login (with its re-login on 401).
    sso_like = method in ("sso", "identity-token", "oidc", "api-token") or (
        method == "auto" and not args.username and login_mode not in (4096, 8) and not api_token)
    if not sso_like and login_mode == 4096 and not api_token:
        usage_error("Login mode 4096 needs MSTR_API_TOKEN")
    if not sso_like and login_mode not in (4096, 8):
        if not args.username:
            usage_error("Set MSTR_USER or pass --username")
        password = os.environ.get("MSTR_PASSWORD")
        if password is None:
            if not sys.stdin.isatty():
                usage_error("Set MSTR_PASSWORD (no terminal to prompt for it)")
            password = getpass.getpass("Password for %s: " % args.username)
    if getattr(args, "workers", 1) < 1:
        usage_error("--workers must be >= 1")

    client = Client(args.base_url, args.username, password, login_mode, api_token,
                    verify=ssl_setting(args.ssl_verify), timeout=args.timeout, retries=args.retries,
                    auth_method=method if sso_like else None)
    try:
        client.login()
        log("Logged in to %s as %s" % (client.base, client.user_name or args.username or "API token"))
        if args.command == "export":
            return cmd_export(args, client)
        return cmd_replicate(args, client)
    except ApiError as err:
        log("ERROR: %s" % err)
        return EXIT_FATAL
    except KeyboardInterrupt:
        log("Interrupted.")
        return EXIT_FATAL
    finally:
        client.logout()


if __name__ == "__main__":
    sys.exit(main())
