#!/usr/bin/env python3
"""
build_mosaic.py — discovery + build CLI for Strategy Mosaic semantic models.

Subcommands:
  auth-probe                 Confirm login + identity-token flow + project-scoped access.
  list-datasources           List database instances the user can see.
  list-namespaces            List schemas in a datasource.   --instance / --instance-id
  list-tables                List tables in a schema.         --instance --namespace
  describe-table             Columns + data types for a warehouse table.
  resolve-users              Resolve user IDs from names, usernames, emails, or roster files.
  search-objects             Quick Search wrapper for object IDs.
  get-model-object           Read Mosaic-contained or classic schema object definitions.
  patch-model-object         Changeset-backed object update with before/after support.
  create-users               Dry-run or create users from CSV/JSON/YAML rosters.
  build                      Create & commit a model from one or more sources.
  build-from-schema-objects  Build a Mosaic model from existing classic attribute/fact/metric IDs.
  merge-attributes           Conform differently-named FK columns by merging child expressions
                             into the parent attribute. Required for Kimball warehouses with
                             prefixed surrogate keys (i_item_sk vs ss_item_sk) where auto-
                             conformance via column-name identity won't fire.
  release-locks              Release stuck schemaEdit changesets owned by the current user.
  validate-model             Run the full post-build quality checklist (failures exit non-zero).
  validate-topology          Lightweight topology check — isolated attrs, fact-table coverage, misclassified numerics.
  discover                   Probe endpoint variants when the server version is unknown.

Authentication
~~~~~~~~~~~~~~
Two modes are supported:

1. **Direct login** (on-prem and tenants that expose POST /api/auth/login):
   pass --user + --password (or env MSTR_USER + MSTR_PASSWORD). The script
   logs in, runs the command, and logs out.

2. **Borrowed session** (Studio Cloud / SSO tenants where direct login isn't
   usable): pass --auth-token + --session-cookie + --ingress-cookie (or env
   MSTR_AUTH_TOKEN, MSTR_SESSION_COOKIE, MSTR_INGRESS_COOKIE), copied out of
   a logged-in browser via DevTools. The script reuses the session in-place;
   /auth/login and /auth/logout are skipped so the human's UI session is left
   intact. If a Modeling Service command needs an identity token and one is
   not provided, the script mints one in the borrowed session.

Other subcommands take optional --base / --project-id or read them from env
vars MSTR_BASE / MSTR_PROJECT_ID. Do not hardcode secrets in this file;
set MSTR_PASSWORD in the shell or keychain-backed environment.

The "build" subcommand can take --source repeatedly, each as "INSTANCE:SCHEMA:T1,T2,...":
    --source "Snowflake Prod:SALES:CUSTOMER,ORDER" --source "Oracle:FIN:INVOICE"

Column-type heuristics (override with --attr-cols / --metric-cols):
  numeric cols (int/float/numeric/decimal/double)     -> fact metric (SUM)
  everything else (varchar/text/date/id)              -> attribute (single key form)

This is the source of truth for the build-mosaic-model skill. When the server
rejects a path with 404, use `discover` to find the current variant on this
tenant's API and update ENDPOINT_CANDIDATES below.
"""
from __future__ import annotations
import argparse, csv, json, os, shutil, subprocess, sys, time, uuid
from typing import Any
import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import schema_object_translator as sot  # noqa: E402
import mosaic_safety as ms  # noqa: E402

# ── Configuration: all tenant values come from env vars or CLI flags ──────────
# No hardcoded tenant defaults. Required: MSTR_BASE, MSTR_USER, MSTR_PASSWORD.
# Optional: MSTR_PROJECT_ID (or resolve by name at runtime), MSTR_DEST_FOLDER_ID,
# MSTR_LOGIN_MODE (default 1 = standard). See README.md + .env.example.
DEFAULT_BASE        = os.environ.get("MSTR_BASE", "")
DEFAULT_PROJECT_ID  = os.environ.get("MSTR_PROJECT_ID", "")
DEFAULT_USER        = os.environ.get("MSTR_USER", "")
DEFAULT_PASSWORD    = os.environ.get("MSTR_PASSWORD", "")
DEFAULT_LOGIN_MODE  = int(os.environ.get("MSTR_LOGIN_MODE", "1"))
DEFAULT_DEST_FOLDER = os.environ.get("MSTR_DEST_FOLDER_ID", os.environ.get("MSTR_DEST_FOLDER", ""))
# Borrowed-session (Studio Cloud / SSO tenants where username+password login
# isn't usable). Copy the four values out of a logged-in browser session via
# DevTools → Network (X-MSTR-AuthToken header) and Application → Cookies
# (JSESSIONID + library-ingress). Identity token is optional — when omitted
# and a Modeling-Service-bound command runs, the script mints one using the
# borrowed session. See README.md.
DEFAULT_AUTH_TOKEN     = os.environ.get("MSTR_AUTH_TOKEN", "")
DEFAULT_IDENTITY_TOKEN = os.environ.get("MSTR_IDENTITY_TOKEN", "")
DEFAULT_SESSION_COOKIE = os.environ.get("MSTR_SESSION_COOKIE", "")
DEFAULT_INGRESS_COOKIE = os.environ.get("MSTR_INGRESS_COOKIE", "")
FORM_ID             = "45C11FA478E745FEA08D781CEA190FE5"   # Universal Strategy ID-form constant (all tenants)

# MicroStrategy REST paths have drifted across versions. Try these in order.
ENDPOINT_CANDIDATES = {
    "list_datasources": [
        "/api/datasources",
    ],
    "list_namespaces": [
        "/api/datasources/{id}/catalog/namespaces",
    ],
    # ns_id is base64(json({"ns":"<schemaName>"}))
    "list_tables": [
        "/api/datasources/{id}/catalog/namespaces/{ns_id}/tables",
    ],
    # tb_id is base64(json({"tbn":"<tableName>","ns":"<schemaName>"}))
    "describe_table": [
        "/api/datasources/{id}/catalog/tables/{tb_id}",
        "/api/datasources/{id}/catalog/namespaces/{ns_id}/tables/{tb_id}",
    ],
}

OPENAPI_CANDIDATES = [
    "/api/openapi.yaml",
    "/api/openapi.yml",
    "/api/openapi.json",
    "/api-docs/openapi.yaml",
    "/api-docs/swagger.json",
]

import base64 as _b64

def encode_ns_id(ns: str) -> str:
    return _b64.b64encode(json.dumps({"ns": ns}, separators=(",",":")).encode()).decode().rstrip("=") + "=="

def encode_tb_id(ns: str, tbn: str) -> str:
    raw = _b64.b64encode(json.dumps({"tbn": tbn, "ns": ns}, separators=(",",":")).encode()).decode()
    # pad to multiple of 4
    return raw + "="*((4 - len(raw)%4)%4)


def _load_json_arg(value, file_path=None) -> Any:
    if file_path:
        with open(file_path, encoding="utf-8") as f:
            return json.load(f)
    if value:
        return json.loads(value)
    return None


def _load_yaml(path: str) -> Any:
    """Load YAML without making PyYAML a hard dependency on macOS workstations."""
    try:
        import yaml
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f)
    except ModuleNotFoundError:
        ruby = shutil.which("ruby")
        if not ruby:
            die(f"{path}: YAML requires PyYAML or ruby. Convert the file to JSON or install PyYAML.")
        try:
            proc = subprocess.run(
                [ruby, "-ryaml", "-rjson", "-e", "puts JSON.generate(YAML.load_file(ARGV[0]))", path],
                check=True, capture_output=True, text=True,
            )
        except subprocess.CalledProcessError as exc:
            die(f"{path}: YAML parse failed: {exc.stderr.strip() or exc.stdout.strip()}")
        return json.loads(proc.stdout or "null")


def load_structured_file(path: str) -> Any:
    """Load JSON or YAML. CSV stays caller-specific because row semantics differ."""
    ext = path.lower().rsplit(".", 1)[-1]
    if ext == "json":
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    if ext in ("yaml", "yml"):
        return _load_yaml(path)
    die(f"{path}: expected .json, .yaml, or .yml")


def _parse_kv(items):
    out = {}
    for item in items or []:
        key, sep, value = item.partition("=")
        if not sep:
            die(f"bad key=value argument: {item}")
        out[key] = value
    return out

NUMERIC_TYPES = {"integer","int","bigint","smallint","tinyint","long","short",
                 "decimal","numeric","float","double","real","number","money",
                 "int64","int32","fixed_numeric"}
ID_COLUMN_SUFFIXES = ("_ID", "ID", "_KEY", "KEY", "_CD", "_CODE", "CODE",
                      "_NO", "NO", "_NUM", "NUM", "_NUMBER", "NUMBER",
                      "_SK", "SK")
NATURAL_NUMERIC_DIMS = ("YEAR", "MONTH", "QUARTER", "QTR", "WEEK", "DAY", "FISCAL")

import re as _re

def friendly_col(col: str) -> str:
    """CUSTOMER_NAME -> 'Customer Name', PO_NUMBER -> 'PO Number', ID -> 'ID'."""
    parts = col.replace("-", "_").split("_")
    out = []
    for p in parts:
        up = p.upper()
        if up in {"ID","PO","SKU","URL","API","IP","UID","GUID","USA","UK","EU","YTD","MTD"}:
            out.append(up)
        else:
            out.append(p.capitalize())
    return " ".join(out).strip()

def friendly_table(tname: str) -> str:
    """Strip common timestamp / prefix patterns and title-case. Returns the *short* label."""
    # Strip leading prefixes like SD_TECH_PENGUIN_20260413_2145_  or similar
    stripped = _re.sub(r"^[A-Z]+(?:_[A-Z]+)*_\d{6,}(?:_\d+)*_", "", tname)
    return friendly_col(stripped)


# ── Session helpers ───────────────────────────────────────────────────────────
class MSTR:
    def __init__(self, args):
        self.base    = args.base.rstrip("/")
        self.project = args.project_id
        self.user    = args.user
        self.pw      = args.password
        self.mode    = args.login_mode
        # Borrowed-session inputs: when set, MSTR will reuse an externally-held
        # session (e.g. tokens + cookies copied out of a logged-in browser) and
        # skip /auth/login and /auth/logout so the human's UI session is left
        # intact. Required for Studio Cloud (studio.strategy.com) where direct
        # username/password login is not exposed.
        self.preset_auth_token     = getattr(args, "auth_token", "") or ""
        self.preset_identity_token = getattr(args, "identity_token", "") or ""
        self.preset_session_cookie = getattr(args, "session_cookie", "") or ""
        self.preset_ingress_cookie = getattr(args, "ingress_cookie", "") or ""
        self.s       = requests.Session()
        self.s.headers.update({"Content-Type":"application/json","Accept":"application/json"})
        host = self.base.replace("https://","").replace("http://","").split("/")[0]
        if self.preset_session_cookie:
            self.s.cookies.set("JSESSIONID", self.preset_session_cookie, domain=host)
        if self.preset_ingress_cookie:
            self.s.cookies.set("library-ingress", self.preset_ingress_cookie, domain=host)
        self.verbose = args.verbose
        self.logged_in = False
        # True when this session was bootstrapped from caller-supplied tokens.
        # logout() and any "kill stale sessions" helpers must NOT delete this
        # session — it is owned by an external client (browser tab, CI runner).
        self.borrowed_session = False

    def login(self, *, identity: bool = False):
        # Borrowed-session mode: caller supplied an auth token already. Skip
        # /auth/login entirely; only mint an identity token if asked and not
        # already provided. /auth/logout is also disabled to protect the
        # external owner's session.
        if self.preset_auth_token:
            self.s.headers["X-MSTR-AuthToken"] = self.preset_auth_token
            if self.project:
                self.s.headers["X-MSTR-ProjectID"] = self.project
            if self.preset_identity_token:
                self.s.headers["X-MSTR-IdentityToken"] = self.preset_identity_token
            elif identity:
                r2 = self.s.post(f"{self.base}/api/auth/identityToken")
                if r2.ok:
                    id_tok = r2.headers.get("X-Mstr-Identitytoken") or r2.headers.get("X-MSTR-IdentityToken","")
                    if id_tok:
                        self.s.headers["X-MSTR-IdentityToken"] = id_tok
                    else:
                        print("[auth] WARN: /auth/identityToken returned 2xx but no token header. "
                              "Modeling Service changesets may fail. Pass --identity-token explicitly.",
                              file=sys.stderr)
                else:
                    print(f"[auth] WARN: identity-token mint failed ({r2.status_code}). "
                          "Modeling Service changesets will fail. Re-grab the cookies "
                          "(JSESSIONID + library-ingress) from a fresh browser session, "
                          "or pass --identity-token explicitly.",
                          file=sys.stderr)
            self.logged_in        = True
            self.borrowed_session = True
            if self.verbose:
                has_id = "X-MSTR-IdentityToken" in self.s.headers
                print(f"[auth] borrowed token={self.preset_auth_token[:12]}…  identity={'yes' if has_id else 'no'}",
                      file=sys.stderr)
            return
        if not self.pw:
            die("missing password. Set MSTR_PASSWORD or pass --password; do not store secrets in skill/memory files. "
                "(Studio Cloud users: pass --auth-token + --session-cookie + --ingress-cookie from a browser session.)")
        r = self.s.post(f"{self.base}/api/auth/login",
                        json={"username": self.user, "password": self.pw, "loginMode": self.mode})
        r.raise_for_status()
        tok = r.headers.get("X-Mstr-Authtoken") or r.headers.get("X-MSTR-AuthToken","")
        if not tok:
            die(f"login: no auth token in response headers: {dict(r.headers)}")
        self.s.headers["X-MSTR-AuthToken"] = tok
        self.s.headers["X-MSTR-ProjectID"] = self.project
        self.logged_in = True
        if identity:
            # Identity token is required for Mosaic data-model Modeling Service changesets,
            # but can break classic/project Modeling reads on some tenants.
            r2 = self.s.post(f"{self.base}/api/auth/identityToken")
            if r2.ok:
                id_tok = r2.headers.get("X-Mstr-Identitytoken") or r2.headers.get("X-MSTR-IdentityToken","")
                if id_tok:
                    self.s.headers["X-MSTR-IdentityToken"] = id_tok
                else:
                    print("[auth] WARN: /auth/identityToken returned 2xx but no token header. "
                          "Modeling Service changesets may fail.", file=sys.stderr)
            else:
                print(f"[auth] WARN: identity-token mint failed ({r2.status_code} {r2.text[:120]}). "
                      "Modeling Service changesets will fail.", file=sys.stderr)
        if self.verbose:
            print(f"[auth] token={tok[:12]}…  identity={'yes' if 'X-MSTR-IdentityToken' in self.s.headers else 'no'}", file=sys.stderr)

    # raw helpers
    def get(self, path, **kw):  return self.s.get(f"{self.base}{path}", **kw)
    def post(self, path, **kw): return self.s.post(f"{self.base}{path}", **kw)
    def put(self, path, **kw):  return self.s.put(f"{self.base}{path}", **kw)
    def patch(self, path, **kw): return self.s.patch(f"{self.base}{path}", **kw)
    def delete(self, path, **kw): return self.s.delete(f"{self.base}{path}", **kw)

    def logout(self):
        if not self.logged_in:
            return
        if self.borrowed_session:
            # The session belongs to whoever lent us the token (typically a
            # human's browser tab). DELETE /api/auth/login here would log them
            # out of their UI mid-task — never do that.
            self.logged_in = False
            return
        try:
            self.delete("/api/auth/login")
        except requests.RequestException:
            pass
        finally:
            self.logged_in = False

    def try_candidates(self, kind, **fmt) -> tuple[str, Any]:
        """Walk ENDPOINT_CANDIDATES[kind]; return (path_used, json_body) on first 2xx."""
        last_err = None
        for tmpl in ENDPOINT_CANDIDATES[kind]:
            path = tmpl.format(**fmt)
            r = self.get(path)
            if r.ok:
                return path, (r.json() if r.text else {})
            last_err = (path, r.status_code, r.text[:200])
            if self.verbose:
                print(f"[probe] {path} -> {r.status_code}", file=sys.stderr)
        die(f"{kind}: no working endpoint. last attempt: {last_err}")


def die(msg):
    print(f"FATAL: {msg}", file=sys.stderr)
    sys.exit(2)

def new_uuid() -> str:
    return str(uuid.uuid4()).upper().replace("-","")


# ── Discovery ─────────────────────────────────────────────────────────────────
def cmd_auth_probe(m: MSTR, args):
    """Confirm login + identity-token flow + project-scoped access.

    Studio Cloud (and some SSO tenants) accept the X-MSTR-AuthToken on
    /auth/* endpoints but reject project-scoped reads without the right
    cookies. Without a project-scoped probe, auth-probe will pass and
    list-datasources will 401 — a frustrating loop. So the probe also
    hits a project-scoped read and reports whether it succeeded.
    """
    m.login(identity=True)
    out: dict[str, object] = {
        "ok": True,
        "base": m.base,
        "project_id": m.project,
        "user": m.user,
        "has_auth_token": "X-MSTR-AuthToken" in m.s.headers,
        "has_identity_token": "X-MSTR-IdentityToken" in m.s.headers,
    }
    if m.project:
        # GET /api/folders/preDefined/7 = project-public root; cheap + present on every tenant.
        r = m.get(f"/api/folders/preDefined/7")
        out["project_access"] = bool(r.ok)
        if not r.ok:
            out["project_access_status"] = r.status_code
            try:
                body = r.json()
            except ValueError:
                body = r.text[:200]
            out["project_access_error"] = body
            out["project_access_hint"] = (
                "If using --auth-token, also pass --session-cookie (JSESSIONID) and "
                "--ingress-cookie (library-ingress) — Studio Cloud requires both."
            )
    else:
        out["project_access"] = "skipped"
        out["project_access_hint"] = "no --project-id supplied; cannot probe project-scoped APIs"
    print(json.dumps(out, indent=2))


def cmd_list_datasources(m: MSTR, args):
    m.login()
    path, body = m.try_candidates("list_datasources")
    # Normalize: most endpoints return {"datasources":[{id,name,...}]} or {"databaseInstances":[...]}
    items = body.get("datasources") or body.get("databaseInstances") or (body if isinstance(body,list) else [])
    rows = [{"id": it.get("id") or it.get("objectId"),
             "name": it.get("name"),
             "description": it.get("description",""),
             "databaseType": it.get("databaseType") or it.get("dbmsType") or ""}
            for it in items if isinstance(it, dict)]
    if args.name:
        rows = [r for r in rows if args.name.lower() in (r["name"] or "").lower()]
    print(f"# endpoint used: {path}", file=sys.stderr)
    print(json.dumps(rows, indent=2))


def resolve_instance_id(m: MSTR, name_or_id: str) -> str:
    """Accept either an ID (32-hex) or a name; return ID."""
    if len(name_or_id) == 32 and all(c in "0123456789ABCDEFabcdef" for c in name_or_id):
        return name_or_id.upper()
    _, body = m.try_candidates("list_datasources")
    items = body.get("datasources") or body.get("databaseInstances") or (body if isinstance(body,list) else [])
    hits = [it for it in items if isinstance(it, dict)
            and (it.get("name","").lower() == name_or_id.lower())]
    if not hits:
        # fuzzy
        hits = [it for it in items if isinstance(it, dict)
                and name_or_id.lower() in it.get("name","").lower()]
    if not hits:
        die(f"no datasource matches '{name_or_id}'")
    if len(hits) > 1:
        die(f"'{name_or_id}' is ambiguous: {[h.get('name') for h in hits]}. Pass --instance-id.")
    return (hits[0].get("id") or hits[0].get("objectId")).upper()


def cmd_list_namespaces(m: MSTR, args):
    m.login()
    ds_id = args.instance_id or resolve_instance_id(m, args.instance)
    path, body = m.try_candidates("list_namespaces", id=ds_id)
    # Normalize
    items = body.get("namespaces") or (body if isinstance(body, list) else [])
    rows = [{"name": it.get("name") if isinstance(it,dict) else it} for it in items]
    print(f"# endpoint used: {path}", file=sys.stderr)
    print(json.dumps(rows, indent=2))


def resolve_namespace_id(m: MSTR, ds_id: str, ns_name: str) -> str:
    """Look up namespaceId via catalog/namespaces, fall back to b64 encoding."""
    r = m.get(f"/api/datasources/{ds_id}/catalog/namespaces")
    if r.ok:
        for ns in (r.json().get("namespaces") or []):
            if ns.get("name","").lower() == ns_name.lower():
                return ns["id"]
    return encode_ns_id(ns_name)

def cmd_list_tables(m: MSTR, args):
    m.login()
    ds_id = args.instance_id or resolve_instance_id(m, args.instance)
    ns_id = resolve_namespace_id(m, ds_id, args.namespace)
    path, body = m.try_candidates("list_tables", id=ds_id, ns_id=ns_id)
    items = body.get("tables") or (body if isinstance(body, list) else [])
    rows = [{"name": it.get("name"),
             "id": it.get("id"),
             "namespace": it.get("namespace", args.namespace),
             "type": it.get("type","")} for it in items if isinstance(it,dict)]
    if args.match:
        rows = [r for r in rows if args.match.lower() in (r["name"] or "").lower()]
    print(f"# endpoint used: {path}", file=sys.stderr)
    print(json.dumps(rows, indent=2))


def cmd_describe_table(m: MSTR, args):
    m.login()
    ds_id = args.instance_id or resolve_instance_id(m, args.instance)
    ns_id = resolve_namespace_id(m, ds_id, args.namespace)
    tb_id = encode_tb_id(args.namespace, args.table)
    path, body = m.try_candidates("describe_table", id=ds_id, ns_id=ns_id, tb_id=tb_id)
    print(f"# endpoint used: {path}", file=sys.stderr)
    print(json.dumps(body, indent=2))


def cmd_describe_tables(m: MSTR, args):
    """Describe many tables in ONE login/logout cycle to avoid the project session cap.

    --source accepts `instanceId:namespace:table` (repeatable). Output is a JSON
    dict keyed by `namespace.table` with the raw describe payload per table.
    """
    m.login()
    out = {}
    for spec in args.source:
        try:
            ins, ns, tb = spec.split(":", 2)
        except ValueError:
            die(f"--source must be instanceId:namespace:table, got {spec!r}")
        ns_id = resolve_namespace_id(m, ins, ns)
        tb_id = encode_tb_id(ns, tb)
        path, body = m.try_candidates("describe_table", id=ins, ns_id=ns_id, tb_id=tb_id)
        out[f"{ns}.{tb}"] = body
        print(f"# {ns}.{tb} via {path}", file=sys.stderr)
    print(json.dumps(out, indent=2, default=str))


def cmd_kill_sessions(m: MSTR, args):
    """Best-effort: login + immediate DELETE, repeated, to reap stale auth tokens owned by this user.

    Does not affect interactive project sessions already opened by other processes; those reap on the
    iServer side (~30 min). Use as a low-risk first response when you hit iServerCode -2147072486.
    """
    killed = 0
    for _ in range(int(args.count)):
        r = m.s.post(f"{m.base}/api/auth/login",
                     json={"username": m.user, "password": m.pw, "loginMode": m.mode})
        if not r.ok:
            break
        tok = r.headers.get("X-MSTR-AuthToken") or r.headers.get("X-Mstr-Authtoken","")
        if not tok:
            break
        d = m.s.delete(f"{m.base}/api/auth/login", headers={"X-MSTR-AuthToken": tok})
        if d.status_code in (200, 204):
            killed += 1
    print(json.dumps({"attempted": int(args.count), "killed": killed}))


def cmd_release_locks(m: MSTR, args):
    """Release stuck Modeling Service changesets owned by the current user.

    If a build/wire script dies between open_cs() and commit_cs() (network blip,
    KeyboardInterrupt, killed process), the schemaEdit lock persists on the
    project and every subsequent open returns 8004cc41 until it ages out.
    There is no way to enumerate "all open changesets" via the public API, so
    this helper provokes the lock conflict, parses the LOCKID out of the error,
    verifies the lock belongs to the current user, and DELETEs the changeset.
    Repeats until open succeeds (in which case it discards the freshly-opened
    one too, leaving the project clean).
    """
    m.login()
    released: list[str] = []
    for _ in range(int(args.max_iters)):
        # schemaEdit must be in BOTH the body and the query param. Strategy
        # parses one or the other depending on path version; body-only opens
        # a non-schema changeset that never collides with the stale lock.
        r = m.post("/api/model/changesets?schemaEdit=true", json={"schemaEdit": True})
        if r.ok:
            cs = r.json().get("id")
            if cs:
                discard_cs(m, cs)
            break
        try:
            body = r.json()
        except ValueError:
            print(f"release-locks: unexpected response {r.status_code}: {r.text[:200]}", file=sys.stderr)
            break
        lockid = _extract_lockid_from_error(body)
        my_uid = (body or {}).get("errors", [{}])[0].get("additionalProperties", {}).get("userId")
        if not lockid:
            print(f"release-locks: no LOCKID in error: {format_mstr_error(r)}", file=sys.stderr)
            break
        if not _lock_owned_by_self(body, my_uid):
            print(f"release-locks: lock {lockid} not owned by current user; will age out", file=sys.stderr)
            break
        dr = m.delete(f"/api/model/changesets/{lockid}")
        if dr.status_code in (200, 204):
            released.append(lockid)
            print(f"release-locks: released {lockid}", file=sys.stderr)
        else:
            print(f"release-locks: failed to release {lockid}: {dr.status_code} {dr.text[:200]}", file=sys.stderr)
            break
    print(json.dumps({"released": released, "count": len(released)}, indent=2))


def cmd_discover(m: MSTR, args):
    """Probe every endpoint variant and print which one worked.
    Useful when porting this skill to a new MSTR version/tenant."""
    m.login()
    results = {}
    for kind, candidates in ENDPOINT_CANDIDATES.items():
        results[kind] = []
        for tmpl in candidates:
            # substitute with args if provided, else skip templated ones
            try:
                ns_id = encode_ns_id(args.namespace) if args.namespace else "PLACEHOLDER"
                tb_id = encode_tb_id(args.namespace, args.table) if (args.namespace and args.table) else "PLACEHOLDER"
                path = tmpl.format(id=args.instance_id or "PLACEHOLDER",
                                   ns_id=ns_id, tb_id=tb_id)
            except Exception:
                path = tmpl
            if "PLACEHOLDER" in path and kind != "list_datasources":
                results[kind].append({"path": tmpl, "skipped": "missing --instance-id/--namespace/--table"})
                continue
            r = m.get(path)
            results[kind].append({"path": path, "status": r.status_code,
                                  "ok": r.ok,
                                  "body_sample": (r.text[:200] if r.text else "")})
    print(json.dumps(results, indent=2))


def cmd_openapi_summary(m: MSTR, args):
    """Fetch the instance's machine-readable OpenAPI spec and summarize useful paths.

    The Swagger UI at /api-docs/ is a JS app. Current Strategy Library servers also
    expose the raw spec at /api/openapi.yaml; keep this probe because exact locations
    can differ across releases and customer-managed deployments.
    """
    last = None
    spec_text = None
    spec_path = None
    for path in OPENAPI_CANDIDATES:
        r = m.get(path)
        if r.ok and ("openapi:" in r.text[:1000] or '"openapi"' in r.text[:1000]):
            spec_text = r.text
            spec_path = path
            break
        last = {"path": path, "status": r.status_code, "body_sample": r.text[:120]}
    if spec_text is None:
        die(f"no OpenAPI spec found. last attempt: {last}")

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(spec_text)

    title = _re.search(r"^\s*title:\s*(.+)$", spec_text, _re.MULTILINE)
    version = _re.search(r"^\s*version:\s*[\"']?([^\"'\n]+)", spec_text, _re.MULTILINE)
    paths = _re.findall(r"^  (/api/[^:]+):\s*$", spec_text, _re.MULTILINE)
    tags = _re.findall(r"^- name:\s*(.+)$", spec_text, _re.MULTILINE)
    filters = args.path_filter or [
        "/api/model/dataModels",
        "/api/model/changesets",
        "/api/model/securityFilters",
        "/api/model/attributes",
        "/api/model/facts",
        "/api/model/tables",
        "/api/cubes",
        "/api/datasources",
        "/api/auth",
    ]
    selected = [p for p in paths if any(p.startswith(prefix) for prefix in filters)]
    print(json.dumps({
        "ok": True,
        "url": f"{m.base}{spec_path}",
        "saved_to": args.out,
        "openapi": bool(_re.search(r"^openapi:", spec_text, _re.MULTILINE)),
        "title": title.group(1).strip().strip('"') if title else None,
        "version": version.group(1).strip() if version else None,
        "path_count": len(paths),
        "tag_count": len(tags),
        "key_tags": [t for t in tags if t in {
            "Authentication", "Changesets", "Data Models", "Datasource Management",
            "Schema Modeling", "Security Filters", "Cubes", "Objects"
        }],
        "selected_paths": selected[: args.limit],
    }, indent=2))


def _get_openapi_text(m: MSTR, local_path=None):
    if local_path and os.path.exists(local_path):
        with open(local_path, encoding="utf-8") as f:
            return local_path, f.read()
    default_local = os.path.join(os.getcwd(), "openapi.yaml")
    if os.path.exists(default_local):
        with open(default_local, encoding="utf-8") as f:
            return default_local, f.read()
    for path in OPENAPI_CANDIDATES:
        r = m.get(path)
        if r.ok and ("openapi:" in r.text[:1000] or '"openapi"' in r.text[:1000]):
            return f"{m.base}{path}", r.text
    die("no OpenAPI spec found locally or at known tenant paths")


def cmd_openapi_search(m: MSTR, args):
    """Search the Strategy OpenAPI YAML without loading the entire spec into context."""
    source, text = _get_openapi_text(m, args.file)
    flags = 0 if args.case_sensitive else _re.IGNORECASE
    pat = _re.compile(args.pattern, flags)
    lines = text.splitlines()
    matches = []
    for idx, line in enumerate(lines, start=1):
        if pat.search(line):
            start = max(1, idx - args.context)
            end = min(len(lines), idx + args.context)
            matches.append({
                "line": idx,
                "text": line,
                "context": [{"line": i, "text": lines[i-1]} for i in range(start, end + 1)] if args.context else None,
            })
            if len(matches) >= args.limit:
                break
    print(json.dumps({
        "ok": True,
        "source": source,
        "pattern": args.pattern,
        "matches": matches,
        "truncated": len(matches) >= args.limit,
    }, indent=2))


def cmd_api_call(m: MSTR, args):
    """Generic Strategy REST call for workflows not yet wrapped by a subcommand."""
    if not args.no_auth:
        m.login(identity=args.identity_token)
    method = args.method.upper()
    if method == "DELETE" and not args.yes:
        die("DELETE requires --yes")
    path = args.path if args.path.startswith("/") else f"/{args.path}"
    params = _parse_kv(args.param)
    headers = _parse_kv(args.header)
    body = _load_json_arg(args.json, args.json_file)
    request = getattr(m.s, method.lower(), None)
    if request is None:
        die(f"unsupported method {method}")
    r = request(f"{m.base}{path}", params=params or None, headers=headers or None, json=body)
    out = {
        "ok": r.ok,
        "status": r.status_code,
        "url": r.url,
        "headers": {k: v for k, v in r.headers.items()
                    if k.lower().startswith("x-mstr") or k.lower() in {"content-type", "location"}},
    }
    try:
        out["body"] = r.json()
    except ValueError:
        out["body"] = r.text[: args.text_limit]
        out["body_truncated"] = len(r.text) > args.text_limit
    if args.out:
        mode = "w"
        with open(args.out, mode, encoding="utf-8") as f:
            if isinstance(out.get("body"), (dict, list)):
                json.dump(out["body"], f, indent=2)
            else:
                f.write(str(out.get("body", "")))
        out["saved_to"] = args.out
    print(json.dumps(out, indent=2))


# ── Build ─────────────────────────────────────────────────────────────────────
def parse_source(src: str):
    inst, _, rest = src.partition(":")
    schema, _, tables = rest.partition(":")
    if not (inst and schema and tables):
        die(f"bad --source '{src}'. expected INSTANCE:SCHEMA:T1,T2,...")
    return inst.strip(), schema.strip(), [t.strip() for t in tables.split(",") if t.strip()]


def load_dictionary(path: str) -> dict:
    """Load a JSON or YAML dictionary of name/description overrides + explicit relationships.

    Expected shape (JSON or YAML):
    {
      "attributes": {
        "<TABLE>.<COLUMN>": {"name": "Friendly Name", "description": "..."}
      },
      "metrics": {
        "<TABLE>.<COLUMN>": {"name": "...", "description": "...", "function": "sum|avg|..."}
      },
      "relationships": [
        {"parent":"<TABLE>.<COL>","child":"<TABLE>.<COL>",
         "relationship_table":"<TABLE>",
         "type":"one_to_many|many_to_many|one_to_one"}
      ],
      "tables": {
        "<TABLE>": {"description": "optional table-level description"}
      }
    }

    CSV form (simpler) — columns: table,column,kind,name,description,function
    """
    if not path:
        return {"attributes":{},"metrics":{},"relationships":[],"tables":{}}
    ext = path.lower().rsplit(".",1)[-1]
    if ext in ("json","yaml","yml"):
        d = load_structured_file(path) or {}
    elif ext == "csv":
        d = {"attributes":{},"metrics":{},"relationships":[],"tables":{}}
        with open(path, encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                row = {str(k).strip().lower(): (v or "") for k, v in row.items()}
                if not row.get("table") or not row.get("column"):
                    continue
                key = f"{row['table'].strip()}.{row['column'].strip()}"
                kind = (row.get("kind") or "attribute").strip().lower()
                bucket = d["metrics"] if kind in ("metric","fact_metric") else d["attributes"]
                entry = {"name": row.get("name","").strip(), "description": row.get("description","").strip()}
                if row.get("function"): entry["function"] = row["function"].strip()
                bucket[key] = {k:v for k,v in entry.items() if v}
    else:
        die(f"{path}: dictionary must be JSON, YAML, or CSV")
    # Normalize
    d.setdefault("attributes",{}); d.setdefault("metrics",{})
    d.setdefault("relationships",[]); d.setdefault("tables",{})
    return d


def load_erd(path: str) -> list[dict]:
    """Parse an ERD file → list of relationship specs.
    Supports: JSON/YAML list of relationships, DBML (Ref lines), Mermaid erDiagram,
    and SQL DDL (best-effort REFERENCES clause extraction).
    For PNG/JPG ERDs, let the calling agent convert to one of the text formats first."""
    if not path: return []
    ext = path.lower().rsplit(".",1)[-1]
    txt = None
    if ext in ("json","yaml","yml"):
        d = load_structured_file(path) or {}
        if isinstance(d, dict): d = d.get("relationships", [])
        return d
    with open(path, encoding="utf-8") as f: txt = f.read()
    rels = []
    # DBML:  Ref: "posts"."user_id" > "users"."id"   or  Ref: posts.user_id > users.id
    for m in _re.finditer(r'Ref:?\s*"?([^".\s]+)"?\."?([^".\s]+)"?\s*([<>\-]+)\s*"?([^".\s]+)"?\."?([^".\s]+)"?', txt):
        src_t, src_c, op, dst_t, dst_c = m.groups()
        # src > dst means src is many, dst is one. So parent=dst, child=src.
        rels.append({"parent": f"{dst_t}.{dst_c}", "child": f"{src_t}.{src_c}",
                     "relationship_table": src_t, "type": "one_to_many"})
    # Mermaid: TABLE1 ||--o{ TABLE2 : label   (one-to-many)
    for m in _re.finditer(r'(\w+)\s*\|\|--o\{\s*(\w+)\s*:\s*"?([\w_]+)"?', txt):
        parent_t, child_t, col = m.groups()
        rels.append({"parent": f"{parent_t}.{col}", "child": f"{child_t}.{col}",
                     "relationship_table": child_t, "type": "one_to_many"})
    # SQL DDL: REFERENCES parent(col) embedded in CREATE TABLE child
    for table_m in _re.finditer(r'CREATE\s+TABLE\s+"?(\w+)"?[^;]+?(?=;|$)', txt, _re.IGNORECASE|_re.DOTALL):
        child_t = table_m.group(1)
        for col_m in _re.finditer(r'"?(\w+)"?\s+[\w\(\)]+\s+REFERENCES\s+"?(\w+)"?\s*\(\s*"?(\w+)"?\s*\)',
                                  table_m.group(0), _re.IGNORECASE):
            child_c, parent_t, parent_c = col_m.groups()
            rels.append({"parent": f"{parent_t}.{parent_c}", "child": f"{child_t}.{child_c}",
                         "relationship_table": child_t, "type": "one_to_many"})
    return rels


# Strategy's catalog probe leaves dataType fields it didn't compute as
# INT32_MIN (a "no value" sentinel). When the build flow forwards those into
# the model body, Strategy stores them, and subsequent UI previews fail with
# "DssDataType '4' is invalid or not supported" (and similar codes) — the
# render layer can't map an integer with scale=INT_MIN to a known DssDataType.
# Postgres, MySQL, and SQL Server backends have all been observed to surface
# integer + char/varchar (fixed_length_string) columns with this sentinel.
# See feedback_dssdatatype_sentinel_scale.md.
_DATATYPE_INT_MIN_SENTINEL = -2147483648


def _normalize_catalog_datatype(dt: dict | None) -> dict | None:
    """Sanitize INT32_MIN sentinels in a column's dataType so Strategy doesn't
    store them as-is. Idempotent; safe to call on already-clean dataTypes.

    - scale == INT32_MIN  → 0 (universal safe default; integers and strings
      both expect 0 from the engine's POV)
    - precision == INT32_MIN → 0 (rare; only seen on unknown-precision probes)
    - type == 'date' and scale is missing or negative → 0 (the catalog reports
      scale=-1 for dates which some preview paths reject)
    Other fields pass through untouched.
    """
    if not isinstance(dt, dict):
        return dt
    out = dict(dt)
    if out.get("scale") == _DATATYPE_INT_MIN_SENTINEL:
        out["scale"] = 0
    if out.get("precision") == _DATATYPE_INT_MIN_SENTINEL:
        out["precision"] = 0
    if out.get("type") == "date":
        sc = out.get("scale")
        if sc is None or (isinstance(sc, int) and sc < 0):
            out["scale"] = 0
    return out


def fetch_table_metadata(m: MSTR, ds_id: str, namespace: str, tname: str) -> dict:
    ns_id = resolve_namespace_id(m, ds_id, namespace)
    tb_id = encode_tb_id(namespace, tname)
    path, body = m.try_candidates("describe_table", id=ds_id, ns_id=ns_id, tb_id=tb_id)
    cols = body.get("columns") or body.get("physicalTable",{}).get("columns") or []
    # Sanitize the catalog's INT32_MIN sentinel in dataType before any consumer
    # forwards these columns into a model-body create/patch. See
    # _normalize_catalog_datatype above.
    for c in cols:
        if "dataType" in c:
            c["dataType"] = _normalize_catalog_datatype(c.get("dataType"))
    return {"raw": body, "columns": cols, "tb_id": tb_id, "ns_id": ns_id}


def _col_dtype(c: dict) -> str:
    """Return a lowercase string dataType, handling both flat string and nested {type,scale,precision} shapes."""
    dt = c.get("dataType") or c.get("type") or ""
    if isinstance(dt, dict): dt = dt.get("type","")
    return str(dt).lower()


def _looks_like_identifier_col(name: str) -> bool:
    upper = (name or "").upper()
    return any(upper.endswith(suffix) or upper == suffix.lstrip("_") for suffix in ID_COLUMN_SUFFIXES)


def _looks_like_numeric_dimension(name: str) -> bool:
    upper = (name or "").upper()
    return any(token in upper for token in NATURAL_NUMERIC_DIMS)


def classify_columns(cols, attr_override: set[str], metric_override: set[str]):
    attrs, metrics = [], []
    for c in cols:
        name = c.get("name") or c.get("columnName")
        if not name: continue
        if name.lower() in attr_override:
            attrs.append(c); continue
        if name.lower() in metric_override:
            metrics.append(c); continue
        dtype = _col_dtype(c)
        if _looks_like_identifier_col(name) or _looks_like_numeric_dimension(name):
            attrs.append(c)
        elif any(t in dtype for t in NUMERIC_TYPES):
            metrics.append(c)
        else:
            attrs.append(c)
    return attrs, metrics


_STALE_LOCK_HINT = (
    "A prior Modeling Service session left an open changeset on this project. "
    "Run `build_mosaic.py release-locks` to free locks owned by the current "
    "user, then retry. Locks held by other users age out on their own."
)


def _extract_lockid_from_error(body) -> str | None:
    """Strategy 8004cc41 (schemaEdit lock conflict) reports the existing
    lock's id embedded in XML inside additionalProperties.existingLock.comment:
        '<LOCKID>D7FEB354B8D14678B78363BB3964C811</LOCKID>'
    Return the LOCKID or None.
    """
    try:
        errs = (body or {}).get("errors") or []
        if not errs:
            return None
        comment = (
            (errs[0] or {}).get("additionalProperties", {})
            .get("existingLock", {}).get("comment", "")
        )
        match = _re.search(r"<LOCKID>([A-F0-9]+)</LOCKID>", comment or "")
        return match.group(1) if match else None
    except Exception:
        return None


def _lock_owned_by_self(body, my_user_id: str | None) -> bool:
    try:
        errs = (body or {}).get("errors") or []
        if not errs:
            return False
        owner = (
            (errs[0] or {}).get("additionalProperties", {})
            .get("existingLock", {}).get("ownerId", "")
        )
        return bool(my_user_id) and owner == my_user_id
    except Exception:
        return False


def open_cs(m: MSTR, *, schema_edit: bool = False, release_self_locks: bool = False) -> str:
    """Open a Modeling Service changeset.

    schema_edit=False — relationships, security filters, ACLs, post-build edits.
    schema_edit=True  — adding/modifying form expressions on attributes, or
                        otherwise touching the schema graph itself. Using the
                        wrong type silently produces 8004ccde or no-ops the
                        write. The chosen type is recorded on the session.

    release_self_locks=True — if open fails with 8004cc41 (schemaEdit lock
                              conflict) and the existing lock is owned by the
                              current user, delete it and retry once. Useful
                              after a previous script crash left a stale lock.

    Implementation note: Strategy ignores `schemaEdit: true` in the JSON body
    on this endpoint; it has to be passed as a query param (`?schemaEdit=true`)
    for the lock to actually be acquired. We send both so old and new server
    builds work — Strategy ignores the spare on whichever side doesn't need it.
    """
    body: dict = {}
    path = "/api/model/changesets"
    if schema_edit:
        body["schemaEdit"] = True
        path = "/api/model/changesets?schemaEdit=true"
    r = m.post(path, json=body)
    if not r.ok:
        # Lock-conflict recovery path — 8004cc41 with a self-owned existing lock.
        try:
            err_body = r.json()
        except Exception:
            err_body = None
        if release_self_locks:
            lockid = _extract_lockid_from_error(err_body)
            my_uid = (err_body or {}).get("errors", [{}])[0].get("additionalProperties", {}).get("userId")
            if lockid and _lock_owned_by_self(err_body, my_uid):
                print(f"[open_cs] releasing self-owned stale lock {lockid}", file=sys.stderr)
                try:
                    m.delete(f"/api/model/changesets/{lockid}")
                except Exception:
                    pass
                r = m.post(path, json=body)
        if not r.ok:
            hint = ""
            try:
                if "8004cc41" in r.text:
                    hint = f"\n  {_STALE_LOCK_HINT}"
            except Exception:
                pass
            die(f"open_cs: {format_mstr_error(r)}{hint}")
    d = r.json()
    cs = d.get("id") or d.get("changesetId", "")
    if not cs:
        die(f"open_cs: {d}")
    m.s.headers["X-MSTR-MS-Changeset"] = cs
    # Stash the type on the session so helpers can assert; not a real header
    # for Strategy, just internal state.
    if not hasattr(m, "_cs_types"):
        m._cs_types = {}
    m._cs_types[cs] = "schema" if schema_edit else "data"
    return cs


def commit_cs(m: MSTR, cs: str):
    r = m.post(f"/api/model/changesets/{cs}/commit")
    m.s.headers.pop("X-MSTR-MS-Changeset", None)
    if getattr(m, "_cs_types", None):
        m._cs_types.pop(cs, None)
    if not r.ok:
        die(f"commit {cs}: {format_mstr_error(r)}")


def format_mstr_error(response, prefix: str = "") -> str:
    """Thin wrapper around mosaic_safety.format_mstr_error so the rest of this
    module can call a one-arg helper without the import-prefix dance. Also
    detects the 8004cb0a session-cap and appends the wait advisory."""
    line = ms.format_mstr_error(response, prefix=prefix)
    if ms.is_session_cap_error(response):
        line += "  ← " + ms.SESSION_CAP_MESSAGE
    return line


def discard_cs(m: MSTR, cs: str) -> None:
    """Best-effort discard of a changeset. Used in error paths."""
    if not cs:
        return
    try:
        m.delete(f"/api/model/changesets/{cs}")
    except Exception:
        pass
    m.s.headers.pop("X-MSTR-MS-Changeset", None)
    if getattr(m, "_cs_types", None):
        m._cs_types.pop(cs, None)


# ── Relationship safety: merge-aware PUT + join-table preflight ──────────────
#
# WARNING: PUT /api/model/dataModels/{model_id}/attributes/{attr_id}/relationships
# REPLACES every relationship attached to that attribute — in BOTH directions
# (incoming AND outgoing). It is NOT append-only. Issuing it with only your new
# rels silently deletes everything that was wired previously. Always go through
# put_relationships_merged() unless you explicitly intend the destructive wipe.

def get_attribute_relationships(
    m: MSTR, model_id: str, attr_id: str,
) -> list[dict]:
    """Read the current set of relationships on a Mosaic attribute. Returns []
    when the attribute exists but has none, and on read failures (caller can
    decide whether absence is fatal)."""
    r = m.get(f"/api/model/dataModels/{model_id}/attributes/{attr_id}")
    if not r.ok:
        if m.verbose:
            print(f"[rel-merge] read {attr_id}: {format_mstr_error(r)}", file=sys.stderr)
        return []
    body = r.json() if r.text else {}
    rels = body.get("relationships") or []
    return rels if isinstance(rels, list) else []


def _rel_key(rel: dict) -> tuple[str, str, str]:
    """Stable identity for a relationship row: (parent_id, child_id, rel_table_id).
    Used to dedup when merging existing + new relationships."""
    parent = ((rel.get("parent") or {}).get("objectId")
              or (rel.get("parent") or {}).get("id") or "")
    child = ((rel.get("child") or {}).get("objectId")
             or (rel.get("child") or {}).get("id") or "")
    rtable = ((rel.get("relationshipTable") or {}).get("objectId")
              or (rel.get("relationshipTable") or {}).get("id") or "")
    return (str(parent), str(child), str(rtable))


def put_relationships_merged(
    m: MSTR,
    model_id: str,
    attr_id: str,
    new_rels: list[dict],
    cs_id: str,
    *,
    replace: bool = False,
) -> tuple[bool, int, int, str]:
    """Safely write relationships for an attribute without wiping existing ones.

    Strategy's PUT /attributes/{id}/relationships is destructive — it REPLACES
    the attribute's full relationship set in both directions. This helper
    fetches the existing relationships first, dedupes by (parent, child,
    relationship_table) against `new_rels`, and PUTs the union.

    Set `replace=True` only when you explicitly want the wipe (e.g. cleanup).

    Returns (ok, added_count, total_count, error_or_empty). `added_count` is
    the number of relationships actually new; `total_count` is the size of the
    final set written.
    """
    if not new_rels:
        return True, 0, 0, ""

    if replace:
        merged = list(new_rels)
        added = len(new_rels)
    else:
        existing = get_attribute_relationships(m, model_id, attr_id)
        existing_keys = {_rel_key(r) for r in existing}
        merged = list(existing)
        added = 0
        for rel in new_rels:
            if _rel_key(rel) in existing_keys:
                continue
            merged.append(rel)
            existing_keys.add(_rel_key(rel))
            added += 1

    body = {"relationships": merged}
    r = m.put(
        f"/api/model/dataModels/{model_id}/attributes/{attr_id}/relationships"
        f"?changesetId={cs_id}",
        json=body,
    )
    if not r.ok:
        return False, added, len(merged), format_mstr_error(r)
    return True, added, len(merged), ""


# ── Post-build topology validation ───────────────────────────────────────────

def post_build_validate_topology(
    m: MSTR,
    model_id: str,
    *,
    expected_tables: list[str] | None = None,
) -> dict:
    """Return a structured report on model topology health.

    Detects:
      - Isolated attributes (no incoming + no outgoing relationships, on a
        fact-like or expected table).
      - Tables present in the model but with zero relationships, or absent
        when `expected_tables` is provided.
      - Numeric attributes whose only expression is on a fact-like table
        (likely misclassified — should probably be metrics).

    Output shape:
      {"model_id": "...",
       "counts": {"attributes": N, "relationships": M, "tables": T},
       "isolated_attributes": [{"id": "...", "name": "...", "table": "..."}],
       "tables_without_relationships": ["..."],
       "missing_expected_tables": ["..."],
       "numeric_attribute_warnings": [{"id": "...", "name": "...", "table": "..."}],
       "ok": bool}

    Any caller can use this — it does not exit the process. Pair with
    cmd_validate_model for CLI usage with non-zero exit-on-failure semantics.
    """
    attrs_r = m.get(f"/api/model/dataModels/{model_id}/attributes?limit=2000")
    if not attrs_r.ok:
        return {
            "ok": False,
            "error": format_mstr_error(attrs_r, "topology attributes read"),
        }
    attrs = (attrs_r.json() or {}).get("attributes", []) or []

    tables_r = m.get(f"/api/model/dataModels/{model_id}/tables")
    tables = (tables_r.json() or {}).get("tables", []) if tables_r.ok else []

    rel_count = 0
    by_table_rels: dict[str, int] = {}
    isolated: list[dict] = []
    numeric_warnings: list[dict] = []

    lookup_map = ms.attribute_lookup_table_map(attrs)
    lookup_name_map = ms.attribute_table_name_map(attrs)

    for a in attrs:
        info = a.get("information") or {}
        aid = info.get("objectId") or a.get("id")
        nm = info.get("name") or "?"
        rels = a.get("relationships") or []
        rel_count += len(rels)
        table_name = lookup_name_map.get(aid, "")
        if table_name:
            by_table_rels[table_name] = by_table_rels.get(table_name, 0) + len(rels)
        if not rels:
            isolated.append({"id": aid, "name": nm, "table": table_name})

        # Numeric-attribute heuristic: if the column-name looks numeric/metric-y
        # AND its lookup table is fact-like AND it carries no relationship,
        # flag as likely-misclassified.
        if not rels and _looks_like_metric_name(nm) and _is_fact_like(table_name):
            numeric_warnings.append({"id": aid, "name": nm, "table": table_name})

    declared_tables = {((t.get("information") or {}).get("name") or "")
                       for t in tables}
    declared_tables.discard("")

    # Tables that exist in the model but have zero relationships touching them.
    # Skip dim tables (a single-table dim can legitimately have no rels — the
    # join lives on the fact-table side).
    fact_like_in_model = {n for n in declared_tables if _is_fact_like(n)}
    tables_without_rels = sorted(
        n for n in fact_like_in_model
        if by_table_rels.get(n, 0) == 0
    )

    missing_expected = []
    if expected_tables:
        missing_expected = sorted(set(expected_tables) - declared_tables)

    ok = (not isolated and not tables_without_rels
          and not missing_expected and not numeric_warnings)

    return {
        "model_id": model_id,
        "counts": {
            "attributes": len(attrs),
            "relationships": rel_count,
            "tables": len(tables),
        },
        "isolated_attributes": isolated,
        "tables_without_relationships": tables_without_rels,
        "missing_expected_tables": missing_expected,
        "numeric_attribute_warnings": numeric_warnings,
        "ok": ok,
    }


_METRIC_NAME_HINTS = ("amount", "amt", "total", "qty", "quantity", "price",
                      "cost", "revenue", "paid", "balance", "discount",
                      "net_paid", "sales", "profit", "value")


def _looks_like_metric_name(name: str) -> bool:
    """Heuristic: column/attribute name reads like a measure column."""
    if not name:
        return False
    n = name.lower()
    return any(h in n for h in _METRIC_NAME_HINTS)


def _parse_id_list(raw: str | None) -> list[str]:
    """Parse comma-separated IDs or @filepath of one ID per line."""
    if not raw:
        return []
    if raw.startswith("@"):
        with open(raw[1:], encoding="utf-8") as f:
            return [line.strip() for line in f if line.strip()]
    return [x.strip() for x in raw.split(",") if x.strip()]


def batch_call(
    m: MSTR,
    model_id: str,
    changeset_id: str,
    ops: list[dict],
    *,
    atomic: bool = True,
) -> tuple[list[dict], list[dict]]:
    """POST /api/model/batch with a list of sub-operations.

    atomic=True  → allowPartialSuccess=false (rollback on any failure).
    atomic=False → allowPartialSuccess=true  (207 Multi-Status, per-op results).

    Returns (passed, failed). Falls back to per-op individual POSTs if the
    tenant returns 404 on /api/model/batch.
    """
    allow_partial = "false" if atomic else "true"
    r = m.post(
        f"/api/model/batch?allowPartialSuccess={allow_partial}&showChanges=true",
        headers={"X-MSTR-MS-Changeset": changeset_id},
        json={"operations": ops},
    )
    if r.status_code == 404:
        if m.verbose:
            print("[batch] endpoint 404 — falling back to per-op individual calls",
                  file=sys.stderr)
        return _batch_fallback(m, model_id, changeset_id, ops)
    if r.status_code not in (200, 207, 400):
        raise RuntimeError(f"batch_call HTTP {r.status_code}: {r.text[:400]}")
    body = r.json() if r.text else {}
    results = body.get("results") or body.get("operations") or body.get("ops") or []
    passed = [res for res in results if 200 <= res.get("status", 500) < 300]
    failed = [res for res in results if res not in passed]
    return passed, failed


def _batch_fallback(
    m: MSTR,
    model_id: str,
    changeset_id: str,
    ops: list[dict],
) -> tuple[list[dict], list[dict]]:
    """Individual POST fallback for tenants without /api/model/batch."""
    PATH_MAP = {
        "/attributes":  f"/api/model/dataModels/{model_id}/attributes",
        "/factMetrics": f"/api/model/dataModels/{model_id}/factMetrics",
        "/metrics":     f"/api/model/dataModels/{model_id}/metrics",
        "/facts":       f"/api/model/dataModels/{model_id}/facts",
    }
    passed, failed = [], []
    for op in ops:
        path_suffix = op.get("path", "")
        endpoint = PATH_MAP.get(path_suffix)
        if not endpoint:
            failed.append({"op": op, "status": 400,
                           "error": f"unknown path {path_suffix}"})
            continue
        r = m.post(endpoint, json=op.get("value", {}),
                   headers={"X-MSTR-MS-Changeset": changeset_id})
        result = {"op": op, "status": r.status_code}
        if r.ok:
            result["response"] = r.json() if r.text else {}
            passed.append(result)
        else:
            result["error"] = r.text[:400]
            failed.append(result)
    return passed, failed


def _make_pipeline_table_body(
    m: MSTR,
    ds_id: str,
    schema: str,
    tname: str,
) -> dict | None:
    """Fetch warehouse table metadata and return the physicalTable pipeline body
    used by POST /api/model/dataModels/{id}/tables. Returns None if the table
    cannot be fetched. Datatypes are normalized via schema_object_translator
    so the resulting model is publishable in-memory.
    """
    try:
        md = fetch_table_metadata(m, ds_id, schema, tname)
    except SystemExit:
        return None
    cols_raw = md.get("columns", [])
    outer_cols, pipe_cols = [], []
    for c in cols_raw:
        cname = c.get("name") or c.get("columnName")
        dt = c.get("dataType")
        if isinstance(dt, str):
            dt = {"type": dt}
        if not isinstance(dt, dict):
            dt = {"type": "utf8_char"}
        dt = sot.normalize_datatype(dt)
        outer_cols.append({
            "information": {"name": cname},
            "dataType": dt,
            "columnName": cname,
        })
        pipe_cols.append({
            "id": new_uuid(),
            "name": cname,
            "dataType": dt,
            "sourceDataType": dt,
        })
    pipeline_obj = {
        "id": new_uuid(),
        "rootTable": {
            "id": new_uuid(),
            "type": "root",
            "children": [{
                "id": new_uuid(),
                "name": tname,
                "type": "source",
                "columns": pipe_cols,
                "importSource": {
                    "type": "single_table",
                    "dataSourceId": ds_id,
                    "namespace": schema,
                    "tableName": tname,
                    "sql": "",
                },
            }],
        },
    }
    return {
        "information": {"name": tname},
        "physicalTable": {
            "columns": outer_cols,
            "type": "pipeline",
            "pipeline": json.dumps(pipeline_obj),
        },
    }


def _apply_conformance_map(dictionary: dict, path: str) -> None:
    """Merge a conformance-map file into the dictionary's attributes block.

    File shape (JSON or YAML) — one entry per logical attribute:
        {"<Logical Name>": ["<TABLE>.<COLUMN>", "<TABLE>.<COLUMN>", ...]}

    Each table.column listed will receive an attributes entry with the shared
    `name`, which triggers the conformance-via-identical-name grouping at build
    time (see feedback_mosaic_relationship_wiring.md step 2). Existing dictionary
    entries keep their description; only `name` is overwritten.
    """
    if not path: return
    data = load_structured_file(path) or {}
    if not isinstance(data, dict):
        die(f"--conformance-map: {path} must be a mapping of logical_name → [table.col, …]")
    attrs = dictionary.setdefault("attributes", {})
    added = 0
    for logical, cols in data.items():
        if not isinstance(cols, list): continue
        for col in cols:
            key = str(col).strip()
            if not key: continue
            entry = attrs.get(key) or {}
            entry["name"] = logical
            attrs[key] = entry
            added += 1
    if added:
        print(f"→ --conformance-map: applied {added} TABLE.COLUMN → logical-name overrides",
              file=sys.stderr)


def _apply_fk_map(dictionary: dict, path: str) -> None:
    """Merge an fk-map file: maps child FKs to their parent PK so differently-named
    columns conform to the parent's logical attribute.

    File shape (JSON or YAML):
        {"<CHILD_TABLE>.<CHILD_COL>": "<PARENT_TABLE>.<PARENT_COL>", ...}

    For each mapping, the child column inherits the parent column's logical name
    (resolved via the dictionary's existing attributes entry, falling back to
    title-cased parent column name if no entry exists yet). Relationships still
    need to be declared separately if the conformance grouping doesn't join the
    tables on its own.
    """
    if not path: return
    data = load_structured_file(path) or {}
    if not isinstance(data, dict):
        die(f"--fk-map: {path} must be a mapping of child.col → parent.col")
    attrs = dictionary.setdefault("attributes", {})
    added = 0
    for child, parent in data.items():
        child_key  = str(child).strip()
        parent_key = str(parent).strip()
        if not (child_key and parent_key): continue
        parent_entry = attrs.get(parent_key) or {}
        parent_name = parent_entry.get("name")
        if not parent_name:
            # Fall back to the parent's column name, title-cased (mirrors the
            # helper's default inference). Keep simple.
            parent_col = parent_key.rsplit(".", 1)[-1]
            parent_name = parent_col.replace("_", " ").title()
        child_entry = attrs.get(child_key) or {}
        child_entry["name"] = parent_name
        attrs[child_key] = child_entry
        # Also set the parent's name if it's not already set, so the two sides
        # conform on the same string.
        if not parent_entry.get("name"):
            parent_entry["name"] = parent_name
            attrs[parent_key] = parent_entry
        added += 1
    if added:
        print(f"→ --fk-map: applied {added} child→parent FK conformance hint(s)",
              file=sys.stderr)


def cmd_build(m: MSTR, args):
    m.login(identity=True)
    sources = [parse_source(s) for s in args.source]
    if args.instance and args.schema and args.tables:
        sources.append((args.instance, args.schema, args.tables))
    if not sources:
        die("provide at least one --source INSTANCE:SCHEMA:T1,T2 or --instance/--schema/--tables")

    # Load optional overrides / ERD
    dictionary = load_dictionary(getattr(args,"dictionary",None))
    _apply_conformance_map(dictionary, getattr(args, "conformance_map", None))
    _apply_fk_map(dictionary, getattr(args, "fk_map", None))
    explicit_rels = list(dictionary.get("relationships",[]))
    for erd_path in (getattr(args,"erd",[]) or []):
        explicit_rels.extend(load_erd(erd_path))
    if explicit_rels:
        print(f"→ Using {len(explicit_rels)} explicit relationships from dictionary/ERD "
              f"(shared-column inference disabled).", file=sys.stderr)

    # Resolve instance IDs and fetch table metadata
    print(f"→ Resolving {len(sources)} source(s)…", file=sys.stderr)
    hydrated = []
    for inst_name, schema, tables in sources:
        ds_id = resolve_instance_id(m, inst_name)
        for t in tables:
            md = fetch_table_metadata(m, ds_id, schema, t)
            print(f"  {inst_name}/{schema}.{t}: {len(md['columns'])} cols", file=sys.stderr)
            hydrated.append({"instance_id": ds_id, "instance_name": inst_name,
                             "schema": schema, "table": t, "metadata": md})

    attr_override  = {c.lower() for c in (args.attr_cols or [])}
    metric_override = {c.lower() for c in (args.metric_cols or [])}

    # ── Create model ──
    print(f"→ Creating model '{args.name}'…", file=sys.stderr)
    cs = open_cs(m)
    r = m.post("/api/model/dataModels", json={
        "information": {"name": args.name, "destinationFolderId": args.dest_folder},
        "dataServeMode": args.data_serve_mode,
    })
    if not r.ok: die(f"create model: {r.status_code} {r.text[:400]}")
    model_id = r.json()["information"]["objectId"]
    print(f"  model_id={model_id}", file=sys.stderr)

    # ── Add tables (pipeline/importSource shape) ──
    table_id_map = {}   # (inst_id, schema, table) -> logical_table_id
    table_cols_map = {} # same -> [cols]
    for h in hydrated:
        cols_raw = h["metadata"]["columns"]
        # Outer physicalTable.columns shape: {information:{name}, dataType, columnName}
        outer_cols = []
        # Inner pipeline columns shape: {id, name, dataType, sourceDataType}
        pipe_cols  = []
        for c in cols_raw:
            cname = c.get("name") or c.get("columnName")
            dt    = c.get("dataType")
            if isinstance(dt, str): dt = {"type": dt}
            if not isinstance(dt, dict): dt = {"type": "utf8_char"}
            outer_cols.append({
                "information": {"name": cname},
                "dataType": dt,
                "columnName": cname,
            })
            pipe_cols.append({
                "id": new_uuid(),
                "name": cname,
                "dataType": dt,
                "sourceDataType": dt,
            })
        pipeline_obj = {
            "id": new_uuid(),
            "rootTable": {
                "id": new_uuid(),
                "type": "root",
                "children": [{
                    "id": new_uuid(),
                    "name": h["table"],
                    "type": "source",
                    "columns": pipe_cols,
                    "importSource": {
                        "type": "single_table",
                        "dataSourceId": h["instance_id"],
                        "namespace": h["schema"],
                        "tableName": h["table"],
                        "sql": "",
                    },
                }],
            },
        }
        body = {
            "information": {"name": h["table"]},
            "physicalTable": {
                "columns": outer_cols,
                "type": "pipeline",
                "pipeline": json.dumps(pipeline_obj),
            },
        }
        r = m.post(f"/api/model/dataModels/{model_id}/tables", json=body)
        if not r.ok:
            print(f"  WARN add table {h['table']}: {r.status_code} {r.text[:400]}", file=sys.stderr)
            continue
        new_tid = r.json()["information"]["objectId"]
        key = (h["instance_id"], h["schema"], h["table"])
        table_id_map[key] = new_tid
        table_cols_map[key] = cols_raw
        print(f"  + table {h['table']} -> {new_tid}", file=sys.stderr)

    # ── Per-column attribute + metric creation (entity-first pattern) ──
    # This matches how MSTR Mosaic UI builds models: one "entity" attribute per table
    # identity, with text-form expressions on every table that carries the same column.
    # Non-key columns become single-table attributes with a parent→child relationship
    # to their table's entity attribute.

    # Pre-pass: column → [(table_name, table_id), ...]
    col_tables = {}
    for key, tid in table_id_map.items():
        _, _, tname = key
        for c in table_cols_map[key]:
            cn = (c.get("name") or c.get("columnName") or "").strip()
            if cn:
                dt = c.get("dataType") or {}
                col_tables.setdefault(cn, []).append({"table": tname, "table_id": tid, "dtype": dt})

    # Identify each table's "entity key" column: the column whose prefix matches the
    # table's singular form (PRODUCTS -> PRODUCT_*, OPPORTUNITIES -> OPPORTUNITY_*).
    # Fallback: the first *_ID column.
    def _strip_prefix(tname: str) -> str:
        return _re.sub(r"^[A-Z]+(?:_[A-Z]+)*_\d{6,}(?:_\d+)*_", "", tname)

    def _entity_prefix(tname: str) -> str:
        base = _strip_prefix(tname).split("_")[-1]
        if base.endswith("IES"): return base[:-3] + "Y"
        if base.endswith("SES"): return base[:-2]
        if base.endswith("S") and len(base) > 2: return base[:-1]
        return base

    def _entity_candidates(tname: str) -> list[str]:
        """Possible PK-column prefixes for a table: singular, acronym, full-compound-singular."""
        stripped = _strip_prefix(tname)
        words = stripped.split("_")
        cands = [_entity_prefix(tname).upper()]
        if len(words) >= 2:
            # acronym: first letter of each word, e.g. PURCHASE_ORDERS -> PO
            cands.append("".join(w[0] for w in words if w).upper())
        return list(dict.fromkeys(cands))

    table_entity_col = {}
    for key in table_id_map:
        _, _, tname = key
        cands = _entity_candidates(tname)
        names = [((c.get("name") or c.get("columnName") or "").upper()) for c in table_cols_map[key]]
        pk = None
        for pref in cands:
            for suf in ["_ID", "_NUMBER", "_KEY", "_NO"]:
                target = f"{pref}{suf}"
                if target in names:
                    pk = target; break
            if pk: break
        if not pk:
            # Fallback: any *_ID / *_NUMBER / *_KEY not on the NOISE list
            for n in names:
                if any(n.endswith(s) for s in ["_ID","_NUMBER","_KEY"]) and n != "SOURCE_SYSTEM":
                    pk = n; break
        table_entity_col[key] = pk

    # Decide the "home" table (lookup) for each shared column:
    #   - If only one table carries it -> that table.
    #   - Else if one of the tables uses it as entity PK -> that table.
    #   - Else first occurrence.
    col_home = {}
    for col, occ in col_tables.items():
        if len(occ) == 1:
            col_home[col] = occ[0]; continue
        for o in occ:
            for key, pk in table_entity_col.items():
                if pk == col.upper() and key[2] == o["table"]:
                    col_home[col] = o; break
            if col in col_home: break
        if col not in col_home: col_home[col] = occ[0]

    # Skip auto-creating attributes for "noise" columns like SOURCE_SYSTEM that
    # appear in every table but aren't a real dimension.
    NOISE_COLS = {"SOURCE_SYSTEM","LOAD_TIMESTAMP","LAST_UPDATED_AT","INGESTION_DATE",
                  "LOAD_DATE","ETL_BATCH_ID","DW_CREATED_AT","DW_UPDATED_AT"}
    SKIP_AS_ATTRIBUTE = {c for c in col_tables if c.upper() in NOISE_COLS and len(col_tables[c]) >= 3}

    # Compute entity PK set early (conformed-dim detection needs it)
    entity_pks = {c for c in (table_entity_col.values()) if c}

    # Snowflake schema support: CONFORMED DIMENSIONS.
    # A column that appears in ≥2 tables, is NOT any table's PK, and isn't noise,
    # is likely a conformed dimension (e.g., REGION in both SUPPLIERS and CUSTOMERS).
    # Create ONE multi-table attribute for it (rather than per-table duplicates).
    entity_pk_set = {p.upper() for p in entity_pks if p}
    conformed_cols = set()
    for col, occ in col_tables.items():
        if len(occ) < 2: continue
        if col.upper() in entity_pk_set: continue
        if col.upper() in NOISE_COLS:    continue
        # If the column is numeric in any occurrence, skip (it's probably a metric)
        is_numeric = False
        for o in occ:
            dt = o.get("dtype") or {}
            dtype_s = (dt.get("type") if isinstance(dt, dict) else str(dt)).lower()
            if any(t in dtype_s for t in NUMERIC_TYPES):
                is_numeric = True; break
        if is_numeric: continue
        conformed_cols.add(col)

    # Entity attributes (one per shared-key column): multi-table expressions.
    entity_attr_of_table = {}   # tname -> attr_id (the PK attr whose lookup is tname)
    created_attrs = {}          # column_lower -> list of {id, table, table_id, name, role: "entity"|"descriptor"}
    total_attrs = total_metrics = 0

    def _dict_override(dkey):
        for k,v in dictionary["attributes"].items():
            if k.lower() == dkey.lower(): return v
        return {}

    # 1) Create entity attributes for each unique PK column, expressions on all occurrences
    for pk_col in entity_pks:
        if pk_col not in col_tables: continue
        occs = col_tables[pk_col]
        home = col_home[pk_col]
        # Pick a short-friendly name — e.g. "PRODUCT_ID" -> "Product"
        base_entity_name = friendly_col(pk_col).replace(" Id","").replace(" ID","").strip() or friendly_col(pk_col)
        # Override with dictionary (home-table key)
        ov = _dict_override(f"{home['table']}.{pk_col}")
        name = ov.get("name") or base_entity_name
        desc = ov.get("description") or f"Unique {friendly_col(pk_col)} identifier; key of the {friendly_table(home['table'])} entity."
        expressions = [
            {"expression": {"tokens":[{"type":"column_reference","value": pk_col}]},
             "tables": [{"objectId": o["table_id"], "subType":"logical_table", "name": o["table"]}]}
            for o in occs
        ]
        attr_body = {
            "information": {"name": name, "description": desc},
            "forms": [{
                "id": FORM_ID, "category": "ID", "type": "system",
                "displayFormat": "text", "name": f"{friendly_col(pk_col)}",
                "expressions": expressions,
                "lookupTable": {"objectId": home["table_id"], "subType":"logical_table", "name": home["table"]},
            }],
            "keyForm": {"id": FORM_ID},
            "attributeLookupTable": {"objectId": home["table_id"], "subType":"logical_table", "name": home["table"]},
        }
        r = m.post(f"/api/model/dataModels/{model_id}/attributes", json=attr_body)
        if not r.ok:
            print(f"    WARN entity attr {name}: {r.status_code} {r.text[:200]}", file=sys.stderr)
            continue
        resp = r.json(); aid = resp["information"]["objectId"]
        # displays PATCH
        fids = [f["id"] for f in resp.get("forms",[]) if f.get("id")]
        if fids:
            m.s.patch(f"{m.base}/api/model/dataModels/{model_id}/attributes/{aid}",
                      json={"displays": {"reportDisplays":[{"id":f} for f in fids],
                                          "browseDisplays": [{"id":f} for f in fids]}})
        entity_attr_of_table[home["table"]] = aid
        created_attrs[pk_col.lower()] = [{"id": aid, "table": home["table"],
                                          "table_id": home["table_id"], "name": name, "role":"entity"}]
        total_attrs += 1
        print(f"  + entity attr '{name}' on {len(occs)} tables (lookup={friendly_table(home['table'])})", file=sys.stderr)

    # 1b) Conformed dimensions: one multi-table attribute per shared descriptor column.
    for col in conformed_cols:
        occs = col_tables[col]
        home = occs[0]   # first occurrence wins for lookup
        name = friendly_col(col)
        desc = f"Conformed dimension: {name} (shared across {', '.join(friendly_table(o['table']) for o in occs)})."
        ov = _dict_override(f"{home['table']}.{col}")
        if ov.get("name"):        name = ov["name"]
        if ov.get("description"): desc = ov["description"]
        expressions = [
            {"expression": {"tokens":[{"type":"column_reference","value": col}]},
             "tables": [{"objectId": o["table_id"], "subType":"logical_table", "name": o["table"]}]}
            for o in occs
        ]
        attr_body = {
            "information": {"name": name, "description": desc},
            "forms": [{
                "id": FORM_ID, "category": "ID", "type": "system",
                "displayFormat": "text", "name": friendly_col(col),
                "expressions": expressions,
                "lookupTable": {"objectId": home["table_id"], "subType":"logical_table", "name": home["table"]},
            }],
            "keyForm": {"id": FORM_ID},
            "attributeLookupTable": {"objectId": home["table_id"], "subType":"logical_table", "name": home["table"]},
        }
        r = m.post(f"/api/model/dataModels/{model_id}/attributes", json=attr_body)
        if not r.ok:
            print(f"    WARN conformed {name}: {r.status_code} {r.text[:200]}", file=sys.stderr)
            continue
        resp = r.json(); aid = resp["information"]["objectId"]
        fids = [f["id"] for f in resp.get("forms",[]) if f.get("id")]
        if fids:
            m.s.patch(f"{m.base}/api/model/dataModels/{model_id}/attributes/{aid}",
                      json={"displays":{"reportDisplays":[{"id":f} for f in fids],
                                         "browseDisplays":[{"id":f} for f in fids]}})
        created_attrs[col.lower()] = [{"id": aid, "table": home["table"],
                                        "table_id": home["table_id"], "name": name, "role":"conformed"}]
        total_attrs += 1
        print(f"  + conformed dim '{name}' spans {len(occs)} tables", file=sys.stderr)

    # 2) Descriptor attributes: one per remaining column, single-table
    for key, tid in table_id_map.items():
        inst_id, schema, tname = key
        cols = table_cols_map[key]
        attrs, metrics = classify_columns(cols, attr_override, metric_override)
        short_table = friendly_table(tname)
        for c in attrs:
            cname = c.get("name") or c.get("columnName")
            if not cname: continue
            if cname.upper() in entity_pks:      continue   # handled as entity above
            if cname in SKIP_AS_ATTRIBUTE:       continue
            if cname in conformed_cols:          continue   # handled as conformed above
            base = friendly_col(cname)
            name = base
            desc = f"{base} from the {short_table} table."
            ov = _dict_override(f"{tname}.{cname}")
            if ov.get("name"): name = ov["name"]
            if ov.get("description"): desc = ov["description"]
            attr_body = {
                "information": {"name": name, "description": desc},
                "forms": [{
                    "id": FORM_ID, "category": "ID", "type": "system",
                    "displayFormat": "text", "name": f"{base} ID",
                    "expressions": [{
                        "expression": {"tokens":[{"type":"column_reference","value": cname}]},
                        "tables": [{"objectId": tid, "subType":"logical_table", "name": tname}],
                    }],
                    "lookupTable": {"objectId": tid, "subType":"logical_table", "name": tname},
                }],
                "keyForm": {"id": FORM_ID},
                "attributeLookupTable": {"objectId": tid, "subType":"logical_table", "name": tname},
            }
            r = m.post(f"/api/model/dataModels/{model_id}/attributes", json=attr_body)
            if not r.ok:
                print(f"    WARN attr {tname}.{cname}: {r.status_code} {r.text[:200]}", file=sys.stderr)
                continue
            resp = r.json(); aid = resp["information"]["objectId"]
            fids = [f["id"] for f in resp.get("forms",[]) if f.get("id")]
            if fids:
                m.s.patch(f"{m.base}/api/model/dataModels/{model_id}/attributes/{aid}",
                          json={"displays": {"reportDisplays":[{"id":f} for f in fids],
                                              "browseDisplays":[{"id":f} for f in fids]}})
            created_attrs.setdefault(cname.lower(), []).append(
                {"id": aid, "table": tname, "table_id": tid, "name": name, "role":"descriptor"})
            total_attrs += 1

        # Metrics (text-form expression, dictionary overrides)
        for c in metrics:
            cname = c.get("name") or c.get("columnName")
            dt_obj = c.get("dataType")
            if not isinstance(dt_obj, dict):
                dt_obj = {"type": str(dt_obj or "double"), "precision": 15, "scale": 4}
            base = friendly_col(cname)
            metric_name = f"Total {base}"
            metric_desc = f"SUM of {cname} from the {short_table} table."
            metric_func = "sum"
            for k,v in dictionary["metrics"].items():
                if k.lower() == f"{tname}.{cname}".lower():
                    if v.get("name"):        metric_name = v["name"]
                    if v.get("description"): metric_desc = v["description"]
                    if v.get("function"):    metric_func = v["function"].lower()
                    break
            metric_body = {
                "information": {"name": metric_name, "description": metric_desc},
                "fact": {
                    "dataType": dt_obj,
                    "expressions": [{
                        "expression": {"tokens":[{"type":"column_reference","value": cname}]},
                        "tables": [{"objectId": tid, "subType":"logical_table","name": tname}],
                    }],
                    "extensions": [], "entryLevel": [],
                },
                "function": metric_func,
                "functionProperties": [{"name":"UseLookupForAttributes","value":{"type":"boolean","value":"false"}}],
                "dimty": {
                    "dimtyUnits":[{"dimtyUnitType":"report_base_level","aggregation":"normal",
                                   "filtering":"apply","groupBy":True}],
                    "excludeAttribute": False, "allowAddingUnit": True,
                },
                "format": {"header":[], "values":[]},
            }
            r = m.post(f"/api/model/dataModels/{model_id}/factMetrics", json=metric_body)
            if not r.ok:
                print(f"    WARN metric {metric_name}: {r.status_code} {r.text[:200]}", file=sys.stderr)
                continue
            total_metrics += 1

    # Snowflake support: auto-create a user-defined hierarchy object walking the
    # longest parent→child entity chain (most common drill path). Skipped if the
    # entity graph has no chains of length ≥ 3.
    hierarchy_path = []
    if total_attrs >= 3:
        # Build entity adjacency: parent_attr_id -> [child_attr_id, ...]
        adj = {}
        for col, entries in created_attrs.items():
            if not entries or entries[0].get("role") != "entity": continue
            parent = entries[0]
            # Anything with its PK column in another table: that other table's entity is a child
            occs = col_tables.get(col.upper(), []) + col_tables.get(col, [])
            for o in occs:
                if o["table"] == parent["table"]: continue
                child = next((info for entries2 in created_attrs.values() for info in entries2
                              if info.get("role")=="entity" and info["table"]==o["table"]), None)
                if child and child["id"] != parent["id"]:
                    adj.setdefault(parent["id"], set()).add(child["id"])
        # Find longest simple path via DFS
        id_to_name = {info["id"]: info["name"] for entries in created_attrs.values()
                      for info in entries if info.get("role")=="entity"}
        best = []
        def dfs(node, path, seen):
            nonlocal best
            if len(path) > len(best): best = list(path)
            for nxt in adj.get(node, ()):
                if nxt in seen: continue
                path.append(nxt); seen.add(nxt)
                dfs(nxt, path, seen)
                path.pop(); seen.discard(nxt)
        for start in adj:
            dfs(start, [start], {start})
        if len(best) >= 3:
            hierarchy_path = [{"id": nid, "name": id_to_name.get(nid,"?")} for nid in best]

    print("→ Committing model changeset…", file=sys.stderr)
    commit_cs(m, cs)

    # ── Relationships (entity-first pattern) ──
    # 1) descriptor → entity: within each table, every descriptor attribute is a parent
    #    of the table's entity attribute (MSTR canonical "lookup" shape).
    # 2) entity A → entity B: whenever entity A's key column exists on B's table, B is a fact of A.
    inferred_rels = []
    # entity_attr_of_table: table_name -> entity_attr_id
    entity_attr_by_table_id = {info["table_id"]: info
                               for entries in created_attrs.values() for info in entries
                               if info.get("role") == "entity"}
    # Descriptor → entity
    for key, tid in table_id_map.items():
        _, _, tname = key
        # find entity attr whose lookup table is this table
        entity = next((info for entries in created_attrs.values() for info in entries
                       if info.get("role")=="entity" and info["table"]==tname), None)
        if not entity: continue
        for entries in created_attrs.values():
            for info in entries:
                if info.get("role")=="descriptor" and info["table"]==tname:
                    inferred_rels.append((info, entity, info["name"], tid, "one_to_many"))
    # Entity → entity (fact tables reference dim entities)
    for ent_col, entries in created_attrs.items():
        if not entries or entries[0].get("role") != "entity": continue
        parent = entries[0]
        occs = col_tables.get(ent_col.upper(), []) + col_tables.get(ent_col, [])
        seen_tables = set()
        for o in occs:
            tname = o["table"]
            if tname == parent["table"] or tname in seen_tables: continue
            seen_tables.add(tname)
            # Find the fact table's entity attribute (its own PK)
            child = next((info for entries2 in created_attrs.values() for info in entries2
                          if info.get("role")=="entity" and info["table"]==tname), None)
            if not child or child["id"] == parent["id"]: continue
            inferred_rels.append((parent, child, f"{parent['name']}→{child['name']}",
                                   o["table_id"], "one_to_many"))
    # Deduplicate
    seen = set(); deduped = []
    for p,c,label,rt,rty in inferred_rels:
        sig = (p["id"], c["id"], rt)
        if sig in seen: continue
        seen.add(sig); deduped.append((p,c,label,rt,rty))
    inferred_rels = deduped

    # Allow ERD/dict to override inference wholesale (only when explicitly provided)
    if explicit_rels:
        def _find_attr(ref: str):
            t, _, col = ref.partition(".")
            for entry in created_attrs.get(col.lower(), []):
                if entry["table"].lower() == t.lower(): return entry
            return (created_attrs.get(col.lower()) or [None])[0]
        inferred_rels = []
        for rel in explicit_rels:
            p = _find_attr(rel.get("parent",""))
            c = _find_attr(rel.get("child",""))
            if not (p and c): continue
            rtbl_name = rel.get("relationship_table") or c["table"]
            rtbl_id = next((tid for (_,_,tn),tid in table_id_map.items()
                            if tn.lower()==rtbl_name.lower()), c["table_id"])
            inferred_rels.append((p, c, rel.get("parent"), rtbl_id, rel.get("type","one_to_many")))

    rels_ok = 0
    if inferred_rels and not args.skip_relationships:
        print(f"→ Setting {len(inferred_rels)} relationships…", file=sys.stderr)
        cs2 = open_cs(m)
        for parent, child, label, rtbl_id, rtype in inferred_rels:
            body = {"relationships":[{
                "parent":{"objectId":parent["id"],"subType":"attribute"},
                "child":{"objectId":child["id"],"subType":"attribute"},
                "relationshipType": rtype,
                "relationshipTable":{"objectId": rtbl_id,"subType":"logical_table"},
            }]}
            r = m.put(f"/api/model/dataModels/{model_id}/attributes/{child['id']}/relationships?changesetId={cs2}",
                      json=body)
            if r.ok:
                rels_ok += 1
                print(f"  {parent['table']}→{child['table']} [{label}]", file=sys.stderr)
            else:
                print(f"  WARN rel {label}: {r.status_code} {r.text[:200]}", file=sys.stderr)
        commit_cs(m, cs2)

    # Auto-create a hierarchy object for the longest dim chain (snowflake drill path)
    hierarchy_id = None
    if hierarchy_path:
        path_name = " > ".join(n["name"] for n in hierarchy_path)
        cs3 = open_cs(m)
        hier_body = {
            "information": {"name": f"Drill: {path_name}",
                            "description": f"Auto-detected snowflake drill path: {path_name}."},
            "attributes": [{"id": n["id"]} for n in hierarchy_path],
            "relationships": [{"parent": hierarchy_path[i]["id"], "child": hierarchy_path[i+1]["id"]}
                              for i in range(len(hierarchy_path)-1)],
        }
        for path in [f"/api/model/dataModels/{model_id}/hierarchies?changesetId={cs3}",
                     f"/api/model/dataModels/{model_id}/userHierarchies?changesetId={cs3}"]:
            r = m.post(path, json=hier_body)
            if r.ok:
                hierarchy_id = r.json().get("information",{}).get("objectId")
                print(f"  + hierarchy '{path_name}' -> {hierarchy_id}", file=sys.stderr)
                break
            else:
                print(f"    WARN hierarchy via {path}: {r.status_code} {r.text[:200]}", file=sys.stderr)
        commit_cs(m, cs3)

    summary = {
        "ok": True,
        "model_id": model_id,
        "url": f"{m.base}/app/library#/model/{model_id}",
        "tables": len(table_id_map),
        "attributes": total_attrs,
        "metrics": total_metrics,
        "inferred_relationships": rels_ok,
        "inferred_relationships_attempted": len(inferred_rels),
        "conformed_dimensions": len(conformed_cols),
        "hierarchy_path": [n["name"] for n in hierarchy_path] if hierarchy_path else None,
        "hierarchy_id": hierarchy_id,
        "data_validation": {
            "status": "not_run",
            "required": True,
            "reason": "Data correctness validation is reference-dependent. Choose a trusted comparator such as another Mosaic model, a classic report/model, warehouse SQL, a flat file, or a REST fixture before marking the build shippable.",
        },
    }

    # ── Security filters ──
    for sf in (args.security_filter or []):
        _apply_security_filter(m, model_id, sf)
    # ── ACL grants ──
    if args.grant or getattr(args, "deny", None):
        _apply_acl(m, model_id, args.grant, model_id=model_id, sub_type="data_model",
                   denies=getattr(args, "deny", []))
    # ── Translations ──
    if args.translate:
        _apply_translations(m, model_id, args.translate)
    # ── Certify ──
    if args.certify:
        _certify(m, model_id)
    # ── Publish (for in_memory) ──
    if args.data_serve_mode == "in_memory" and args.publish:
        _publish(m, model_id)
        summary["published"] = True

    print(json.dumps(summary, indent=2))


# ── Lifecycle / governance ops ────────────────────────────────────────────────
def _is_mstr_id(value: str) -> bool:
    return len(value or "") == 32 and all(c in "0123456789ABCDEFabcdef" for c in value)


def _items_from_response(body: Any, *keys) -> list:
    if isinstance(body, list):
        return body
    if not isinstance(body, dict):
        return []
    for key in keys:
        value = body.get(key)
        if isinstance(value, list):
            return value
    for key in ("items", "result", "results", "users", "objects"):
        value = body.get(key)
        if isinstance(value, list):
            return value
    return []


def _shape_user_candidate(raw: dict, source: str, input_value: str) -> dict:
    info = raw if isinstance(raw, dict) else {}
    return {k: v for k, v in {
        "input": input_value,
        "id": info.get("id") or info.get("objectId"),
        "username": info.get("username") or info.get("abbreviation"),
        "name": info.get("name"),
        "fullName": info.get("fullName"),
        "email": info.get("defaultEmailAddress") or info.get("email"),
        "type": info.get("type"),
        "subtype": info.get("subtype") or info.get("subType"),
        "source": source,
    }.items() if v not in (None, "")}


def _user_candidate_matches(candidate: dict, value: str) -> bool:
    needle = (value or "").strip().lower()
    if not needle:
        return False
    for key in ("id", "username", "name", "fullName", "email"):
        cur = str(candidate.get(key) or "").strip().lower()
        if cur and (cur == needle or needle in cur):
            return True
    return False


def _dedupe_by_id(items: list[dict]) -> list[dict]:
    seen = set()
    out = []
    for item in items:
        sig = item.get("id") or json.dumps(item, sort_keys=True)
        if sig in seen:
            continue
        seen.add(sig)
        out.append(item)
    return out


def _resolve_member_candidates(m: MSTR, name_or_id: str, limit: int = 10) -> list[dict]:
    """Resolve user/group-ish inputs to candidate user records. Read-only."""
    raw = (name_or_id or "").strip()
    if not raw:
        return []

    if _is_mstr_id(raw):
        r = m.get(f"/api/users/{raw.upper()}")
        if r.ok:
            return [_shape_user_candidate(r.json(), "users/{id}", raw)]
        return [{"input": raw, "id": raw.upper(), "source": "literal_id"}]

    terms = [raw]
    if "@" in raw:
        terms.append(raw.split("@", 1)[0])
    candidates = []

    for term in list(dict.fromkeys(t for t in terms if t)):
        for param_name in ("nameBegins", "abbreviationBegins"):
            r = m.get("/api/users", params={param_name: term, "limit": limit})
            if not r.ok:
                continue
            for item in _items_from_response(r.json(), "users"):
                cand = _shape_user_candidate(item, f"users?{param_name}", raw)
                if _user_candidate_matches(cand, raw) or _user_candidate_matches(cand, term):
                    candidates.append(cand)

        # Search fallback is useful on tenants where /users is restricted but
        # Quick Search exposes owner metadata for objects the person owns.
        r = m.get("/api/searches/results", params={
            "name": term,
            "getAncestors": "false",
            "limit": limit,
        })
        if r.ok:
            for item in _items_from_response(r.json(), "result"):
                owner = item.get("owner") or {}
                if not owner:
                    continue
                cand = _shape_user_candidate(owner, "search.owner", raw)
                if _user_candidate_matches(cand, raw) or _user_candidate_matches(cand, term):
                    candidates.append(cand)

    return _dedupe_by_id(candidates)


def _resolve_member_ids(m: MSTR, names_or_ids: list[str]) -> list[str]:
    """Resolve user/user-group names to IDs, with the tenant-specific search fallback."""
    ids = []
    for raw in names_or_ids:
        name = raw.strip()
        if not name:
            continue
        candidates = _resolve_member_candidates(m, name, limit=10)
        if candidates:
            cand_id = candidates[0].get("id")
            if cand_id:
                ids.append(cand_id)
    return list(dict.fromkeys(ids))


def _assign_security_filter_members(m: MSTR, model_id: str, sf_id: str, member_ids: list[str]):
    if not member_ids:
        return False
    patch_body = {"operationList":[{"op":"addElements", "path":"/Members", "value": member_ids}]}
    r = m.patch(f"/api/dataModels/{model_id}/securityFilters/{sf_id}/members", json=patch_body)
    if r.ok:
        return True
    # Older/local modeling endpoint shape seen in early skill iterations.
    r2 = m.post(f"/api/model/dataModels/{model_id}/securityFilters/{sf_id}/members",
                json={"users": [{"id": mid} for mid in member_ids]})
    if r2.ok:
        return True
    print(f"  WARN security-filter members: PATCH {r.status_code} {r.text[:160]} | "
          f"POST {r2.status_code} {r2.text[:160]}", file=sys.stderr)
    return False


def _normalize_mosaic_security_filter_qualification(value: Any) -> dict:
    """Return a Mosaic security-filter qualification object.

    Accepts either {"qualification": {...}} or the qualification object itself.
    """
    if not isinstance(value, dict):
        die("Mosaic security filter qualification must be a JSON object")
    if isinstance(value.get("qualification"), dict):
        value = value["qualification"]
    if isinstance(value.get("tree"), dict):
        return value
    die("Mosaic security filter qualification must contain a top-level 'tree' object")


def _infer_constant(value: str) -> dict:
    text = str(value).strip()
    if (text.startswith('"') and text.endswith('"')) or (text.startswith("'") and text.endswith("'")):
        text = text[1:-1]
    if _re.fullmatch(r"-?\d+", text):
        return {"parameterType": "constant", "constant": {"type": "int32", "value": text}}
    if _re.fullmatch(r"-?(?:\d+\.\d*|\.\d+)(?:[eE][+-]?\d+)?|-?\d+[eE][+-]?\d+", text):
        return {"parameterType": "constant", "constant": {"type": "double", "value": text}}
    return {"parameterType": "constant", "constant": {"type": "string", "value": text}}


def _parse_mosaic_security_filter_qualification(raw: str) -> dict:
    """Parse the Mosaic-only qualification half of --security-filter.

    Supported minimal form:
      <attributeId>[:<formId>]=<constant>

    For anything richer, pass @path/to/qualification.json where the file contains
    either {"qualification": {...}} or {"tree": {...}}. Classic/project security
    filters use a different endpoint family and should not call this helper.
    """
    qual = (raw or "").strip()
    if not qual:
        die("Mosaic security filter requires a qualification after NAME=")
    if qual.startswith("@"):
        return _normalize_mosaic_security_filter_qualification(load_structured_file(qual[1:]))
    if qual.startswith("{"):
        try:
            payload = json.loads(qual)
        except json.JSONDecodeError as exc:
            die(f"Mosaic security filter JSON qualification is invalid: {exc}")
        return _normalize_mosaic_security_filter_qualification(payload)

    left, sep, value = qual.partition("=")
    if sep and value:
        attr, _, form = left.strip().partition(":")
        if _is_mstr_id(attr) and (not form or _is_mstr_id(form)):
            return {"tree": {
                "type": "predicate_form_qualification",
                "predicateTree": {
                    "function": "equals",
                    "attribute": {"objectId": attr.upper(), "subType": "attribute"},
                    "form": {"objectId": (form.upper() if form else FORM_ID),
                             "subType": "attribute_form_system"},
                    "parameters": [_infer_constant(value)],
                },
            }}

    die("Mosaic security filter qualification must be @file.json, JSON, or ATTR_ID[:FORM_ID]=VALUE. "
        "Classic/project security filters use /api/model/securityFilters and /api/securityFilters/{id}/members.")


def _apply_security_filter(m: MSTR, model_id: str, spec: str):
    """Create a Mosaic data-model security filter and optionally assign members.

    This is not the classic/project security-filter helper. Classic filters are
    created through /api/model/securityFilters and assigned through
    /api/securityFilters/{id}/members.
    """
    parts = spec.split("|", 1)
    nq, users = parts[0], (parts[1].split(",") if len(parts)>1 else [])
    name, _, qual = nq.partition("=")
    name = name.strip()
    qualification = _parse_mosaic_security_filter_qualification(qual)
    cs = open_cs(m)
    r = m.post(f"/api/model/dataModels/{model_id}/securityFilters?changesetId={cs}",
               json={"information":{"name": name, "subType": "md_security_filter"},
                     "qualification": qualification,
                     "topLevel":[],"bottomLevel":[]})
    if not r.ok:
        m.delete(f"/api/model/changesets/{cs}")
        m.s.headers.pop("X-MSTR-MS-Changeset", None)
        die(f"security filter '{name}': {r.status_code} {r.text[:300]}")
    sf_id = r.json()["information"]["objectId"]
    commit_cs(m, cs)
    if users:
        member_ids = _resolve_member_ids(m, users)
        unresolved = [u.strip() for u in users if u.strip() and not _is_mstr_id(u.strip())]
        if member_ids:
            _assign_security_filter_members(m, model_id, sf_id, member_ids)
        elif unresolved:
            print(f"  WARN security filter '{name}': no members resolved from {unresolved}", file=sys.stderr)
    print(f"  ✓ security filter '{name}' -> {sf_id}", file=sys.stderr)


_RIGHT_FLAGS = {"read":1,"write":2,"delete":4,"control":32,"execute":128,"browse":64,
                "use":512,"inherit":1024,"full":255}

def _rights_mask(rights: str) -> int:
    mask = 0
    for right in rights.split(","):
        right = right.strip().lower()
        if not right:
            continue
        if right.isdigit():
            mask |= int(right)
        else:
            mask |= _RIGHT_FLAGS.get(right, 0)
    return mask


def _parse_acl_entries(entries: list[str], mode: str) -> dict[str, dict]:
    """Parse 'trusteeId:rights[:user|user_group]' specs into Data Model ACL entries."""
    acl = {}
    for entry in entries or []:
        parts = entry.split(":")
        if len(parts) < 2:
            die(f"bad ACL spec '{entry}'. expected trusteeId:rights[:user|user_group]")
        trustee_id, rights = parts[0].strip(), parts[1].strip()
        trustee_subtype = parts[2].strip() if len(parts) > 2 and parts[2].strip() else "user"
        mask = _rights_mask(rights)
        if not trustee_id or not mask:
            die(f"bad ACL spec '{entry}'. trustee and non-empty rights are required")
        cur = acl.setdefault(trustee_id, {"granted": 0, "denied": 0, "subType": trustee_subtype})
        cur["subType"] = trustee_subtype
        if mode == "deny":
            cur["denied"] |= mask
        else:
            cur["granted"] |= mask
    return acl


def _apply_acl(m: MSTR, object_id: str, grants: list[str], model_id=None,
               sub_type: str = "data_model", denies=None):
    """Apply ACLs.

    Data-model-contained objects use the Modeling endpoint:
      PATCH /api/model/dataModels/{modelId}/objects/{objectId}/acl?subType=<objectSubType>

    Entry syntax: 'trusteeId:rights[:user|user_group]'. Rights can be names
    (read,browse,execute,...) or numeric masks.
    """
    acl = {}
    for tid, ace in _parse_acl_entries(grants, "grant").items():
        acl[tid] = ace
    for tid, ace in _parse_acl_entries(denies or [], "deny").items():
        cur = acl.setdefault(tid, {"granted": 0, "denied": 0, "subType": ace.get("subType", "user")})
        cur["denied"] |= ace.get("denied", 0)
        cur["subType"] = ace.get("subType", cur["subType"])

    if not acl:
        return

    if model_id:
        cs = open_cs(m)
        r = m.patch(f"/api/model/dataModels/{model_id}/objects/{object_id}/acl?subType={sub_type}",
                    json={"acl": acl})
        if not r.ok:
            m.delete(f"/api/model/changesets/{cs}")
            die(f"data model ACL on {object_id}: {r.status_code} {r.text[:300]}")
        commit_cs(m, cs)
        print(f"  ✓ ACL set on {object_id} ({len(acl)} trustees via data model endpoint)", file=sys.stderr)
        return

    # Legacy/global fallback retained for older tenants or non-data-model objects.
    trustees = []
    for trustee_id, ace in acl.items():
        if ace.get("granted"):
            trustees.append({"trustee":{"id": trustee_id}, "rights": ace["granted"], "type":"grant"})
        if ace.get("denied"):
            trustees.append({"trustee":{"id": trustee_id}, "rights": ace["denied"], "type":"deny"})
    r = m.post(f"/api/objects/{object_id}/acl", json={"trustees": trustees, "type":"replace"})
    if not r.ok:
        die(f"acl on {object_id}: {r.status_code} {r.text[:300]}")
    print(f"  ✓ ACL set on {object_id} ({len(trustees)} entries)", file=sys.stderr)


def _apply_translations(m: MSTR, model_id: str, entries: list[str], default_sub_type="data_model"):
    """Apply name/description translations for data-model-contained objects.

    Entry syntax:
      objectId:locale=text
      objectId:subType:locale=text
      objectId:subType:locale:description=text

    Locale keys can be numeric Strategy locale IDs (for example 1033) or the
    locale tokens accepted by the tenant. Field defaults to name.
    """
    by_obj = {}
    for entry in entries or []:
        left, _, text = entry.partition("=")
        parts = left.split(":")
        if len(parts) == 2:
            obj, loc = parts
            sub_type, field = default_sub_type, "name"
        elif len(parts) == 3:
            obj, sub_type, loc = parts
            field = "name"
        elif len(parts) >= 4:
            obj, sub_type, loc, field = parts[:4]
        else:
            die(f"bad translation entry '{entry}'. expected objectId[:subType]:locale[:field]=text")
        if field not in {"name", "description"}:
            die(f"bad translation field '{field}'. use name or description")
        body = by_obj.setdefault((obj, sub_type), {})
        body.setdefault(field, {"translationValues": {}})
        body[field]["translationValues"][loc] = {"translation": text}

    if not by_obj:
        return

    if model_id and model_id != "_":
        cs = open_cs(m)
        ok = 0
        for (obj, sub_type), body in by_obj.items():
            r = m.patch(f"/api/model/dataModels/{model_id}/objects/{obj}/translations?subType={sub_type}",
                        json=body)
            if r.ok:
                ok += 1
            else:
                print(f"  WARN translate {obj}: {r.status_code} {r.text[:200]}", file=sys.stderr)
        commit_cs(m, cs)
        print(f"  ✓ translations updated for {ok}/{len(by_obj)} objects", file=sys.stderr)
        return

    print("  WARN translate: --model-id is required for data model object translations", file=sys.stderr)


def _certify(m: MSTR, object_id: str):
    r = m.s.patch(f"{m.base}/api/objects/{object_id}",
                  json={"certifiedInfo":{"certified": True}})
    if r.ok: print(f"  ✓ certified {object_id}", file=sys.stderr)
    else: print(f"  WARN certify: {r.status_code} {r.text[:200]}", file=sys.stderr)


def classify_object_surface(m: MSTR, object_id: str) -> dict:
    """Decide whether an object is Mosaic (subtype 779) vs a classic cube (776) vs other.

    Returns {"subtype": int, "surface": "mosaic_data_model|classic_cube|other", "name": str}.
    Pure read. Must be called before any endpoint that differs between surfaces (publish,
    refresh, execute, ACL, security filter, serve mode). See
    memory/reference_mosaic_vs_legacy_surfaces.md for the full pair cheat sheet.
    """
    r = m.get(f"/api/objects/{object_id}?type=3")
    if not r.ok:
        die(f"classify_object_surface: cannot GET /api/objects/{object_id}?type=3 "
            f"({r.status_code}); cannot route legacy-vs-Mosaic safely.")
    d = r.json()
    subtype = int(d.get("subtype") or 0)
    surface = ("mosaic_data_model" if subtype == 779
               else "classic_cube"   if subtype == 776
               else "other")
    return {"subtype": subtype, "surface": surface, "name": d.get("name")}


def _mosaic_publish_verified(m: MSTR, model_id: str, *, poll_seconds: int = 180,
                             poll_interval: float = 5.0) -> None:
    """Publish a Mosaic data model via the verified 3-step flow and assert completion.

    Flow (see memory/reference_mosaic_publish_path.md):
      1. POST /api/dataModels/{id}/instances           -> 204 with X-MSTR-DataModelInstanceId header
      2. POST /api/dataModels/{id}/publish             body {"tables":[{id,refreshPolicy:replace}]}
      3. poll GET /api/dataModels/{id}/publishStatus   until every table is "loaded"

    Fails loud on:
      - missing instance header
      - non-204 publish response
      - terminal error status (-2147212544 QueryEngine stall etc.)
      - timeout before every table is "loaded"
    Never falls back to /api/cubes/* — that endpoint 2xxs but leaves a Mosaic model unpublished.
    """
    # discover tables (ids required in publish body)
    r = m.get(f"/api/model/dataModels/{model_id}/tables")
    if not r.ok:
        die(f"_mosaic_publish_verified: list tables failed {r.status_code} {r.text[:200]}")
    tables = r.json().get("tables") or []
    if not tables:
        die(f"_mosaic_publish_verified: model {model_id} has 0 tables; nothing to publish.")
    tids = [t["information"]["objectId"] for t in tables]

    # 1. create instance
    r1 = m.post(f"/api/dataModels/{model_id}/instances")
    inst = r1.headers.get("X-MSTR-DataModelInstanceId") or r1.headers.get("X-Mstr-Datamodelinstanceid")
    if not inst:
        die(f"_mosaic_publish_verified: no X-MSTR-DataModelInstanceId header in "
            f"/instances response ({r1.status_code}); cannot proceed.")

    # 2. publish with tables[] body
    hdr = {"X-MSTR-DataModelInstanceId": inst}
    r2 = m.post(f"/api/dataModels/{model_id}/publish",
                headers=hdr,
                json={"tables": [{"id": tid, "refreshPolicy": "replace"} for tid in tids]})
    if r2.status_code not in (200, 202, 204):
        die(f"_mosaic_publish_verified: publish POST {r2.status_code} {r2.text[:300]}")
    print(f"  ✓ mosaic publish started instanceId={inst}", file=sys.stderr)

    # 3. poll until loaded
    deadline = time.time() + poll_seconds
    last = None
    while time.time() < deadline:
        rs = m.get(f"/api/dataModels/{model_id}/publishStatus", headers=hdr)
        try: js = rs.json()
        except Exception: js = {"raw": rs.text}
        last = js
        st = js.get("status") if isinstance(js, dict) else None
        tbl = js.get("tables") or []
        if isinstance(st, int) and st < 0:
            die(f"_mosaic_publish_verified: terminal error status={st} body={json.dumps(js)[:400]}")
        if isinstance(js, dict) and js.get("code"):
            die(f"_mosaic_publish_verified: server error {js.get('code')}: {js.get('message','')[:300]}")
        if tbl and all((t.get("status") or "") == "loaded" for t in tbl):
            print(f"  ✓ mosaic publish COMPLETE: {len(tbl)} tables loaded.", file=sys.stderr)
            return
        time.sleep(poll_interval)
    die(f"_mosaic_publish_verified: timeout after {poll_seconds}s; last status: "
        f"{json.dumps(last)[:400] if last else 'none'}. "
        f"This signature historically indicates tenant-side QueryEngineServer trouble or "
        f"dirty dataTypes; see memory/reference_mosaic_publish_path.md and "
        f"captures/2026-04-22-queryengine-publish-incident/README.md.")


def _classic_cube_publish(m: MSTR, cube_id: str) -> None:
    """Publish a classic Intelligent Cube (subtype 776). Separate from Mosaic publish."""
    r = m.post(f"/api/cubes/{cube_id}?cubeAction=publish", json={})
    if not r.ok:
        die(f"_classic_cube_publish: {r.status_code} {r.text[:300]}")
    print(f"  ✓ classic cube publish accepted (202 expected).", file=sys.stderr)


def _publish(m: MSTR, model_id: str, *, poll_seconds: int = 180,
             skip_classify: bool = False) -> None:
    """Surface-routed publish: classify subType first, never mix Mosaic/legacy paths.

    skip_classify=True bypasses GET /api/objects/{id}?type=3 and assumes the caller
    already knows the target is a Mosaic data model (subType 779). Use this when
    chaining build→publish in the same session to save one project-scoped call
    against the session cap — see feedback_build_mosaic_session_leak.md.
    """
    if skip_classify:
        print("  ↳ skip-classify: assuming Mosaic data model (subType 779)", file=sys.stderr)
        _mosaic_publish_verified(m, model_id, poll_seconds=poll_seconds)
        return
    info = classify_object_surface(m, model_id)
    if info["surface"] == "mosaic_data_model":
        _mosaic_publish_verified(m, model_id, poll_seconds=poll_seconds)
    elif info["surface"] == "classic_cube":
        _classic_cube_publish(m, model_id)
    else:
        die(f"_publish: object {model_id} is subtype {info['subtype']} ({info['name']}); "
            f"not a Mosaic data model or classic cube. Refusing to guess. See "
            f"memory/reference_mosaic_vs_legacy_surfaces.md.")


def cmd_set_serve_mode(m: MSTR, args):
    m.login(identity=True)
    info = classify_object_surface(m, args.model_id)
    if info["surface"] != "mosaic_data_model":
        die(f"set-serve-mode: dataServeMode is a Mosaic-only concept; object {args.model_id} "
            f"is subtype {info['subtype']} ({info['name']}).")
    cs = open_cs(m)
    try:
        r = m.s.patch(f"{m.base}/api/model/dataModels/{args.model_id}",
                      json={"dataServeMode": args.mode})
        if not r.ok: die(f"set-serve-mode: {r.status_code} {r.text[:300]}")
        commit_cs(m, cs)
        print(f"  ✓ dataServeMode set to {args.mode}", file=sys.stderr)
    except Exception:
        # best-effort changeset discard on failure
        try: m.s.headers.pop("X-MSTR-MS-Changeset", None)
        except Exception: pass
        raise

def cmd_publish(m: MSTR, args):
    m.login()
    _publish(m, args.model_id, poll_seconds=args.poll_seconds,
             skip_classify=getattr(args, "skip_classify", False))
def cmd_refresh(m: MSTR, args):
    m.login()
    r = m.post(f"/api/cubes/{args.model_id}/refresh",
               params={"refreshType": args.refresh_type})
    print(f"HTTP {r.status_code}: {r.text[:300]}")


# ── wire-relationships ─────────────────────────────────────────────────────────
# Post-build relationship wiring. Validates step-3 and step-5 prerequisites from
# feedback_mosaic_relationship_wiring.md before issuing any PUT, so we don't
# burn the session cap retrying on 8004ccdb (self-ref) or 8004ccc7 (invalid
# join table).

def _fetch_attribute(m: MSTR, model_id: str, attr_id: str) -> dict:
    r = m.s.get(f"{m.base}/api/model/dataModels/{model_id}/attributes/{attr_id}")
    if not r.ok:
        die(f"wire-relationships: GET attribute {attr_id}: {r.status_code} {r.text[:200]}")
    return r.json()


def _attr_table_ids(attr: dict) -> set:
    """Return the set of logical-table ids that this attribute's forms touch."""
    tids = set()
    for form in attr.get("forms", []) or []:
        for exp in form.get("expressions", []) or []:
            for t in exp.get("tables", []) or []:
                tid = t.get("objectId") or t.get("id")
                if tid:
                    tids.add(tid)
    return tids


def _list_model_attributes(m: MSTR, model_id: str) -> list:
    r = m.s.get(f"{m.base}/api/model/dataModels/{model_id}/attributes")
    if not r.ok:
        die(f"wire-relationships: list attributes: {r.status_code} {r.text[:200]}")
    d = r.json()
    return d.get("attributes") or d.get("items") or []


def _list_model_tables(m: MSTR, model_id: str) -> dict:
    r = m.s.get(f"{m.base}/api/model/dataModels/{model_id}/tables")
    if not r.ok:
        die(f"wire-relationships: list tables: {r.status_code} {r.text[:200]}")
    d = r.json()
    tbls = d.get("tables") or d.get("items") or []
    by_name = {}
    for t in tbls:
        nm = (t.get("information") or {}).get("name") or t.get("name") or ""
        tid = (t.get("information") or {}).get("objectId") or t.get("id") or t.get("objectId")
        if nm and tid:
            by_name[nm] = tid
    return by_name


def cmd_merge_attributes(m: MSTR, args):
    """Conform differently-named FK columns by merging child expressions into
    the parent attribute.

    Mosaic's auto-conformance groups expressions by IDENTICAL column names
    across tables (e.g. `PRODUCT_ID` in both `orders` and `products`). Real
    warehouses using Kimball-style prefixed surrogate keys (`i_item_sk` on
    the item dim vs `ss_item_sk` on the store_sales fact) defeat that — each
    column becomes its own attribute and joins never resolve, even with
    --conformance-map / --fk-map applied at build time (those only rename;
    they do not actually merge).

    This command takes the same {child.col: parent.col} map shape as --fk-map
    and, for each pair, PATCHes the parent attribute to gain an expression on
    the child's table, then DELETEs the now-redundant child attribute. The
    result is a true Kimball conformed dimension: one attribute whose forms
    span the dim and every fact that FKs to it.

    Role-playing edge case: when the same fact table has two FKs to the same
    dim (e.g. `cs_sold_date_sk` AND `cs_ship_date_sk` both pointing at
    `d_date_sk`), Mosaic rejects the second merge with 8004cc77 ("table is
    used in other expressions"). Those pairs are reported as skipped — they
    need their own role-playing alias attributes built separately, which is
    out of scope for this command (see memory/feedback_mosaic_role_playing_dimensions.md).

    Hint file shape (JSON or YAML), accepts either form:
        # flat — matches the --fk-map shape that `build` already accepts
        {"<CHILD_TABLE>.<CHILD_COL>": "<PARENT_TABLE>.<PARENT_COL>", ...}

        # envelope — accepted for forward-compat with extended hint metadata
        {"merges": [
            {"child":  "<CHILD_TABLE>.<CHILD_COL>",
             "parent": "<PARENT_TABLE>.<PARENT_COL>"}, ...]}

    Honors --dry-run; otherwise opens a schema-edit changeset and commits at
    the end (with discard on exception).
    """
    m.login(identity=True)
    model_id = args.model_id

    pairs = _read_merge_hints(args.hints)
    if not pairs:
        die("merge-attributes: no merge pairs found in --hints.")

    attrs = _list_model_attributes(m, model_id)
    table_ids = _list_model_tables(m, model_id)  # name -> objectId
    # Build (table_name, column_text) -> attribute index. A given attribute can
    # appear under multiple (table, col) keys if it's already partially conformed.
    by_tcol: dict[tuple[str, str], dict] = {}
    for a in attrs:
        for form in a.get("forms") or []:
            for exp in form.get("expressions") or []:
                col = (exp.get("expression") or {}).get("text", "")
                for t in exp.get("tables") or []:
                    tn = t.get("name", "")
                    if tn and col:
                        by_tcol[(tn, col)] = a

    plan = []     # list of (parent_attr, child_attr, child_table_name, child_col, label)
    skips = []    # (label, reason)
    for child_ref, parent_ref in pairs:
        try:
            ct, cc = child_ref.split(".", 1)
            pt, pc = parent_ref.split(".", 1)
        except ValueError:
            skips.append((f"{child_ref} → {parent_ref}", "malformed pair (expected TABLE.COL on both sides)"))
            continue
        label = f"{pt}.{pc} += {ct}.{cc}"
        parent = by_tcol.get((pt, pc))
        child  = by_tcol.get((ct, cc))
        if not parent:
            skips.append((label, f"parent attribute for {pt}.{pc} not found"))
            continue
        if not child:
            skips.append((label, f"child attribute for {ct}.{cc} not found"))
            continue
        if parent is child:
            skips.append((label, "already conformed (parent and child resolve to same attribute)"))
            continue
        if ct not in table_ids:
            skips.append((label, f"child table {ct!r} not in model"))
            continue
        plan.append((parent, child, ct, cc, label))

    print(f"→ merge-attributes plan: {len(plan)} to merge, {len(skips)} skipped pre-flight", file=sys.stderr)
    for label, reason in skips:
        print(f"  ✗ SKIP {label}: {reason}", file=sys.stderr)
    if args.dry_run:
        for _p, _c, _t, _col, label in plan:
            print(f"  ✓ would merge {label}", file=sys.stderr)
        print("→ dry-run; exiting without writes", file=sys.stderr)
        return
    if not plan:
        die("merge-attributes: nothing to write after validation.")

    cs = open_cs(m, schema_edit=True, release_self_locks=bool(args.release_locks))
    ok = 0
    deleted = 0
    write_skips = []
    try:
        for parent_attr, child_attr, child_table, child_col, label in plan:
            pid = (parent_attr.get("information") or {}).get("objectId")
            cid = (child_attr.get("information")  or {}).get("objectId")
            # Re-fetch parent each iteration: prior merges in this changeset
            # mutate it, and the PATCH must include the cumulative forms list.
            parent_full = _fetch_attribute(m, model_id, pid)
            normalized = ms.normalize_expressions(parent_full)
            forms = normalized.get("forms") or []
            if not forms:
                write_skips.append((label, "parent has no forms"))
                continue
            form = forms[0]
            child_tid = table_ids.get(child_table)
            new_expr = ms.make_expression(
                child_col,
                table_id=child_tid,
                table_name=child_table,
            )
            exprs = form.get("expressions") or []
            already = any(
                e.get("tables") and (e.get("tables")[0] or {}).get("name") == child_table
                and (e.get("expression") or {}).get("tokens") and
                next((tok.get("value") for tok in e["expression"]["tokens"]
                      if tok.get("type") == "column_reference"), None) == child_col
                for e in exprs
            )
            if not already:
                exprs.append(new_expr)
                form["expressions"] = exprs
            # PATCH the parent. Only forms is mutable here; everything else on
            # the parent (name, lookupTable, etc.) is preserved by Strategy.
            r = m.s.patch(
                f"{m.base}/api/model/dataModels/{model_id}/attributes/{pid}?changesetId={cs}",
                json={"forms": forms},
            )
            if not r.ok:
                err = ms.parse_mstr_error(r)
                # 8004cc77 — "table is used in other expressions". This is
                # the role-playing case: the same fact has two FKs to the
                # same dim. Skip and continue — a future role-alias build
                # step handles these.
                if err.get("code") == "8004cc77":
                    write_skips.append((label, "role-playing secondary (8004cc77) — skipped"))
                    continue
                write_skips.append((label, f"PATCH parent: {format_mstr_error(r)}"))
                continue
            print(f"  + {label}", file=sys.stderr)
            ok += 1
            # Delete the now-redundant child attribute.
            if not args.keep_children:
                dr = m.delete(f"/api/model/dataModels/{model_id}/attributes/{cid}?changesetId={cs}")
                if dr.status_code in (200, 204):
                    deleted += 1
                else:
                    write_skips.append((label, f"DELETE child {cid}: {format_mstr_error(dr)}"))
        commit_cs(m, cs)
    except Exception:
        discard_cs(m, cs)
        raise

    for label, reason in write_skips:
        print(f"  ✗ SKIP-WRITE {label}: {reason}", file=sys.stderr)
    print(
        f"→ merge-attributes committed: {ok}/{len(plan)} merges, "
        f"{deleted} child attrs deleted, {len(skips)} pre-flight skips, "
        f"{len(write_skips)} write skips",
        file=sys.stderr,
    )


def _read_merge_hints(path: str) -> list[tuple[str, str]]:
    """Read a merge-hints file in either the flat fk-map shape
    ({child.col: parent.col}) or an envelope ({"merges":[{child,parent}]}).
    Returns a list of (child_ref, parent_ref) tuples preserving input order.
    """
    if not path:
        return []
    data = load_structured_file(path) or {}
    pairs: list[tuple[str, str]] = []
    if isinstance(data, dict) and isinstance(data.get("merges"), list):
        for item in data["merges"]:
            if not isinstance(item, dict):
                continue
            c, p = item.get("child"), item.get("parent")
            if c and p:
                pairs.append((str(c), str(p)))
    elif isinstance(data, dict):
        for c, p in data.items():
            if isinstance(c, str) and isinstance(p, str):
                pairs.append((c, p))
    return pairs


def cmd_wire_relationships(m: MSTR, args):
    """Wire attribute relationships with step-3/step-5 validation.

    Reads a JSON/YAML FK-hint file listing parent→child attribute pairs plus the
    relationship_table, validates each against the live model, and issues only
    the PUTs that will succeed.

    Hint file shape:
      {"relationships": [
         {"parent_attribute": "<name or id>",
          "child_attribute":  "<name or id>",
          "relationship_table": "<name or id>",
          "type": "one_to_many"|"many_to_many"|"one_to_one"}]}
    """
    m.login(identity=True)
    model_id = args.model_id

    hints = _read_wire_hints(args.hints)
    if not hints:
        die("wire-relationships: no relationships found in --hints file.")

    # Role-playing dimension detection: when multiple hints share the same
    # (parent_attribute, relationship_table) pair, the second+ hint is a
    # role-playing secondary. Log them explicitly rather than silently
    # picking first-wins. See mosaic_safety.ROLE_PLAYING_DOC.
    hints, role_secondaries = ms.detect_role_playing_secondaries(hints)
    if role_secondaries:
        print(
            f"→ wire-relationships: {len(role_secondaries)} role-playing "
            "secondary hint(s) detected — wiring primary role only. "
            "Build alias attributes for secondaries before re-running:",
            file=sys.stderr,
        )
        for rel in role_secondaries:
            print(
                f"  ! ROLE-PLAY skip "
                f"{rel.get('parent_attribute')}→{rel.get('child_attribute')} "
                f"via {rel.get('relationship_table')}",
                file=sys.stderr,
            )

    attrs = _list_model_attributes(m, model_id)
    by_name = {}
    by_id = {}
    for a in attrs:
        info = a.get("information") or {}
        aid = info.get("objectId") or a.get("id")
        nm  = info.get("name") or a.get("name") or ""
        if aid:
            by_id[aid] = a
            if nm:
                by_name.setdefault(nm.lower(), a)
    tables_by_name = _list_model_tables(m, model_id)

    def _resolve_attr(ref: str) -> dict:
        if not ref: return None
        if ref in by_id: return by_id[ref]
        return by_name.get(ref.lower())

    def _resolve_table(ref: str) -> str:
        if not ref: return None
        if ref in tables_by_name.values(): return ref
        return tables_by_name.get(ref)

    plan = []   # rows ready to PUT
    skips = []  # rows skipped with reason

    for h in hints:
        parent = _resolve_attr(h.get("parent_attribute"))
        child  = _resolve_attr(h.get("child_attribute"))
        rtbl_id = _resolve_table(h.get("relationship_table"))
        rtype  = h.get("type","one_to_many")
        label = f"{h.get('parent_attribute')}→{h.get('child_attribute')} via {h.get('relationship_table')}"

        if not parent:
            skips.append((label, f"parent attribute {h.get('parent_attribute')!r} not found"))
            continue
        if not child:
            skips.append((label, f"child attribute {h.get('child_attribute')!r} not found"))
            continue
        if not rtbl_id:
            skips.append((label, f"relationship_table {h.get('relationship_table')!r} not found in model"))
            continue

        # Step-3: forbid self-reference.
        p_id = (parent.get("information") or {}).get("objectId") or parent.get("id")
        c_id = (child.get("information")  or {}).get("objectId") or child.get("id")
        if p_id == c_id:
            skips.append((label, "parent and child resolve to same attribute (would trip 8004ccdb)"))
            continue

        # Fetch full attribute definitions (/attributes list may omit forms[].expressions details).
        p_full = _fetch_attribute(m, model_id, p_id)
        c_full = _fetch_attribute(m, model_id, c_id)
        p_tids = _attr_table_ids(p_full)
        c_tids = _attr_table_ids(c_full)

        # Step-5: both endpoints must have an expression on the relationship table.
        missing = []
        if rtbl_id not in p_tids: missing.append("parent")
        if rtbl_id not in c_tids: missing.append("child")
        if missing:
            skips.append((label,
                f"{'+'.join(missing)} has no expression on relationship_table (would trip 8004ccc7); "
                f"PATCH to add the missing expression first — see reference_strategy_object_cloning.md"))
            continue

        plan.append((p_id, c_id, rtbl_id, rtype, label))

    # Report plan.
    print(f"→ wire-relationships plan: {len(plan)} to write, {len(skips)} skipped", file=sys.stderr)
    for label, reason in skips:
        print(f"  ✗ SKIP {label}: {reason}", file=sys.stderr)
    if args.dry_run:
        print(f"→ dry-run; exiting without PUTs", file=sys.stderr)
        for p_id, c_id, rtbl_id, rtype, label in plan:
            print(f"  ✓ would PUT {label} [{rtype}]", file=sys.stderr)
        return

    if not plan:
        die("wire-relationships: nothing to write after validation. See skip reasons above.")

    # Group plan rows by child attribute so we PUT each child once with all
    # its parents merged in — this respects the merge contract of
    # put_relationships_merged() and minimizes round-trips.
    by_child: dict[str, list[tuple] ] = {}
    for p_id, c_id, rtbl_id, rtype, label in plan:
        by_child.setdefault(c_id, []).append((p_id, c_id, rtbl_id, rtype, label))

    cs = open_cs(m, schema_edit=False)
    ok = 0
    try:
        for c_id, rows in by_child.items():
            new_rels = []
            labels = []
            for p_id, _c_id, rtbl_id, rtype, label in rows:
                new_rels.append({
                    "parent": {"objectId": p_id, "subType": "attribute"},
                    "child":  {"objectId": c_id, "subType": "attribute"},
                    "relationshipType": rtype,
                    "relationshipTable": {
                        "objectId": rtbl_id, "subType": "logical_table"
                    },
                })
                labels.append(label)
            success, added, total, err = put_relationships_merged(
                m, model_id, c_id, new_rels, cs, replace=args.replace
            )
            if success:
                ok += added
                action = "REPLACED" if args.replace else f"MERGED (+{added}/{total})"
                for label in labels:
                    print(f"  ✓ {label} [{action}]", file=sys.stderr)
            else:
                for label in labels:
                    print(f"  ✗ {label}: {err}", file=sys.stderr)
        commit_cs(m, cs)
    except Exception:
        discard_cs(m, cs)
        raise
    print(
        f"→ wire-relationships committed: {ok}/{len(plan)} new rels written "
        f"(merge-aware), {len(skips)} skipped pre-flight, "
        f"{len(role_secondaries)} role-playing secondaries",
        file=sys.stderr,
    )


def _read_wire_hints(path: str) -> list:
    """Read JSON or YAML FK-hint file. Accepts either a {relationships:[...]}
    envelope or a bare list."""
    if not path: return []
    with open(path) as f:
        text = f.read()
    data = None
    try:
        data = json.loads(text)
    except Exception:
        try:
            import yaml  # type: ignore
            data = yaml.safe_load(text)
        except Exception:
            die(f"wire-relationships: cannot parse --hints file {path} as JSON or YAML")
    if isinstance(data, dict):
        return data.get("relationships") or []
    if isinstance(data, list):
        return data
    return []


def cmd_build_from_schema_objects(m: MSTR, args):
    """Build a Mosaic data model from existing classic schema object IDs.

    Pipeline:
      1. Read classic attribute/fact/metric definitions.
      2. Resolve physical tables referenced by those objects.
      3. Discover warehouse datasource/schema/name for each.
      4. Create the Mosaic model shell.
      5. Add physical tables.
      6. Translate + batch-create attributes and fact metrics (CS1).
      7. Wire relationships from classic attribute relationship arrays (CS2).
      8. Translate + create derived metrics bottom-up (CS3).
      9. Optionally publish in-memory.
     10. Write a JSON review file with warnings + created object IDs.
    """
    m.login(identity=True)

    attr_ids   = _parse_id_list(getattr(args, "attribute_ids", "") or "")
    fact_ids   = _parse_id_list(getattr(args, "fact_ids", "") or "")
    metric_ids = _parse_id_list(getattr(args, "metric_ids", "") or "")

    if not (attr_ids or fact_ids or metric_ids):
        die("provide at least one of --attribute-ids, --fact-ids, --metric-ids")

    print(f"→ Input: {len(attr_ids)} attributes, {len(fact_ids)} facts, "
          f"{len(metric_ids)} metrics", file=sys.stderr)

    all_warnings: list[str] = []
    rate_sleep = 0.05 if (len(attr_ids) + len(fact_ids) + len(metric_ids)) > 200 else 0

    # ── Read classic object definitions ──────────────────────────────────────
    print("→ Reading classic attribute definitions…", file=sys.stderr)
    attr_defs: dict[str, dict] = {}
    for aid in attr_ids:
        r = m.get(f"/api/model/attributes/{aid}", params={"showExpressionAs": "tree"})
        if not r.ok:
            all_warnings.append(f"attribute {aid}: read failed {r.status_code} — skipped")
            continue
        attr_defs[aid] = r.json()
        if rate_sleep:
            time.sleep(rate_sleep)
        if m.verbose:
            n = (attr_defs[aid].get("information") or {}).get("name", "?")
            print(f"  attr {aid}: {n}", file=sys.stderr)

    print("→ Reading classic fact definitions…", file=sys.stderr)
    fact_defs: dict[str, dict] = {}
    for fid in fact_ids:
        r = m.get(f"/api/model/facts/{fid}", params={"showExpressionAs": "tree"})
        if not r.ok:
            all_warnings.append(f"fact {fid}: read failed {r.status_code} — skipped")
            continue
        fact_defs[fid] = r.json()
        if rate_sleep:
            time.sleep(rate_sleep)

    print("→ Reading classic metric definitions…", file=sys.stderr)
    metric_defs: dict[str, dict] = {}
    for mid in metric_ids:
        r = m.get(f"/api/model/metrics/{mid}", params={"showExpressionAs": "tree"})
        if not r.ok:
            all_warnings.append(f"metric {mid}: read failed {r.status_code} — skipped")
            continue
        metric_defs[mid] = r.json()
        if rate_sleep:
            time.sleep(rate_sleep)

    # ── Collect referenced classic table IDs ─────────────────────────────────
    classic_table_ids: set[str] = set()
    for adef in attr_defs.values():
        classic_table_ids |= sot.extract_table_ids_from_attribute(adef)
    for fdef in fact_defs.values():
        classic_table_ids |= sot.extract_table_ids_from_fact(fdef)

    if not classic_table_ids:
        die("no physical table references found in any object definition. "
            "Verify the IDs are correct and showExpressionAs=tree returns expressions.")

    print(f"→ Resolving {len(classic_table_ids)} classic table(s)…", file=sys.stderr)
    classic_table_meta: dict[str, dict] = {}
    for tid in classic_table_ids:
        r = m.get(f"/api/model/tables/{tid}")
        if not r.ok:
            all_warnings.append(
                f"table {tid}: read failed {r.status_code} — referencing "
                "objects may have unmapped expressions"
            )
            continue
        classic_table_meta[tid] = r.json()

    # Group tables by (datasource_id, schema) → list of (classic_id, table_name)
    source_groups: dict[tuple[str, str], list[tuple[str, str]]] = {}
    for tid, tmeta in classic_table_meta.items():
        pt = tmeta.get("physicalTable") or {}
        ds_obj = pt.get("databaseInstance") or {}
        ds_id  = ds_obj.get("objectId") or ds_obj.get("id") or args.instance_id
        schema = pt.get("namespace") or args.schema or ""
        tname  = pt.get("tableName") or (tmeta.get("information") or {}).get("name") or ""
        if not (ds_id and tname):
            all_warnings.append(
                f"table {tid}: cannot determine datasource or table name — skipped"
            )
            continue
        source_groups.setdefault((ds_id, schema), []).append((tid, tname))

    if not source_groups:
        die("Could not resolve any source tables. Check that classic table object IDs "
            "are readable and return physicalTable.databaseInstance.")

    # ── Create model shell ───────────────────────────────────────────────────
    print(f"→ Creating model '{args.name}'…", file=sys.stderr)
    serve_mode = "in_memory" if args.publish else args.data_serve_mode
    r = m.post("/api/model/dataModels", json={
        "information": {"name": args.name, "destinationFolderId": args.dest_folder},
        "dataServeMode": serve_mode,
    })
    if not r.ok:
        die(f"create model: {r.status_code} {r.text[:400]}")
    model_id = r.json()["information"]["objectId"]
    print(f"  model_id={model_id}", file=sys.stderr)

    # ── Add physical tables (CS1 begins) ─────────────────────────────────────
    logical_table_map: dict[str, str] = {}
    cs1 = open_cs(m)
    try:
        for (ds_id, schema), entries in source_groups.items():
            for classic_tid, tname in entries:
                tbl_body = _make_pipeline_table_body(m, ds_id, schema, tname)
                if tbl_body is None:
                    all_warnings.append(
                        f"table {tname}: could not fetch warehouse metadata — skipped"
                    )
                    continue
                rr = m.post(f"/api/model/dataModels/{model_id}/tables", json=tbl_body)
                if not rr.ok:
                    all_warnings.append(
                        f"add table {tname}: {rr.status_code} {rr.text[:200]}"
                    )
                    continue
                mosaic_tid = rr.json()["information"]["objectId"]
                logical_table_map[classic_tid] = mosaic_tid
                # Also map any other classic tables that resolved to the same warehouse name
                for other_cid, other_meta in classic_table_meta.items():
                    if other_cid == classic_tid:
                        continue
                    other_pt = other_meta.get("physicalTable") or {}
                    if other_pt.get("tableName") == tname:
                        logical_table_map.setdefault(other_cid, mosaic_tid)
                print(f"  + table {tname} → {mosaic_tid}", file=sys.stderr)

        # ── Translate + batch-create attributes ──────────────────────────────
        print(f"→ Translating {len(attr_defs)} attribute(s)…", file=sys.stderr)
        attr_ops: list[dict] = []
        attr_id_order: list[str] = []
        attr_id_to_mosaic: dict[str, str] = {}

        for classic_id, adef in attr_defs.items():
            payload, warns = sot.translate_attribute(adef, logical_table_map)
            all_warnings.extend([f"[attr {classic_id}] {w}" for w in warns])
            attr_ops.append({"op": "create", "path": "/attributes", "value": payload})
            attr_id_order.append(classic_id)

        if attr_ops:
            passed, failed = batch_call(m, model_id, cs1, attr_ops, atomic=False)
            for f in failed:
                all_warnings.append(f"[batch attr] failed op: {json.dumps(f)[:200]}")
            for i, result in enumerate(passed):
                if i >= len(attr_id_order):
                    break
                response = result.get("response") or result
                obj_id = (response.get("information") or {}).get("objectId")
                if obj_id:
                    attr_id_to_mosaic[attr_id_order[i]] = obj_id

        # ── Translate + batch-create fact metrics ────────────────────────────
        print(f"→ Translating {len(fact_defs)} fact(s)…", file=sys.stderr)
        fact_ops: list[dict] = []
        fact_id_order: list[str] = []
        fact_id_to_mosaic: dict[str, str] = {}

        for classic_id, fdef in fact_defs.items():
            payload, warns = sot.translate_fact_to_factmetric(fdef, logical_table_map)
            all_warnings.extend([f"[fact {classic_id}] {w}" for w in warns])
            fact_ops.append({"op": "create", "path": "/factMetrics", "value": payload})
            fact_id_order.append(classic_id)

        if fact_ops:
            passed, failed = batch_call(m, model_id, cs1, fact_ops, atomic=False)
            for f in failed:
                all_warnings.append(f"[batch fact] failed op: {json.dumps(f)[:200]}")
            for i, result in enumerate(passed):
                if i >= len(fact_id_order):
                    break
                response = result.get("response") or result
                obj_id = (response.get("information") or {}).get("objectId")
                if obj_id:
                    fact_id_to_mosaic[fact_id_order[i]] = obj_id

        commit_cs(m, cs1)
        cs1 = None
        print(f"  CS1 committed ({len(attr_id_to_mosaic)} attrs, "
              f"{len(fact_id_to_mosaic)} factMetrics)", file=sys.stderr)
    except Exception:
        if cs1:
            discard_cs(m, cs1)
        raise

    # ── Wire relationships (CS2) ─────────────────────────────────────────────
    rel_count = 0
    cs2 = open_cs(m)
    try:
        for classic_child_id, adef in attr_defs.items():
            mosaic_child_id = attr_id_to_mosaic.get(classic_child_id)
            if not mosaic_child_id:
                continue
            for rel in (adef.get("relationships") or []):
                parent_classic_id = (rel.get("parent") or {}).get("objectId")
                if not parent_classic_id:
                    continue
                mosaic_parent_id = attr_id_to_mosaic.get(parent_classic_id)
                if not mosaic_parent_id:
                    all_warnings.append(
                        f"[rel] child {classic_child_id}: parent "
                        f"{parent_classic_id} not in translated set — relationship skipped"
                    )
                    continue
                rel_table_classic = (rel.get("relationshipTable") or {}).get("objectId")
                rel_table_mosaic = (
                    logical_table_map.get(rel_table_classic) if rel_table_classic else None
                )
                rel_body = {
                    "relationships": [{
                        "parent": {"objectId": mosaic_parent_id, "subType": "attribute"},
                        "child":  {"objectId": mosaic_child_id,  "subType": "attribute"},
                        "relationshipType": rel.get("relationshipType", "one_to_many"),
                    }]
                }
                if rel_table_mosaic:
                    rel_body["relationships"][0]["relationshipTable"] = {
                        "objectId": rel_table_mosaic, "subType": "logical_table",
                    }
                rr = m.put(
                    f"/api/model/dataModels/{model_id}/attributes/"
                    f"{mosaic_child_id}/relationships?changesetId={cs2}",
                    json=rel_body,
                )
                if not rr.ok:
                    all_warnings.append(
                        f"[rel] {classic_child_id}→{parent_classic_id}: "
                        f"{rr.status_code} {rr.text[:200]}"
                    )
                else:
                    rel_count += 1
        commit_cs(m, cs2)
        cs2 = None
        print(f"  CS2 committed ({rel_count} relationships)", file=sys.stderr)
    except Exception:
        if cs2:
            discard_cs(m, cs2)
        raise

    # ── Translate + create derived metrics (CS3, bottom-up) ──────────────────
    metric_id_to_mosaic: dict[str, str] = {}
    if metric_defs:
        print(f"→ Translating {len(metric_defs)} metric(s) in dependency order…",
              file=sys.stderr)
        try:
            ordered_ids = sot.build_metric_translation_order(metric_defs)
        except ValueError as e:
            all_warnings.append(
                f"[metrics] dependency cycle detected: {e} — input order used"
            )
            ordered_ids = list(metric_defs.keys())

        cs3 = open_cs(m)
        try:
            for classic_id in ordered_ids:
                mdef = metric_defs.get(classic_id)
                if not mdef:
                    continue
                payload, warns = sot.translate_metric(
                    mdef, fact_id_to_mosaic, metric_id_to_mosaic,
                    attr_id_to_mosaic_id=attr_id_to_mosaic,
                )
                all_warnings.extend([f"[metric {classic_id}] {w}" for w in warns])
                mtype = sot.classify_metric(mdef)
                path_suffix = "/factMetrics" if mtype == "fact_metric" else "/metrics"
                rr = m.post(
                    f"/api/model/dataModels/{model_id}{path_suffix}", json=payload
                )
                if not rr.ok:
                    all_warnings.append(
                        f"[metric {classic_id}] create failed: "
                        f"{rr.status_code} {rr.text[:200]}"
                    )
                    continue
                new_id = (rr.json().get("information") or {}).get("objectId")
                if new_id:
                    metric_id_to_mosaic[classic_id] = new_id
                    print(f"  metric {classic_id} → {new_id}", file=sys.stderr)
            commit_cs(m, cs3)
            cs3 = None
            print(f"  CS3 committed ({len(metric_id_to_mosaic)} metrics)",
                  file=sys.stderr)
        except Exception:
            if cs3:
                discard_cs(m, cs3)
            raise

    # ── Optional publish ─────────────────────────────────────────────────────
    if args.publish:
        print(f"→ Publishing model {model_id} in-memory…", file=sys.stderr)
        rr = m.post(f"/api/cubes/{model_id}?cubeAction=publish")
        if not rr.ok:
            all_warnings.append(
                f"publish: {rr.status_code} {rr.text[:200]} — model exists "
                "but is not materialized"
            )
        else:
            print("  publish accepted (202). Poll publishStatus to confirm.",
                  file=sys.stderr)

    # ── Review file ──────────────────────────────────────────────────────────
    review = {
        "model_id": model_id,
        "model_url": f"{m.base}/app/library#/model/{model_id}",
        "translated": {
            "attributes": len(attr_id_to_mosaic),
            "factMetrics": len(fact_id_to_mosaic),
            "metrics": len(metric_id_to_mosaic),
            "relationships": rel_count,
        },
        "warnings": all_warnings,
    }
    if args.review_file:
        with open(args.review_file, "w", encoding="utf-8") as f:
            json.dump(review, f, indent=2)
        print(f"→ Review file: {args.review_file}", file=sys.stderr)

    if all_warnings:
        print(f"\n⚠  {len(all_warnings)} warning(s) — see review file or stderr above.",
              file=sys.stderr)

    print(f"\n✓ Model: {m.base}/app/library#/model/{model_id}", file=sys.stderr)
    print(json.dumps(review, indent=2))


def cmd_delete_model(m: MSTR, args):
    if not args.yes:
        die("delete-model requires --yes after verifying the Mosaic data model id")
    m.login()
    r = m.delete(f"/api/objects/{args.model_id}?type=3")
    print(f"HTTP {r.status_code}: {r.text[:300]}")
def cmd_set_acl(m: MSTR, args):
    m.login(identity=bool(args.model_id)); _apply_acl(m, args.object_id, args.grant, model_id=args.model_id,
                                                       sub_type=args.sub_type, denies=args.deny)
def cmd_add_security_filter(m: MSTR, args):
    m.login(identity=True); _apply_security_filter(m, args.model_id, args.spec)
def cmd_translate(m: MSTR, args):
    m.login(identity=True); _apply_translations(m, args.model_id, args.entry, default_sub_type=args.sub_type)
def cmd_certify(m: MSTR, args):
    m.login(); _certify(m, args.object_id)


def _load_records_file(path: str, list_keys=("users", "items", "rows", "members")) -> list:
    ext = path.lower().rsplit(".", 1)[-1]
    if ext == "csv":
        with open(path, encoding="utf-8-sig", newline="") as f:
            return [{str(k).strip(): v for k, v in row.items()} for row in csv.DictReader(f)]
    data = load_structured_file(path)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in list_keys:
            if isinstance(data.get(key), list):
                return data[key]
        return [data]
    die(f"{path}: expected a list, object, or CSV rows")


def _first_present(row: dict, names: list[str]):
    for name in names:
        for key in (name, name.lower(), name.upper()):
            value = row.get(key)
            if value not in (None, ""):
                return value
    return None


def _split_list_value(value) -> list:
    if value in (None, ""):
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    return [v.strip() for v in _re.split(r"[;,]", str(value)) if v.strip()]


def _parse_bool(value, default=None):
    if value in (None, ""):
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"true", "t", "yes", "y", "1", "enabled"}:
        return True
    if text in {"false", "f", "no", "n", "0", "disabled"}:
        return False
    return default


def _user_identifier_from_record(row) -> str:
    if isinstance(row, str):
        return row
    if not isinstance(row, dict):
        return ""
    return str(_first_present(row, ["id", "username", "email", "name", "fullName", "full_name", "displayName"]) or "")


def cmd_resolve_users(m: MSTR, args):
    """Resolve user IDs from names, usernames, emails, or files before security/admin writes."""
    m.login()
    inputs = list(args.user or [])
    for path in args.file or []:
        inputs.extend(_user_identifier_from_record(row) for row in _load_records_file(path))
    inputs = [i.strip() for i in inputs if str(i).strip()]

    resolved, ambiguous, unresolved = [], [], []
    for value in inputs:
        candidates = _resolve_member_candidates(m, value, limit=args.limit)
        if not candidates:
            unresolved.append(value)
        elif len(candidates) == 1 or args.first:
            resolved.append(candidates[0])
        else:
            ambiguous.append({"input": value, "candidates": candidates})

    print(json.dumps({
        "ok": True,
        "resolved": resolved,
        "ambiguous": ambiguous,
        "unresolved": unresolved,
    }, indent=2))


def cmd_search_objects(m: MSTR, args):
    """Quick Search wrapper for finding object IDs before updates."""
    m.login()
    params = {
        "name": args.name,
        "pattern": args.pattern,
        "getAncestors": str(args.ancestors).lower(),
        "offset": args.offset,
        "limit": args.limit,
    }
    if args.type:
        params["type"] = [int(t) for t in args.type]
    if args.project_id_filter:
        params["projectId"] = args.project_id_filter
    r = m.get("/api/searches/results", params=params)
    if not r.ok:
        die(f"search-objects: {r.status_code} {r.text[:300]}")
    body = r.json() if r.text else {}
    rows = []
    for item in _items_from_response(body, "result"):
        subtype = item.get("subtype") or item.get("subType")
        if args.subtype and str(subtype) != str(args.subtype):
            continue
        rows.append({k: v for k, v in {
            "id": item.get("id") or item.get("objectId"),
            "name": item.get("name"),
            "type": item.get("type"),
            "subtype": subtype,
            "projectId": item.get("projectId"),
            "owner": (item.get("owner") or {}).get("name") if isinstance(item.get("owner"), dict) else item.get("owner"),
            "ancestors": item.get("ancestors") if args.ancestors else None,
        }.items() if v not in (None, "")})
    print(json.dumps({
        "ok": True,
        "count": len(rows),
        "objects": rows if not args.raw else body,
    }, indent=2))


MODEL_OBJECT_KINDS = {
    "data_model": {"path": "/api/model/dataModels/{model_id}", "needs_model": True, "changeset": False},
    "attribute": {"path": "/api/model/dataModels/{model_id}/attributes/{object_id}", "needs_model": True, "changeset": True},
    "fact_metric": {"path": "/api/model/dataModels/{model_id}/factMetrics/{object_id}", "needs_model": True, "changeset": True},
    "metric": {"alias": "fact_metric"},
    "table": {"path": "/api/model/dataModels/{model_id}/tables/{object_id}", "needs_model": True, "changeset": True},
    "filter": {"path": "/api/model/dataModels/{model_id}/filters/{object_id}", "needs_model": True, "changeset": True},
    "security_filter": {"path": "/api/model/dataModels/{model_id}/securityFilters/{object_id}", "needs_model": True, "changeset": True},
    "transformation": {"path": "/api/model/dataModels/{model_id}/transformations/{object_id}", "needs_model": True, "changeset": True},
    "hierarchy": {"path": "/api/model/dataModels/{model_id}/hierarchies/{object_id}", "needs_model": True, "changeset": True},
    "project_attribute": {"path": "/api/model/attributes/{object_id}", "needs_model": False, "changeset": True},
    "legacy_attribute": {"alias": "project_attribute"},
    "project_metric": {"path": "/api/model/metrics/{object_id}", "needs_model": False, "changeset": True},
    "legacy_metric": {"alias": "project_metric"},
    "project_fact": {"path": "/api/model/facts/{object_id}", "needs_model": False, "changeset": True},
    "project_table": {"path": "/api/model/tables/{object_id}", "needs_model": False, "changeset": True},
}


def _kind_info(kind: str) -> dict:
    info = MODEL_OBJECT_KINDS.get(kind)
    if not info:
        die(f"unknown kind '{kind}'. expected one of {sorted(MODEL_OBJECT_KINDS)}")
    while "alias" in info:
        info = MODEL_OBJECT_KINDS[info["alias"]]
    return info


def _model_object_path(kind: str, model_id: str, object_id: str) -> tuple[str, dict]:
    info = _kind_info(kind)
    if info.get("needs_model") and not model_id:
        die(f"--model-id is required for kind {kind}")
    if "{object_id}" in info["path"] and not object_id:
        die(f"--object-id is required for kind {kind}")
    path = info["path"].format(model_id=model_id or object_id, object_id=object_id or model_id)
    return path, info


def _expression_params(args) -> dict:
    params = {}
    if getattr(args, "show_expression_as", None):
        params["showExpressionAs"] = args.show_expression_as
    if getattr(args, "fields", None):
        params["fields"] = args.fields
    if getattr(args, "show_advanced_properties", False):
        params["showAdvancedProperties"] = "true"
    return params


def cmd_get_model_object(m: MSTR, args):
    path, _ = _model_object_path(args.kind, args.model_id, args.object_id)
    m.login(identity=False)
    r = m.get(path, params=_expression_params(args) or None)
    out = {"ok": r.ok, "status": r.status_code, "path": path}
    try:
        out["body"] = r.json()
    except ValueError:
        out["body"] = r.text[:args.text_limit]
        out["body_truncated"] = len(r.text) > args.text_limit
    if args.out and out.get("body") is not None:
        with open(args.out, "w", encoding="utf-8") as f:
            if isinstance(out["body"], (dict, list)):
                json.dump(out["body"], f, indent=2)
            else:
                f.write(str(out["body"]))
        out["saved_to"] = args.out
    print(json.dumps(out, indent=2))


def cmd_patch_model_object(m: MSTR, args):
    """Patch/put a Mosaic-contained or legacy schema object through Modeling Service."""
    if not args.yes:
        die("patch-model-object requires --yes after you have reviewed the target ID and request body")
    body = _load_json_arg(args.json, args.json_file)
    if body is None:
        die("patch-model-object requires --json or --json-file")
    path, info = _model_object_path(args.kind, args.model_id, args.object_id)
    m.login(identity=info.get("needs_model", False))
    before = None
    if args.before_out or args.include_before:
        r0 = m.get(path, params=_expression_params(args) or None)
        if r0.ok:
            before = r0.json() if r0.text else {}
            if args.before_out:
                with open(args.before_out, "w", encoding="utf-8") as f:
                    json.dump(before, f, indent=2)

    cs = None
    try:
        if info.get("changeset"):
            cs = open_cs(m)
        request = getattr(m, args.method.lower())
        r = request(path, params=_expression_params(args) or None, json=body)
        if not r.ok:
            if cs:
                m.delete(f"/api/model/changesets/{cs}")
                m.s.headers.pop("X-MSTR-MS-Changeset", None)
            die(f"patch-model-object {args.method} {path}: {r.status_code} {r.text[:500]}")
        updated = r.json() if r.text else {}
        if cs:
            commit_cs(m, cs)
        verify = m.get(path, params=_expression_params(args) or None)
        out = {
            "ok": verify.ok,
            "method": args.method,
            "path": path,
            "changeset": cs,
            "updated_in_changeset": updated,
            "verified": verify.json() if verify.ok and verify.text else verify.text[:args.text_limit],
        }
        if before is not None and args.include_before:
            out["before"] = before
        print(json.dumps(out, indent=2))
    finally:
        if cs:
            m.s.headers.pop("X-MSTR-MS-Changeset", None)


USER_CREATION_FIELDS = {
    "username": ["username", "user", "login", "loginName"],
    "fullName": ["fullName", "full_name", "name", "displayName"],
    "description": ["description"],
    "password": ["password"],
    "enabled": ["enabled", "status"],
    "passwordModifiable": ["passwordModifiable", "password_modifiable"],
    "passwordAutoExpire": ["passwordAutoExpire", "password_auto_expire"],
    "passwordExpirationDate": ["passwordExpirationDate", "password_expiration_date"],
    "passwordExpirationFrequency": ["passwordExpirationFrequency", "password_expiration_frequency"],
    "requireNewPassword": ["requireNewPassword", "require_new_password"],
    "standardAuth": ["standardAuth", "standard_auth"],
    "ldapdn": ["ldapdn", "ldap_dn"],
    "trustId": ["trustId", "trust_id"],
    "ssoScopes": ["ssoScopes", "sso_scopes"],
    "databaseAuthLogin": ["databaseAuthLogin", "database_auth_login"],
    "memberships": ["memberships", "groups", "groupIds", "group_ids"],
    "languageId": ["languageId", "language_id"],
}


def _redact_secrets(value):
    if isinstance(value, dict):
        return {k: ("***" if k.lower() in {"password", "oldpassword", "newpassword"} else _redact_secrets(v))
                for k, v in value.items()}
    if isinstance(value, list):
        return [_redact_secrets(v) for v in value]
    return value


def _user_creation_payload(row, default_password: str = "") -> tuple[dict, str]:
    if not isinstance(row, dict):
        row = {"username": str(row)}
    body = dict(row.get("body") or {}) if isinstance(row.get("body"), dict) else {}
    for out_key, aliases in USER_CREATION_FIELDS.items():
        value = _first_present(row, aliases)
        if value in (None, ""):
            continue
        if out_key in {"enabled", "passwordModifiable", "passwordAutoExpire", "requireNewPassword", "standardAuth"}:
            parsed = _parse_bool(value)
            if parsed is not None:
                body[out_key] = parsed
        elif out_key in {"memberships", "ssoScopes"}:
            body[out_key] = _split_list_value(value)
        elif out_key == "passwordExpirationFrequency":
            body[out_key] = int(value)
        else:
            body[out_key] = str(value)

    email = str(_first_present(row, ["email", "mail", "defaultEmailAddress"]) or "").strip()
    if not body.get("username") and email:
        body["username"] = email
    if not body.get("fullName"):
        body["fullName"] = body.get("username")
    if default_password and not body.get("password"):
        body["password"] = default_password
    if not body.get("username") or not body.get("fullName"):
        die(f"user row missing username/fullName: {_redact_secrets(row)}")
    return body, email


def _has_exact_user_match(candidates: list[dict], username: str, email: str = "") -> dict:
    username = (username or "").lower()
    email = (email or "").lower()
    for cand in candidates:
        fields = [cand.get("id"), cand.get("username"), cand.get("name"), cand.get("fullName"), cand.get("email")]
        for value in fields:
            text = str(value or "").lower()
            if text and (text == username or (email and text == email)):
                return cand
    return {}


def cmd_create_users(m: MSTR, args):
    """Bulk create users from CSV/JSON/YAML. Dry-run by default; --yes performs writes."""
    rows = []
    for path in args.file:
        rows.extend(_load_records_file(path, list_keys=("users", "items", "rows")))
    default_password = os.environ.get(args.default_password_env, "")
    planned, created, skipped, errors = [], [], [], []

    if args.yes or args.check_existing:
        m.login()

    for row in rows:
        body, email = _user_creation_payload(row, default_password=default_password)
        existing = {}
        if args.yes or args.check_existing:
            candidates = _resolve_member_candidates(m, body["username"], limit=5)
            if email:
                candidates.extend(_resolve_member_candidates(m, email, limit=5))
            existing = _has_exact_user_match(_dedupe_by_id(candidates), body["username"], email)
        if existing and not args.allow_existing:
            skipped.append({"reason": "already_exists", "input": body["username"], "existing": existing})
            continue
        if not args.yes:
            planned.append({"user": _redact_secrets(body), "email_address": email or None})
            continue

        params = {}
        source_user_id = _first_present(row, ["sourceUserId", "source_user_id"]) if isinstance(row, dict) else None
        if source_user_id or args.source_user_id:
            params["sourceUserId"] = source_user_id or args.source_user_id
        r = m.post("/api/users", params=params or None, json=body)
        if not r.ok:
            errors.append({"user": body["username"], "status": r.status_code, "body": r.text[:500]})
            continue
        user = r.json() if r.text else {}
        user_id = user.get("id")
        address = None
        if email and user_id and not args.skip_email_address:
            ar = m.post(f"/api/users/{user_id}/addresses", json={
                "name": args.email_address_name,
                "deliveryMode": "EMAIL",
                "device": "GENERIC_EMAIL",
                "value": email,
                "isDefault": True,
            })
            address = {"ok": ar.ok, "status": ar.status_code}
            if ar.ok and ar.text:
                address["body"] = ar.json()
            elif not ar.ok:
                address["body"] = ar.text[:300]
        created.append({"user": _redact_secrets(user), "email_address": address})

    print(json.dumps({
        "ok": not errors,
        "dry_run": not args.yes,
        "planned": planned,
        "created": created,
        "skipped": skipped,
        "errors": errors,
    }, indent=2))


def cmd_create_transformation(m: MSTR, args):
    """Create a time-shift transformation.
    --member: 'attributeId=offset' (repeatable). offset is integer (-1 = prior period)."""
    m.login(identity=True)
    members = []
    for spec in args.member:
        aid, _, off = spec.partition("=")
        members.append({"attribute":{"objectId": aid.strip(), "subType":"attribute"},
                        "offset": int(off)})
    cs = open_cs(m)
    r = m.post(f"/api/model/dataModels/{args.model_id}/transformations?changesetId={cs}",
               json={"information":{"name": args.name}, "members": members})
    if not r.ok: die(f"create transformation: {r.status_code} {r.text[:300]}")
    tid = r.json()["information"]["objectId"]
    commit_cs(m, cs)
    print(json.dumps({"ok": True, "transformation_id": tid}, indent=2))


def cmd_create_compound_metric(m: MSTR, args):
    """Create a compound metric from a formula referencing existing metric IDs.
    --formula: infix tokens, e.g. 'METRIC:<id1> - METRIC:<id2>'  (METRIC:<id> metric_reference tokens,
    OP:<op> operator tokens).  Simple: 'A - B' where A,B are metric IDs."""
    m.login(identity=True)
    tokens = []
    for raw in args.formula.split():
        if raw in {"+","-","*","/","(",")"}:
            tokens.append({"type":"operator","value": raw})
        else:
            tokens.append({"type":"metric_reference","value": raw})
    cs = open_cs(m)
    r = m.post(f"/api/model/dataModels/{args.model_id}/factMetrics?changesetId={cs}",
               json={"information":{"name": args.name},
                     "expression":{"tokens": tokens},
                     "dimty":{}, "format":{"header":[],"values":[]}})
    if not r.ok: die(f"compound metric: {r.status_code} {r.text[:300]}")
    mid = r.json()["information"]["objectId"]
    commit_cs(m, cs)
    print(json.dumps({"ok": True, "metric_id": mid}, indent=2))


def cmd_create_conditional_metric(m: MSTR, args):
    """Create a filtered metric: copy a source metric and apply a filter.
    --source-metric: existing metric id to clone semantics from.
    --filter: existing filter object id to embed."""
    m.login(identity=True)
    r = m.get(f"/api/model/dataModels/{args.model_id}/factMetrics/{args.source_metric}")
    if not r.ok: die(f"source metric GET: {r.status_code} {r.text[:200]}")
    src = r.json()
    body = {
        "information":{"name": args.name},
        "fact": src.get("fact"),
        "function": src.get("function","sum"),
        "functionProperties": src.get("functionProperties",[]),
        "dimty": src.get("dimty",{}),
        "format": src.get("format",{}),
        "conditionality":{"filter":{"objectId": args.filter, "subType":"filter"},
                          "embed": True, "removeAttrQualifications": False},
    }
    cs = open_cs(m)
    r = m.post(f"/api/model/dataModels/{args.model_id}/factMetrics?changesetId={cs}", json=body)
    if not r.ok: die(f"conditional metric: {r.status_code} {r.text[:300]}")
    mid = r.json()["information"]["objectId"]
    commit_cs(m, cs)
    print(json.dumps({"ok": True, "metric_id": mid}, indent=2))


def cmd_attach_transformation(m: MSTR, args):
    """Apply a transformation to an existing metric → creates a new time-shifted metric."""
    m.login(identity=True)
    r = m.get(f"/api/model/dataModels/{args.model_id}/factMetrics/{args.source_metric}")
    if not r.ok: die(f"source metric GET: {r.status_code} {r.text[:200]}")
    src = r.json()
    body = {
        "information":{"name": args.name},
        "fact": src.get("fact"), "function": src.get("function","sum"),
        "functionProperties": src.get("functionProperties",[]),
        "dimty": src.get("dimty",{}), "format": src.get("format",{}),
        "transformation": {"objectId": args.transformation, "subType":"transformation"},
    }
    cs = open_cs(m)
    r = m.post(f"/api/model/dataModels/{args.model_id}/factMetrics?changesetId={cs}", json=body)
    if not r.ok: die(f"transformation metric: {r.status_code} {r.text[:300]}")
    mid = r.json()["information"]["objectId"]
    commit_cs(m, cs)
    print(json.dumps({"ok": True, "metric_id": mid}, indent=2))


_FACT_HINT = _re.compile(r"(?:^|_)(FACT|LINEITEM|DETAIL|REL|F|TRANSACTIONS?|ACTIVITY|EVENTS?)(?:_|$)", _re.I)
_RATE_COL  = _re.compile(r"(?:_RATE|_PCT|_RATIO|DISCOUNT|TAX|_PRICE|_COST|BALANCE)", _re.I)

def _is_fact_like(name: str) -> bool:
    if not name: return False
    u = name.upper()
    return bool(_FACT_HINT.search(u)) or u.endswith("_DETAIL") or u.endswith("_FACT")

def cmd_validate_model(m: MSTR, args):
    """Run the post-build quality checklist against a Mosaic data model.

    Enforces the rules in memory/feedback_mosaic_build_quality.md and
    reference_mosaic_relationship_archetypes.md. Exit code non-zero if any
    FAIL check trips.
    """
    m.login()
    mid = args.model_id
    forced_facts = {t.strip().upper() for t in (args.fact_tables or "").split(",") if t.strip()}

    def load(ep, key=None):
        r = m.get(f"/api/model/dataModels/{mid}{ep}")
        if not r.ok: die(f"{ep}: {r.status_code} {r.text[:200]}")
        b = r.json()
        if key and isinstance(b, dict): return b.get(key, [])
        return b

    root    = load("")
    tables  = load("/tables", "tables")
    attrs   = load("/attributes", "attributes")
    metrics = load("/factMetrics", "factMetrics")

    failures, warnings = [], []
    def FAIL(check, msg, obj=None): failures.append({"check":check,"message":msg,"object":obj})
    def WARN(check, msg, obj=None): warnings.append({"check":check,"message":msg,"object":obj})

    # F3 — required top-level fields
    for f in ("dataServeMode","autoJoin","enableAutoHierarchyRelationships"):
        if root.get(f) is None:
            FAIL("F3", f"model.{f} missing")
    if not (root.get("information",{}) or {}).get("name"):
        FAIL("F3", "model.information.name missing")
    if not (root.get("information",{}) or {}).get("description"):
        WARN("W2", "model has no description — degrades AI/Library discoverability")

    # F2 read-back integrity
    def readback(ep, objs, kind):
        for o in objs:
            oid = (o.get("information") or {}).get("objectId")
            name = (o.get("information") or {}).get("name", oid)
            if not oid: continue
            r = m.get(f"/api/model/dataModels/{mid}/{ep}/{oid}")
            if not r.ok:
                FAIL("F2", f"{kind} {name}: GET /{ep}/{oid} -> {r.status_code} (partial commit)", {"name":name,"id":oid,"kind":kind})
    readback("tables",      tables,  "table")
    readback("attributes",  attrs,   "attribute")
    readback("factMetrics", metrics, "factMetric")

    # Detect fact/bridge tables (name-based + usage-based)
    rel_table_usage = {}
    for a in attrs:
        for r in (a.get("relationships") or []):
            rt = (r.get("relationshipTable") or {}).get("name","")
            if rt: rel_table_usage[rt] = rel_table_usage.get(rt,0) + 1
    fact_like = {t["information"]["name"] for t in tables
                 if _is_fact_like(t["information"]["name"])
                    or t["information"]["name"].upper() in forced_facts
                    or rel_table_usage.get(t["information"]["name"],0) >= 2}

    # F1 empty form names + W6 date-hierarchy heuristic + W1 orphan attrs + W5 dup names
    name_counts = {}
    date_like_bases = set()
    for a in attrs:
        name = (a.get("information") or {}).get("name","")
        name_counts[name] = name_counts.get(name,0) + 1
        forms = a.get("forms") or []
        for i,f in enumerate(forms):
            if not (f.get("name") or "").strip():
                FAIL("F1", f"attribute '{name}' form[{i}] has empty name — disables auto-hierarchy and blanks UI labels",
                     {"attribute": name, "form_index": i})
        lookup = (a.get("attributeLookupTable") or {}).get("name","")
        rels = a.get("relationships") or []
        # Skip W1 for date-style attrs (W6 owns those) and for attrs that themselves end in typical ID patterns (they ARE the grain)
        is_date_like = bool(_re.search(r"\b(date|timestamp|day|month|quarter|year)\b", name, _re.I))
        if lookup in fact_like and not rels and not is_date_like:
            (FAIL if args.strict_orphans else WARN)(
                "W1", f"orphan attribute '{name}' on fact/bridge table {lookup} has zero relationships",
                {"attribute": name, "lookup": lookup})
        # W6 date heuristic: treat any attribute whose name ends in "Date" (not a derived Day/Month/etc) as needing 4 derivatives
        if _re.search(r"\b(date|timestamp)\b", name, _re.I) and not _re.search(r"\b(day|month|quarter|year)\b", name, _re.I):
            date_like_bases.add(name)
    for n,c in name_counts.items():
        if c > 1:
            WARN("W5", f"duplicate attribute name '{n}' appears {c}× — likely conformed-dim mis-merge", {"attribute": n})
    for base in sorted(date_like_bases):
        have = {g: any(_re.search(rf"\b{g}\b", (a.get('information') or {}).get('name',''), _re.I)
                       and base.split()[0].lower() in (a.get('information') or {}).get('name','').lower()
                       for a in attrs) for g in ("Day","Month","Quarter","Year")}
        missing = [g for g,v in have.items() if not v]
        if missing:
            WARN("W6", f"date attribute '{base}' missing derived grains: {missing}", {"attribute": base, "missing": missing})

    # W3 — FK coverage per fact table
    for t in tables:
        tname = t["information"]["name"]
        if tname not in fact_like: continue
        parents = set()
        for a in attrs:
            for r in (a.get("relationships") or []):
                if (r.get("relationshipTable") or {}).get("name") == tname:
                    parents.add((r.get("parent") or {}).get("name"))
        if len(parents) < 2:
            WARN("W3", f"fact/bridge table {tname} has only {len(parents)} distinct parent dim(s) declared — most fact tables have ≥3 FKs",
                 {"table": tname, "parents": sorted(p for p in parents if p)})

    # W2 — blank attribute/metric descriptions
    for a in attrs:
        info = a.get("information") or {}
        if not info.get("description"):
            WARN("W2", f"attribute '{info.get('name')}' has no description", {"attribute": info.get("name")})
    for mm in metrics:
        info = mm.get("information") or {}
        if not info.get("description"):
            WARN("W2", f"metric '{info.get('name')}' has no description", {"metric": info.get("name")})

    # W4 — suspect aggregation on rate/price metrics
    for mm in metrics:
        info = mm.get("information") or {}
        name = info.get("name","")
        fn = mm.get("function","").lower()
        if fn == "sum" and _RATE_COL.search(name):
            WARN("W4", f"metric '{name}' is SUM but name suggests a rate/price/balance — review vs AVG or derived formula",
                 {"metric": name, "function": fn})

    # W7 — topology: isolated attributes on fact tables, fact tables with zero
    # relationships, and numeric-named attributes that almost certainly should
    # have been metrics. (See post_build_validate_topology() for the standalone
    # helper that any wiring script can call.)
    topology = post_build_validate_topology(m, mid)
    for iso in topology.get("isolated_attributes", []):
        if iso.get("table") in fact_like:
            (FAIL if args.strict_isolation else WARN)(
                "W7-iso",
                f"isolated attribute '{iso['name']}' on fact-like table "
                f"{iso['table']} has zero relationships",
                iso,
            )
    for tname in topology.get("tables_without_relationships", []):
        WARN(
            "W7-tbl",
            f"fact-like table '{tname}' has zero relationships touching it — "
            "isolated table or wiring incomplete",
            {"table": tname},
        )
    for warn in topology.get("numeric_attribute_warnings", []):
        WARN(
            "W7-num",
            f"numeric-named attribute '{warn['name']}' on fact-like table "
            f"{warn['table']} has no relationships — likely a misclassified "
            "metric. Delete or convert to factMetric.",
            warn,
        )

    counts = {"tables": len(tables), "attributes": len(attrs), "factMetrics": len(metrics),
              "relationships": sum(len(a.get("relationships") or []) for a in attrs)}
    report = {
        "modelId": mid,
        "modelName": (root.get("information") or {}).get("name"),
        "counts": counts,
        "fact_like_tables": sorted(fact_like),
        "topology": topology,
        "failures": failures,
        "warnings": warnings,
    }

    if args.diff_against:
        r = m.get(f"/api/model/dataModels/{args.diff_against}")
        if not r.ok: die(f"diff target read: {r.status_code}")
        prev_attrs = load_other(m, args.diff_against, "/attributes", "attributes")
        prev_metrics = load_other(m, args.diff_against, "/factMetrics", "factMetrics")
        prev_counts = {
            "attributes": len(prev_attrs),
            "factMetrics": len(prev_metrics),
            "relationships": sum(len(a.get("relationships") or []) for a in prev_attrs),
        }
        prev_names = {(a.get('information') or {}).get('name') for a in prev_attrs}
        cur_names  = {(a.get('information') or {}).get('name') for a in attrs}
        report["diff"] = {
            "prev_counts": prev_counts,
            "cur_counts": counts,
            "attributes_removed": sorted(prev_names - cur_names),
            "attributes_added":   sorted(cur_names  - prev_names),
        }
        for k in ("attributes","factMetrics","relationships"):
            if counts[k] < prev_counts[k]:
                FAIL("F-diff", f"count regression: {k} {prev_counts[k]} -> {counts[k]}")

    # Pretty print
    status = "PASS" if not failures else "FAIL"
    print(f"\n[validate-model:{mid}] {status}")
    print(f"  name: {report['modelName']}")
    print(f"  counts: tables={counts['tables']} attributes={counts['attributes']} factMetrics={counts['factMetrics']} relationships={counts['relationships']}")
    print(f"  fact-like tables: {', '.join(report['fact_like_tables']) or '(none detected)'}")
    if failures:
        print(f"\n  FAIL ({len(failures)}):")
        for f in failures: print(f"    [{f['check']}] {f['message']}")
    if warnings:
        print(f"\n  WARN ({len(warnings)}):")
        by = {}
        for w in warnings: by.setdefault(w["check"], []).append(w["message"])
        for k, msgs in by.items():
            print(f"    [{k}] {len(msgs)} issue(s)")
            for msg in msgs[:5]: print(f"        - {msg}")
            if len(msgs) > 5: print(f"        … +{len(msgs)-5} more")
    if "diff" in report:
        d = report["diff"]
        print(f"\n  DIFF vs {args.diff_against}:")
        print(f"    prev: {d['prev_counts']}")
        print(f"    cur:  {d['cur_counts']}")
        if d["attributes_removed"]: print(f"    removed attrs: {d['attributes_removed'][:10]}{' …' if len(d['attributes_removed'])>10 else ''}")
        if d["attributes_added"]:   print(f"    added attrs:   {d['attributes_added'][:10]}{' …'   if len(d['attributes_added'])>10   else ''}")

    if args.json:
        print("\n" + json.dumps(report, indent=2, default=str))

    sys.exit(1 if failures else 0)


def load_other(m: MSTR, mid: str, ep: str, key: str):
    r = m.get(f"/api/model/dataModels/{mid}{ep}")
    if not r.ok: die(f"diff read {ep}: {r.status_code}")
    return (r.json() or {}).get(key, [])


def cmd_validate_topology(m: MSTR, args):
    """Lightweight topology check designed to be the LAST step of any
    relationship-wiring or build script. Prints a short status line plus an
    optional JSON report, and exits non-zero on any finding when --strict.

    Failure modes detected:
      - Isolated attributes on fact-like tables (no relationships).
      - Fact-like tables with zero relationships touching them.
      - Numeric-named attributes that look like measures but landed as attrs.
      - Expected tables missing from the model (when --expected-tables given).
    """
    m.login()
    expected = None
    if args.expected_tables:
        expected = [t.strip() for t in args.expected_tables.split(",") if t.strip()]
    report = post_build_validate_topology(m, args.model_id, expected_tables=expected)

    if "error" in report:
        die(report["error"])

    counts = report["counts"]
    issues = (len(report["isolated_attributes"])
              + len(report["tables_without_relationships"])
              + len(report["missing_expected_tables"])
              + len(report["numeric_attribute_warnings"]))
    status = "OK" if issues == 0 else f"FOUND {issues} ISSUE(S)"
    print(f"\n[validate-topology:{args.model_id}] {status}")
    print(f"  counts: tables={counts['tables']} attributes={counts['attributes']} "
          f"relationships={counts['relationships']}")
    if report["isolated_attributes"]:
        print(f"  isolated attributes ({len(report['isolated_attributes'])}):")
        for iso in report["isolated_attributes"][:10]:
            print(f"    - {iso['name']} (table={iso.get('table') or '?'})")
        if len(report["isolated_attributes"]) > 10:
            print(f"    … +{len(report['isolated_attributes'])-10} more")
    if report["tables_without_relationships"]:
        print(f"  fact-like tables with no relationships: "
              f"{', '.join(report['tables_without_relationships'])}")
    if report["missing_expected_tables"]:
        print(f"  missing expected tables: "
              f"{', '.join(report['missing_expected_tables'])}")
    if report["numeric_attribute_warnings"]:
        print(f"  likely-misclassified numeric attributes "
              f"({len(report['numeric_attribute_warnings'])}):")
        for warn in report["numeric_attribute_warnings"][:10]:
            print(f"    - {warn['name']} (table={warn.get('table') or '?'})")

    if args.json:
        print("\n" + json.dumps(report, indent=2, default=str))

    if args.strict and issues:
        sys.exit(1)


def cmd_build_from_config(m: MSTR, args):
    """Declarative build from a YAML/JSON spec. See memory/reference_mosaic_config_schema.md."""
    spec = load_structured_file(args.config) or {}
    # Rehydrate into argparse-like namespace and reuse cmd_build.
    class NS: pass
    ns = NS()
    ns.name         = spec["name"]
    ns.source       = [f"{s['instance']}:{s['schema']}:{','.join(s['tables'])}" for s in spec.get("sources",[])]
    ns.instance = ns.schema = None; ns.tables = []
    ns.dest_folder  = spec.get("destination_folder", args.dest_folder)
    ns.data_serve_mode = spec.get("data_serve_mode","connect_live")
    ns.attr_cols    = spec.get("attr_cols", [])
    ns.metric_cols  = spec.get("metric_cols", [])
    ns.skip_relationships = spec.get("skip_relationships", False)
    ns.dictionary   = spec.get("dictionary") or spec.get("data_dictionary")
    # Conformance / FK maps — equivalent to the `build` CLI's --conformance-map
    # and --fk-map flags. Accept both `conformance_map_file` (preferred,
    # explicit about the "file path" semantics) and `conformance_map` (short
    # alias). Same for fk_map. Useful for warehouses with prefixed column
    # naming where auto-conformance via column-name identity won't fire.
    ns.conformance_map = (
        spec.get("conformance_map_file")
        or spec.get("conformance_map")
    )
    ns.fk_map = (
        spec.get("fk_map_file")
        or spec.get("fk_map")
    )
    erd = []
    for key in ("erd", "erds"):
        value = spec.get(key)
        if isinstance(value, list):
            erd.extend(value)
        elif value:
            erd.append(value)
    ns.erd          = erd
    ns.security_filter = [f"{sf['name']}={sf.get('qualification','True')}|{','.join(sf.get('members',[]))}"
                          for sf in spec.get("security_filters",[])]
    ns.grant        = [f"{g['trustee']}:{','.join(g['rights'])}" for g in spec.get("grants",[])]
    ns.deny         = [f"{g['trustee']}:{','.join(g['rights'])}" for g in spec.get("denies",[])]
    ns.translate    = [f"{t['object']}:{t['locale']}={t['text']}" for t in spec.get("translations",[])]
    ns.certify      = spec.get("certify", False)
    ns.publish      = spec.get("publish", False)
    cmd_build(m, ns)


# ── CLI ───────────────────────────────────────────────────────────────────────
def build_parser():
    p = argparse.ArgumentParser(prog="build_mosaic.py")
    p.add_argument("--base",        default=DEFAULT_BASE)
    p.add_argument("--project-id",  default=DEFAULT_PROJECT_ID)
    p.add_argument("--user",        default=DEFAULT_USER)
    p.add_argument("--password",    default=DEFAULT_PASSWORD)
    p.add_argument("--login-mode",  type=int, default=DEFAULT_LOGIN_MODE)
    # Borrowed-session auth (Studio Cloud / SSO tenants). When --auth-token is
    # provided, MSTR.login() skips /auth/login and /auth/logout so the external
    # owner's session is left intact. See README.md → "Borrowed-session auth".
    p.add_argument("--auth-token",     default=DEFAULT_AUTH_TOKEN,
                   help="Pre-existing X-MSTR-AuthToken (e.g. from a browser session). "
                        "Skips /auth/login and /auth/logout. Env: MSTR_AUTH_TOKEN.")
    p.add_argument("--identity-token", default=DEFAULT_IDENTITY_TOKEN,
                   help="Pre-existing X-MSTR-IdentityToken (required for Mosaic Modeling "
                        "Service changesets). If unset, the script attempts to mint one "
                        "via /api/auth/identityToken using --auth-token + cookies. "
                        "Env: MSTR_IDENTITY_TOKEN.")
    p.add_argument("--session-cookie", default=DEFAULT_SESSION_COOKIE,
                   help="JSESSIONID value from the browser session. Required alongside "
                        "--auth-token for project-scoped APIs on Studio Cloud. "
                        "Env: MSTR_SESSION_COOKIE.")
    p.add_argument("--ingress-cookie", default=DEFAULT_INGRESS_COOKIE,
                   help="library-ingress value from the browser session (Studio Cloud "
                        "routing cookie). Env: MSTR_INGRESS_COOKIE.")
    p.add_argument("-v","--verbose", action="store_true")

    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("auth-probe")

    sp = sub.add_parser("list-datasources")
    sp.add_argument("--name", help="filter by substring match on name")

    sp = sub.add_parser("list-namespaces")
    sp.add_argument("--instance"); sp.add_argument("--instance-id")

    sp = sub.add_parser("list-tables")
    sp.add_argument("--instance"); sp.add_argument("--instance-id")
    sp.add_argument("--namespace", required=True)
    sp.add_argument("--match", help="substring match on table name")

    sp = sub.add_parser("describe-tables",
                        help="Describe many tables in one login to avoid the project session cap")
    sp.add_argument("--source", action="append", required=True,
                    help="Repeatable: instanceId:namespace:table")

    sp = sub.add_parser("kill-sessions",
                        help="Reap stale AUTH TOKENS via login/logout loop. "
                             "Does NOT reap iServer project-interactive sessions — those "
                             "are the ones that trip the 8004cb0a cap and they can only "
                             "time out (~30 min). Run this only to clean up orphaned auth "
                             "tokens; it cannot rescue a capped-state. See "
                             "memory/feedback_build_mosaic_session_leak.md.")
    sp.add_argument("--count", type=int, default=5)

    sp = sub.add_parser("describe-table")
    sp.add_argument("--instance"); sp.add_argument("--instance-id")
    sp.add_argument("--namespace", required=True)
    sp.add_argument("--table",     required=True)

    sp = sub.add_parser("discover")
    sp.add_argument("--instance-id"); sp.add_argument("--namespace"); sp.add_argument("--table")

    sp = sub.add_parser("openapi-summary")
    sp.add_argument("--out", help="optional path to save the raw OpenAPI YAML")
    sp.add_argument("--path-filter", action="append", default=[],
                    help="path prefix to include in selected_paths; repeatable")
    sp.add_argument("--limit", type=int, default=120)

    sp = sub.add_parser("openapi-search")
    sp.add_argument("pattern", help="regex/text pattern to search in the OpenAPI YAML")
    sp.add_argument("--file", help="local OpenAPI YAML path; defaults to ./openapi.yaml, then live tenant")
    sp.add_argument("--limit", type=int, default=40)
    sp.add_argument("--context", type=int, default=0)
    sp.add_argument("--case-sensitive", action="store_true")

    sp = sub.add_parser("api-call")
    sp.add_argument("--method", default="GET", choices=["GET","POST","PUT","PATCH","DELETE"])
    sp.add_argument("--path", required=True, help="REST path, e.g. /api/projects")
    sp.add_argument("--param", action="append", default=[], help="query param key=value; repeatable")
    sp.add_argument("--header", action="append", default=[], help="extra header key=value; repeatable")
    sp.add_argument("--json", help="JSON request body string")
    sp.add_argument("--json-file", help="JSON request body file")
    sp.add_argument("--out", help="save response body to file")
    sp.add_argument("--text-limit", type=int, default=8000)
    sp.add_argument("--no-auth", action="store_true", help="do not login first; useful for public OpenAPI paths")
    sp.add_argument("--identity-token", action="store_true",
                    help="also request X-MSTR-IdentityToken; use for Mosaic data-model Modeling Service writes, not classic/project Modeling calls")
    sp.add_argument("--yes", action="store_true", help="required for DELETE")

    sp = sub.add_parser("resolve-users")
    sp.add_argument("--user", action="append", default=[], help="user id, username, full name, or email; repeatable")
    sp.add_argument("--file", action="append", default=[],
                    help="CSV/JSON/YAML with id, username, email, name/fullName rows; repeatable")
    sp.add_argument("--limit", type=int, default=10)
    sp.add_argument("--first", action="store_true", help="return first candidate instead of reporting ambiguity")

    sp = sub.add_parser("create-users")
    sp.add_argument("--file", action="append", required=True,
                    help="CSV/JSON/YAML rows. Required fields: username and fullName/name; email is optional.")
    sp.add_argument("--source-user-id", help="optional source user to duplicate from")
    sp.add_argument("--default-password-env", default="MSTR_NEW_USER_PASSWORD",
                    help="env var used as default password when a row omits password")
    sp.add_argument("--email-address-name", default="Default email")
    sp.add_argument("--skip-email-address", action="store_true")
    sp.add_argument("--allow-existing", action="store_true", help="create even if an exact username/email match is found")
    sp.add_argument("--check-existing", action="store_true", help="during dry-run, login and check for exact existing users")
    sp.add_argument("--yes", action="store_true", help="actually create users; without this, print a dry-run plan")

    sp = sub.add_parser("search-objects")
    sp.add_argument("--name", required=True)
    sp.add_argument("--type", action="append", default=[],
                    help="numeric EnumDSSObjectType; repeatable")
    sp.add_argument("--subtype", help="numeric subtype filter applied client-side")
    sp.add_argument("--pattern", type=int, default=4,
                    help="Strategy search pattern enum; default 4")
    sp.add_argument("--project-id-filter", action="append", default=[],
                    help="search project ID query param; repeatable")
    sp.add_argument("--ancestors", action="store_true")
    sp.add_argument("--offset", type=int, default=0)
    sp.add_argument("--limit", type=int, default=25)
    sp.add_argument("--raw", action="store_true")

    object_kinds = sorted(MODEL_OBJECT_KINDS)
    sp = sub.add_parser("get-model-object")
    sp.add_argument("--kind", required=True, choices=object_kinds,
                    help="Mosaic-contained kind, or project_/legacy_ kind for classic schema objects")
    sp.add_argument("--model-id", help="required for Mosaic-contained objects")
    sp.add_argument("--object-id", help="required except kind=data_model")
    sp.add_argument("--show-expression-as", action="append", choices=["tokens", "tree"])
    sp.add_argument("--show-advanced-properties", action="store_true")
    sp.add_argument("--fields")
    sp.add_argument("--out", help="save response body to JSON/text file")
    sp.add_argument("--text-limit", type=int, default=8000)

    sp = sub.add_parser("patch-model-object")
    sp.add_argument("--kind", required=True, choices=object_kinds,
                    help="Mosaic-contained kind, or project_/legacy_ kind for classic schema objects")
    sp.add_argument("--model-id", help="required for Mosaic-contained objects")
    sp.add_argument("--object-id", help="required except kind=data_model")
    sp.add_argument("--method", default="PATCH", choices=["PATCH", "PUT"])
    sp.add_argument("--json", help="JSON request body string")
    sp.add_argument("--json-file", help="JSON request body file")
    sp.add_argument("--show-expression-as", action="append", choices=["tokens", "tree"])
    sp.add_argument("--show-advanced-properties", action="store_true")
    sp.add_argument("--fields")
    sp.add_argument("--before-out", help="save current definition before patching")
    sp.add_argument("--include-before", action="store_true", help="include current definition in command output")
    sp.add_argument("--text-limit", type=int, default=8000)
    sp.add_argument("--yes", action="store_true", help="required after reviewing target and patch body")

    sp = sub.add_parser("build")
    sp.add_argument("--name", required=True, help="new model name")
    sp.add_argument("--source", action="append", default=[],
                    help="INSTANCE:SCHEMA:T1,T2,... (repeatable, for multi-source models)")
    sp.add_argument("--instance"); sp.add_argument("--schema"); sp.add_argument("--tables", nargs="*")
    sp.add_argument("--dest-folder", default=DEFAULT_DEST_FOLDER)
    sp.add_argument("--data-serve-mode", default="connect_live", choices=["connect_live","in_memory","hybrid"])
    sp.add_argument("--attr-cols",   nargs="*", default=[], help="column names to force as attributes")
    sp.add_argument("--metric-cols", nargs="*", default=[], help="column names to force as metrics")
    sp.add_argument("--skip-relationships", action="store_true")
    sp.add_argument("--dictionary", help="JSON/YAML/CSV file of attribute+metric name/description overrides and relationships")
    sp.add_argument("--erd", action="append", default=[],
                    help="ERD file (JSON/YAML list of relationships, DBML, Mermaid, or SQL DDL). Repeatable.")
    sp.add_argument("--conformance-map",
                    help="JSON/YAML {logical_name: [TABLE.COLUMN, ...]} — forces those columns to collapse "
                         "into one conformed attribute. Overrides column-name inference. See "
                         "feedback_mosaic_relationship_wiring.md.")
    sp.add_argument("--fk-map",
                    help="JSON/YAML {child_table.child_col: parent_table.parent_col} — normalizes "
                         "semantically-same-but-differently-named FKs so they conform to the parent's "
                         "logical name. Useful for multi-DB builds with e.g. primary_<entity>_id vs <entity>_id.")
    sp.add_argument("--security-filter", action="append", default=[],
                    help="Mosaic data-model SF: 'NAME=ATTR_ID[:FORM_ID]=VALUE|USER,USER' or 'NAME=@qualification.json|USER,USER' (repeatable)")
    sp.add_argument("--grant", action="append", default=[],
                    help="ACL grant 'trusteeId:right1,right2' (repeatable)")
    sp.add_argument("--deny", action="append", default=[],
                    help="ACL deny 'trusteeId:right1,right2' (repeatable)")
    sp.add_argument("--translate", action="append", default=[],
                    help="'objectId[:subType]:locale[:name|description]=translation' (repeatable)")
    sp.add_argument("--certify", action="store_true")
    sp.add_argument("--publish", action="store_true", help="publish cube for in_memory mode")

    sp = sub.add_parser("validate-model",
        help="Run post-build quality checks on a Mosaic data model (see memory/reference_mosaic_build_validation.md).")
    sp.add_argument("--model-id", required=True)
    sp.add_argument("--fact-tables", help="comma-separated table names to force-classify as fact/bridge")
    sp.add_argument("--strict-orphans", action="store_true", help="promote W1 orphan-attributes from WARN to FAIL")
    sp.add_argument("--strict-isolation", action="store_true",
                    help="promote W7-iso (isolated attributes on fact tables) from WARN to FAIL — "
                         "use as the standard tail of every wiring script")
    sp.add_argument("--diff-against", help="another modelId; emit a count diff and fail on regressions")
    sp.add_argument("--json", action="store_true", help="also print the full JSON report")

    sp = sub.add_parser("validate-topology",
        help="Lightweight post-build topology check: isolated attributes, fact "
             "tables with no relationships, numeric-named attrs that should "
             "have been metrics. Exit 1 on any finding when --strict is set.")
    sp.add_argument("--model-id", required=True)
    sp.add_argument("--expected-tables",
                    help="comma-separated table names that MUST appear in the model")
    sp.add_argument("--strict", action="store_true",
                    help="exit non-zero on any finding (recommended as the "
                         "tail of every wiring/build script)")
    sp.add_argument("--json", action="store_true", help="print the full JSON report")

    sp = sub.add_parser("build-from-config")
    sp.add_argument("--config", required=True, help="path to YAML/JSON spec file")
    sp.add_argument("--dest-folder", default=DEFAULT_DEST_FOLDER)

    sp = sub.add_parser(
        "build-from-schema-objects",
        help="Build a Mosaic data model from existing classic schema object IDs."
    )
    sp.add_argument("--name", required=True,
                    help="Name for the new Mosaic data model.")
    sp.add_argument("--attribute-ids", default="",
                    help="Comma-separated classic attribute object IDs, "
                         "or @filepath for one-per-line.")
    sp.add_argument("--fact-ids", default="",
                    help="Comma-separated classic fact object IDs, or @filepath.")
    sp.add_argument("--metric-ids", default="",
                    help="Comma-separated classic metric object IDs, or @filepath.")
    sp.add_argument("--instance-id", default="",
                    help="Fallback datasource ID if classic table metadata "
                         "lacks databaseInstance.")
    sp.add_argument("--schema", default="",
                    help="Fallback warehouse schema if classic table metadata "
                         "lacks namespace.")
    sp.add_argument("--data-serve-mode",
                    choices=["connect_live", "in_memory", "hybrid"],
                    default="connect_live")
    sp.add_argument("--publish", action="store_true",
                    help="Publish to in-memory after build (forces "
                         "data-serve-mode=in_memory).")
    sp.add_argument("--dest-folder", default=DEFAULT_DEST_FOLDER,
                    help="Destination folder ID for the new model.")
    sp.add_argument("--review-file", default="",
                    help="Write a JSON review file with warnings and "
                         "created object IDs.")

    sp = sub.add_parser("set-serve-mode")
    sp.add_argument("--model-id", required=True)
    sp.add_argument("--mode", required=True, choices=["connect_live","in_memory","hybrid"])

    sp = sub.add_parser("publish"); sp.add_argument("--model-id", required=True)
    sp.add_argument("--poll-seconds", type=int, default=180,
                    help="max wait for every table to reach 'loaded' before failing")
    sp.add_argument("--skip-classify", action="store_true",
                    help="skip GET /api/objects/{id}?type=3 surface classification; "
                         "assume Mosaic data model. Saves one project-scoped call to "
                         "stay under the session cap when chaining build→publish.")

    sp = sub.add_parser("wire-relationships",
        help="Post-build relationship wiring with step-3/step-5 validation; avoids 8004ccdb/8004ccc7 retry loops. See memory/feedback_mosaic_relationship_wiring.md.")
    sp.add_argument("--model-id", required=True)
    sp.add_argument("--hints", required=True,
                    help="JSON/YAML file: {relationships:[{parent_attribute, child_attribute, relationship_table, type}]}")
    sp.add_argument("--dry-run", action="store_true",
                    help="validate + print plan without issuing PUTs")
    sp.add_argument("--replace", action="store_true",
                    help="OVERWRITE existing relationships on each child attribute "
                         "(destructive — wipes incoming rels too). Default is "
                         "merge-aware: fetch existing, dedupe, PUT the union.")

    sp = sub.add_parser("merge-attributes",
        help="Conform differently-named FK columns by merging child expressions "
             "into the parent attribute. The Kimball pattern for warehouses where "
             "prefixed surrogate keys (i_item_sk vs ss_item_sk) defeat auto-conformance.")
    sp.add_argument("--model-id", required=True)
    sp.add_argument("--hints",    required=True,
                    help="JSON/YAML map of {child_table.child_col: parent_table.parent_col} "
                         "(same shape as `build --fk-map`); or {'merges':[{child,parent}]} envelope.")
    sp.add_argument("--dry-run",  action="store_true",
                    help="validate + print plan without writing")
    sp.add_argument("--keep-children", action="store_true",
                    help="leave the now-redundant child attributes in place "
                         "instead of deleting them (useful for staged rollouts)")
    sp.add_argument("--release-locks", action="store_true",
                    help="if open_cs hits 8004cc41 with a self-owned lock, release "
                         "it and retry once. See `release-locks` subcommand for the "
                         "standalone equivalent.")

    sp = sub.add_parser("release-locks",
        help="Release stuck Modeling Service schemaEdit changesets owned by the "
             "current user. Use after a crashed build/merge/wire run leaves "
             "8004cc41 on every subsequent open.")
    sp.add_argument("--max-iters", type=int, default=5,
                    help="cap on release attempts (each provokes one lock conflict "
                         "to discover the LOCKID). Default 5.")

    sp = sub.add_parser("refresh")
    sp.add_argument("--model-id", required=True)
    sp.add_argument("--refresh-type", default="incremental",
                    choices=["update","add","replace","incremental"])

    sp = sub.add_parser("delete-model")
    sp.add_argument("--model-id", required=True)
    sp.add_argument("--yes", action="store_true", help="required after verifying the Mosaic data model id")

    sp = sub.add_parser("set-acl")
    sp.add_argument("--model-id", help="required for data-model-contained objects")
    sp.add_argument("--object-id", required=True)
    sp.add_argument("--sub-type", default="data_model",
                    help="object subtype for data model ACL endpoint, e.g. data_model, fact_metric, attribute")
    sp.add_argument("--grant", action="append", default=[], help="'trusteeId:rights' (repeatable)")
    sp.add_argument("--deny", action="append", default=[], help="'trusteeId:rights' (repeatable)")

    sp = sub.add_parser("add-security-filter")
    sp.add_argument("--model-id", required=True)
    sp.add_argument("--spec", required=True,
                    help="Mosaic data-model SF: 'NAME=ATTR_ID[:FORM_ID]=VALUE|USER,USER' or 'NAME=@qualification.json|USER,USER'")

    sp = sub.add_parser("translate")
    sp.add_argument("--model-id", required=True)
    sp.add_argument("--sub-type", default="data_model")
    sp.add_argument("--entry", action="append", required=True,
                    help="'objectId[:subType]:locale[:name|description]=translation' (repeatable)")

    sp = sub.add_parser("certify"); sp.add_argument("--object-id", required=True)

    sp = sub.add_parser("create-transformation")
    sp.add_argument("--model-id", required=True)
    sp.add_argument("--name", required=True)
    sp.add_argument("--member", action="append", required=True,
                    help="'attributeId=offset' e.g. 'ABC...=-1' for prior period (repeatable)")

    sp = sub.add_parser("create-compound-metric")
    sp.add_argument("--model-id", required=True)
    sp.add_argument("--name", required=True)
    sp.add_argument("--formula", required=True, help="space-separated: 'METRIC_ID1 - METRIC_ID2'")

    sp = sub.add_parser("create-conditional-metric")
    sp.add_argument("--model-id", required=True)
    sp.add_argument("--name", required=True)
    sp.add_argument("--source-metric", required=True, help="existing metric ID to clone semantics from")
    sp.add_argument("--filter", required=True, help="filter object ID to embed")

    sp = sub.add_parser("attach-transformation")
    sp.add_argument("--model-id", required=True)
    sp.add_argument("--name", required=True)
    sp.add_argument("--source-metric", required=True)
    sp.add_argument("--transformation", required=True)

    return p


def main():
    args = build_parser().parse_args()
    m = MSTR(args)
    t0 = time.monotonic()
    try:
        {
            "auth-probe":      cmd_auth_probe,
            "list-datasources":cmd_list_datasources,
            "list-namespaces": cmd_list_namespaces,
            "list-tables":     cmd_list_tables,
            "describe-table":  cmd_describe_table,
            "describe-tables": cmd_describe_tables,
            "kill-sessions":   cmd_kill_sessions,
            "release-locks":   cmd_release_locks,
            "discover":        cmd_discover,
            "openapi-summary": cmd_openapi_summary,
            "openapi-search":  cmd_openapi_search,
            "api-call":        cmd_api_call,
            "resolve-users":   cmd_resolve_users,
            "create-users":    cmd_create_users,
            "search-objects":  cmd_search_objects,
            "get-model-object":cmd_get_model_object,
            "patch-model-object":cmd_patch_model_object,
            "build":           cmd_build,
            "build-from-config":cmd_build_from_config,
            "build-from-schema-objects": cmd_build_from_schema_objects,
            "validate-model":  cmd_validate_model,
            "validate-topology": cmd_validate_topology,
            "set-serve-mode":  cmd_set_serve_mode,
            "publish":         cmd_publish,
            "wire-relationships": cmd_wire_relationships,
            "merge-attributes":   cmd_merge_attributes,
            "refresh":         cmd_refresh,
            "delete-model":    cmd_delete_model,
            "set-acl":         cmd_set_acl,
            "add-security-filter": cmd_add_security_filter,
            "translate":       cmd_translate,
            "certify":         cmd_certify,
            "create-transformation": cmd_create_transformation,
            "create-compound-metric": cmd_create_compound_metric,
            "create-conditional-metric": cmd_create_conditional_metric,
            "attach-transformation": cmd_attach_transformation,
        }[args.cmd](m, args)
    except requests.HTTPError as e:
        die(f"{e.response.status_code} {e.response.text[:500]}")
    finally:
        m.logout()
        if args.verbose:
            print(f"[wall] {int((time.monotonic()-t0)*1000)}ms", file=sys.stderr)


if __name__ == "__main__":
    main()
