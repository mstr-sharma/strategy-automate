"""Call any Strategy REST operation, checked against the tenant's own OpenAPI spec.

  python3 strategy_api.py sync                          # cache the tenant's spec (public + internal)
  python3 strategy_api.py tags                          # every API area: operations and owning skill
  python3 strategy_api.py ops --tag Subscriptions       # operations in an area (or --search WORDS)
  python3 strategy_api.py describe getSubscriptions     # parameters, headers, body skeleton, responses
  python3 strategy_api.py call getSubscriptions -p limit=10
  python3 strategy_api.py call "DELETE /api/subscriptions/{id}" -p id=<id> --yes
  python3 strategy_api.py coverage --write ../../../memory/reference_strategy_api_surface.md

An operation is an operationId or "VERB /api/path". Before anything is sent, `call` checks the
request against the spec — unknown or missing parameters, enum values, a missing or malformed
body, missing required body fields — and fills in what the operation needs: X-MSTR-ProjectID
(--project, or MSTR_PROJECT_ID / MSTR_PROJECT_NAME), a Modeling changeset (opened, then committed
on success or discarded on failure; read operations always discard), and Prefer: respond-async.
GET and HEAD run directly; anything else needs --yes, and without it the request is printed, not
sent. Internal (not public) and deprecated operations are flagged. Sign-in goes through
strategy_auth.py (any --auth-method); tokens never appear in the output.

The spec is read from {MSTR_BASE}/api/openapi.json?visibility=all and cached under
~/.cache/strategy-automate/ (MSTR_API_SPEC=<file> uses a local copy instead).
See skills/strategy-platform/SKILL.md and memory/reference_strategy_api_surface.md.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import time
import urllib.parse
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import strategy_auth as sa  # noqa: E402

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None  # type: ignore[assignment]

VERBS = ("get", "post", "put", "patch", "delete", "head")
READ_VERBS = ("GET", "HEAD")
AUTO_HEADERS = {"x-mstr-authtoken", "x-mstr-projectid", "x-mstr-ms-changeset", "prefer"}
CACHE_TTL = 7 * 24 * 3600

# Which skill owns which API area (the spec's first tag). Prefix matches end with "*".
SKILL_TAGS: dict[str, tuple[str, ...]] = {
    "strategy-platform": ("Authentication", "Misc", "(untagged)", "Documentation", "Documentation Definition",
                          "Debug"),
    "strategy-admin": ("System Administration", "User Management", "Security Roles", "Privilege Management",
                       "SCIM", "IAM", "Multi Tenant", "License", "Vault Connection Management", "Preferences",
                       "Languages", "Timezones", "Applications", "Client Configurations", "Configuration",
                       "Configurations", "Projects", "Emails", "Microsoft Teams App", "Desktops", "URL Scan",
                       "Scope Filters", "Notifications"),
    "strategy-distribution": ("Subscriptions", "Schedules", "Events", "Transmitters", "Devices", "Contacts",
                              "Contact Groups", "History List"),
    "strategy-content": ("Reports", "Dashboard*", "Library", "Browsing", "Object Management", "Content Groups",
                         "Content Bundles", "Themes", "Palettes", "Maps", "Cards", "Hyper", "Elements",
                         "Transaction Reports", "Cubes", "Datasets", "Datamarts", "MDX Cube Catalog", "Runtimes",
                         "Shared File Store"),
    "strategy-migration": ("Migrations", "Migration Groups", "Packages", "Project Duplications", "Git Service"),
    "strategy-ops": ("Monitors", "Telemetry", "Change Journal", "Performance Statistics", "HangDetector", "Scripts",
                     "Tasks", "Flows", "Workflows", "Insight Engine*"),
    "strategy-ai": ("Agent", "Auto Bots", "AutoExpert", "AI Storage", "Explorer", "Ontology", "QuestionSet",
                    "Recommendations"),
    "build-mosaic-model": ("Data Models", "Mosaic", "Changesets", "Workspaces", "Open Semantic Layer", "Model Server",
                           "Data Server", "Attributes", "Facts", "Metrics", "Filters", "Transformations",
                           "Hierarchies", "System Hierarchy", "User Hierarchies", "Tables", "Schema",
                           "Security Filters", "Custom Groups", "Consolidations", "Derived Elements", "Base Formulas",
                           "Subtotals", "Calendars", "Drill Maps", "Prompts", "Datasource Management", "Drivers",
                           "Gateways"),
    "strategy-validation": ("Baseline Test*", "Comparison Test*", "Test Center*", "Storage Sync File*",
                            "internal-baseline*"),
}


class ApiError(RuntimeError):
    """A request the spec rejects, or a call that failed; the message is safe to print."""


def skill_for_tag(tag: str) -> str:
    for skill, tags in SKILL_TAGS.items():
        for t in tags:
            if (t.endswith("*") and tag.startswith(t[:-1])) or tag == t:
                return skill
    return "unassigned"


# ── Spec loading and indexing ────────────────────────────────────────────────

def _cache_path(base: str) -> str:
    root = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
    host = urllib.parse.urlsplit(base).hostname or "tenant"
    return os.path.join(root, "strategy-automate", f"openapi-{host}.json")


def sync_spec(base: str, http: Any = None) -> str:
    """Download the tenant's full spec (public + internal operations) into the cache. Most
    tenants serve it without sign-in; when one answers 401/403, sign in and retry once."""
    http = http or requests.Session()
    r = http.get(f"{base}/api/openapi.json", params={"visibility": "all"}, timeout=120)
    if r.status_code in (401, 403):
        signin = sa.sign_in(http, sa.AuthConfig.from_env(base=base))
        try:
            r = http.get(f"{base}/api/openapi.json", params={"visibility": "all"}, timeout=120)
        finally:
            sa.sign_out(http, base, signin)
    if not r.ok:
        raise ApiError(f"could not fetch {base}/api/openapi.json: HTTP {r.status_code}")
    spec = r.json()
    if "paths" not in spec:
        raise ApiError("the tenant answered, but not with an OpenAPI document")
    path = _cache_path(base)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(spec, f)
    os.replace(tmp, path)
    return path


def load_spec(base: str = "", allow_fetch: bool = True) -> dict:
    local = os.environ.get("MSTR_API_SPEC")
    if local:
        with open(local, encoding="utf-8") as f:
            return json.load(f)
    if not base:
        raise ApiError("set MSTR_BASE (or MSTR_API_SPEC=<spec.json>)")
    path = _cache_path(base)
    fresh = os.path.isfile(path) and time.time() - os.path.getmtime(path) < CACHE_TTL
    if not fresh and allow_fetch:
        sync_spec(base)
    if not os.path.isfile(path):
        raise ApiError("no cached spec; run `strategy_api.py sync`")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _resolve(spec: dict, node: Any) -> Any:
    """Follow a $ref chain at this level only (schemas are resolved lazily as they are walked;
    some spec schemas are large and recursive)."""
    seen = 0
    while isinstance(node, dict) and "$ref" in node and seen < 20:
        target: Any = spec
        for part in node["$ref"].lstrip("#/").split("/"):
            target = target.get(part, {}) if isinstance(target, dict) else {}
        node, seen = target, seen + 1
    return node


def _merged_object(spec: dict, schema: dict) -> dict:
    """allOf parts merged into one object schema (properties + required)."""
    schema = _resolve(spec, schema)
    if not isinstance(schema, dict) or "allOf" not in schema:
        return schema if isinstance(schema, dict) else {}
    merged: dict = {"type": "object", "properties": dict(schema.get("properties") or {}),
                    "required": list(schema.get("required") or [])}
    for part in schema["allOf"]:
        part = _merged_object(spec, part)
        merged["properties"].update(part.get("properties") or {})
        merged["required"] += part.get("required") or []
    return merged


class Operation:
    def __init__(self, spec: dict, verb: str, path: str, op: dict):
        self.spec, self.verb, self.path, self.raw = spec, verb.upper(), path, op
        self.id = op.get("operationId") or f"{verb.upper()} {path}"
        self.tag = (op.get("tags") or ["(untagged)"])[0]
        self.summary = (op.get("summary") or "").strip()
        visibility = (op.get("x-microstrategy") or {}).get("visibility")
        self.internal = visibility == "internal"
        self.deprecated = (bool(op.get("deprecated")) or visibility == "deprecated"
                           or "deprecat" in (op.get("description") or "").lower()[:300])

    @property
    def response_types(self) -> list[str]:
        """Content types of the 2xx responses (e.g. application/pdf for an export)."""
        types: list[str] = []
        for code, resp in (self.raw.get("responses") or {}).items():
            if str(code).startswith("2"):
                for ctype in (_resolve(self.spec, resp).get("content") or {}):
                    if ctype not in types:
                        types.append(ctype)
        return types

    @property
    def params(self) -> list[dict]:
        out = []
        for p in self.raw.get("parameters", []):
            p = _resolve(self.spec, p)
            schema = _resolve(self.spec, p.get("schema") or {})
            items = _resolve(self.spec, schema.get("items") or {})
            out.append({"name": p.get("name"), "in": p.get("in"), "required": bool(p.get("required")),
                        "type": schema.get("type") or ("array" if "items" in schema else ""),
                        "enum": schema.get("enum") or items.get("enum"),
                        "description": (p.get("description") or "").strip()})
        return out

    @property
    def body(self) -> dict | None:
        rb = self.raw.get("requestBody")
        if not rb:
            return None
        rb = _resolve(self.spec, rb)
        content = rb.get("content") or {}
        ctype = next(iter(content), "application/json")
        return {"required": bool(rb.get("required")), "content_type": ctype,
                "schema": _merged_object(self.spec, (content.get(ctype) or {}).get("schema") or {})}

    def key(self) -> str:
        return f"{self.verb} {self.path}"


def operations(spec: dict) -> list[Operation]:
    return [Operation(spec, verb, path, op) for path, item in spec.get("paths", {}).items()
            for verb, op in item.items() if verb in VERBS]


def find_operation(spec: dict, ref: str) -> Operation:
    ops = operations(spec)
    ref = ref.strip()
    m = re.match(r"^(GET|POST|PUT|PATCH|DELETE|HEAD)\s+(\S+)$", ref, re.I)
    if m:
        verb, path = m.group(1).upper(), m.group(2)
        hits = [o for o in ops if o.verb == verb and o.path == path]
        if not hits:   # allow a concrete path: match templates
            hits = [o for o in ops if o.verb == verb and _template_matches(o.path, path)]
    else:
        hits = [o for o in ops if o.id == ref] or [o for o in ops if o.id.lower() == ref.lower()]
    if len(hits) == 1:
        return hits[0]
    if not hits:
        near = [o.id for o in ops if ref.lower() in o.id.lower()][:8]
        raise ApiError(f"no operation '{ref}'" + (f"; similar: {', '.join(near)}" if near else ""))
    raise ApiError(f"'{ref}' is ambiguous ({', '.join(o.key() for o in hits[:6])}); use \"VERB /path\"")


def _template_matches(template: str, path: str) -> bool:
    pat = "^" + re.sub(r"\\\{[^}]+\\\}", "[^/]+", re.escape(template)) + "$"
    return re.match(pat, path) is not None


# ── Request building and validation ──────────────────────────────────────────

def body_skeleton(spec: dict, schema: Any, depth: int = 0) -> Any:
    """An example value for a schema: required fields first, optional ones marked `?`."""
    if depth > 4:
        return "…"
    schema = _merged_object(spec, schema)
    for key in ("oneOf", "anyOf"):
        if schema.get(key):
            return body_skeleton(spec, schema[key][0], depth)
    if "enum" in schema:
        return "|".join(str(v) for v in schema["enum"][:40])
    kind = schema.get("type") or ("object" if "properties" in schema else "")
    if kind == "object":
        props = schema.get("properties") or {}
        required = schema.get("required") or []
        ordered = [k for k in props if k in required] + [k for k in props if k not in required]
        return {(k if k in required else f"{k}?"): body_skeleton(spec, props[k], depth + 1) for k in ordered[:25]}
    if kind == "array":
        return [body_skeleton(spec, schema.get("items") or {}, depth + 1)]
    return f"<{kind or 'value'}>"


def _multipart(op: Operation, file_specs: list[str], form_specs: list[str], body: Any) -> tuple[dict, dict]:
    """Open --file FIELD=PATH parts and collect --form NAME=VALUE fields for a multipart operation."""
    if not file_specs and not form_specs:
        return {}, {}
    spec_body = op.body
    if spec_body is None or "multipart" not in spec_body["content_type"]:
        raise ApiError(f"{op.key()} does not take a multipart body; use --body")
    if body is not None:
        raise ApiError("--body cannot be combined with --file/--form")
    files, form = {}, {}
    for item in file_specs:
        field, sep, path = item.partition("=")
        if not sep or not os.path.isfile(path):
            raise ApiError(f"--file {item!r}: expected FIELD=PATH to an existing file")
        files[field] = (os.path.basename(path), open(path, "rb"))
    for item in form_specs:
        name, sep, value = item.partition("=")
        if not sep:
            raise ApiError(f"--form {item!r}: expected NAME=VALUE")
        form[name] = value
    return files, form


def build_request(op: Operation, pairs: list[str], body: Any, project: str | None,
                  multipart: bool = False) -> dict:
    """Validate parameters/body against the spec and return {path, query, headers, json}."""
    by_name = {p["name"]: p for p in op.params if p.get("name")}
    lower = {k.lower(): k for k in by_name}
    path_vals: dict[str, str] = {}
    query: dict[str, Any] = {}
    headers: dict[str, str] = {}
    problems: list[str] = []
    for pair in pairs:
        name, sep, value = pair.partition("=")
        if not sep:
            problems.append(f"'{pair}' is not name=value")
            continue
        real = by_name.get(name) and name or lower.get(name.lower())
        if not real:
            settable = sorted(n for n, p in by_name.items() if n.lower() not in AUTO_HEADERS or n == "Prefer")
            problems.append(f"unknown parameter '{name}' (this operation takes: {', '.join(settable) or 'none'})")
            continue
        spec_p = by_name[real]
        if spec_p["enum"] and value not in [str(e) for e in spec_p["enum"]]:
            problems.append(f"{real}={value!r} is not one of {spec_p['enum']}")
            continue
        if spec_p["in"] == "path":
            path_vals[real] = value
        elif spec_p["in"] == "query":
            if real in query:   # repeat a query parameter for arrays: -p type=3 -p type=4
                query[real] = (query[real] if isinstance(query[real], list) else [query[real]]) + [value]
            else:
                query[real] = value
        elif spec_p["in"] == "header":
            headers[real] = value
        else:
            problems.append(f"parameter '{real}' is passed in the {spec_p['in']}, which `call` does not set")
    for p in op.params:
        name = p.get("name") or ""
        if not p["required"] or name.lower() in AUTO_HEADERS:
            continue
        if (p["in"] == "path" and name not in path_vals) or (p["in"] == "query" and name not in query) \
                or (p["in"] == "header" and name not in headers):
            problems.append(f"missing required {p['in']} parameter '{name}'")
    needs_project = any((p.get("name") or "").lower() == "x-mstr-projectid" and p["required"] for p in op.params)
    takes_project = any((p.get("name") or "").lower() == "x-mstr-projectid" for p in op.params)
    if takes_project and project:
        headers["X-MSTR-ProjectID"] = project
    elif needs_project:
        problems.append("this operation needs a project: pass --project (or set MSTR_PROJECT_ID / MSTR_PROJECT_NAME)")
    spec_body = op.body
    if spec_body is None and body is not None:
        problems.append("this operation takes no request body")
    if spec_body is not None and not multipart:
        if body is None and spec_body["required"]:
            problems.append(f"this operation needs a request body ({spec_body['content_type']}); see `describe`")
        if body is not None and "json" not in spec_body["content_type"]:
            problems.append(f"the body must be {spec_body['content_type']}; use build_mosaic.py api-call --file/--form")
        schema = spec_body["schema"]
        if isinstance(body, dict) and isinstance(schema, dict):
            missing = [k for k in (schema.get("required") or []) if k not in body]
            if missing:
                problems.append(f"request body is missing required field(s): {', '.join(missing)}")
    if problems:
        raise ApiError(f"{op.key()} — " + "; ".join(problems))
    path = op.path
    for name, value in path_vals.items():
        path = path.replace("{" + name + "}", urllib.parse.quote(value, safe=""))
    return {"path": path, "query": query, "headers": headers, "json": body}


def _redact(headers: dict) -> dict:
    hidden = {"x-mstr-authtoken", "x-mstr-identitytoken", "set-cookie", "cookie", "authorization"}
    return {k: ("<redacted>" if k.lower() in hidden else v) for k, v in headers.items()}


def _load_body(value: str | None) -> Any:
    if value is None:
        return None
    text = value
    if value.startswith("@"):
        with open(value[1:], encoding="utf-8") as f:
            text = f.read()
    try:
        return json.loads(text)
    except ValueError as e:
        raise ApiError(f"--body is not valid JSON: {e}") from None


def _resolve_project(session: Any, base: str, project: str) -> str:
    if re.fullmatch(r"[0-9A-Fa-f]{32}", project or ""):
        return project.upper()
    r = session.get(f"{base}/api/projects", timeout=60)
    if not r.ok:
        raise ApiError(f"could not list projects to resolve '{project}': {sa.describe(r)}")
    hits = [p for p in r.json() if str(p.get("name", "")).lower() == project.lower()]
    if len(hits) != 1:
        raise ApiError(f"project '{project}': {len(hits)} matches")
    return hits[0]["id"]


def auto_headers(op: Operation, accept: str = "") -> dict:
    """Headers `call` adds on its own: Accept for non-JSON responses, Prefer when required."""
    out: dict[str, str] = {}
    types = op.response_types
    if accept:
        out["Accept"] = accept
    elif types and not any("json" in t or t == "*/*" for t in types):
        out["Accept"] = ", ".join(types)   # exports: PDF, Excel, CSV, YAML, binary
    names = {(p.get("name") or "").lower(): p for p in op.params}
    if "prefer" in names and names["prefer"]["required"]:
        out["Prefer"] = "respond-async"
    return out


def needs_changeset(op: Operation) -> bool:
    return any((p.get("name") or "").lower() == "x-mstr-ms-changeset" and p["required"] for p in op.params)


def call(op: Operation, req: dict, *, base: str, session: Any, changeset: str = "auto",
         schema_edit: bool = False, project: str = "", accept: str = "", files: dict | None = None,
         form: dict | None = None) -> dict:
    """Send a validated request; manage the Modeling changeset when the operation needs one."""
    headers = {**auto_headers(op, accept), **req["headers"]}
    names = {(p.get("name") or "").lower(): p for p in op.params}
    cs_headers = {"X-MSTR-ProjectID": project} if project else {}   # ms-createChangeset needs it
    cs_param = names.get("x-mstr-ms-changeset")
    opened = None
    if cs_param and changeset not in ("auto", "none", ""):
        headers["X-MSTR-MS-Changeset"] = changeset
    elif cs_param and cs_param["required"]:
        if changeset == "none":
            raise ApiError(f"{op.key()} needs a Modeling changeset; drop --changeset none or pass an id")
        q = "?schemaEdit=true" if schema_edit else ""
        r = session.post(f"{base}/api/model/changesets{q}", json={"schemaEdit": True} if schema_edit else {},
                         headers=cs_headers, timeout=60)
        if not r.ok:
            raise ApiError(f"could not open a changeset: {sa.describe(r)}")
        opened = (r.json() or {}).get("id")
        headers["X-MSTR-MS-Changeset"] = opened
    outcome = None
    try:
        if files or form:   # multipart: let requests set the boundary Content-Type
            headers["Content-Type"] = None   # type: ignore[assignment]
            r = session.request(op.verb, f"{base}{req['path']}", params=req["query"] or None, headers=headers,
                                files=files or None, data=form or None, timeout=300)
        else:
            r = session.request(op.verb, f"{base}{req['path']}", params=req["query"] or None, headers=headers,
                                json=req["json"], timeout=300)
    except BaseException:
        if opened:
            session.delete(f"{base}/api/model/changesets/{opened}", headers=cs_headers, timeout=60)
        raise
    if opened:
        if r.ok and op.verb not in READ_VERBS:
            c = session.post(f"{base}/api/model/changesets/{opened}/commit", headers=cs_headers, timeout=300)
            outcome = "committed" if c.ok else f"commit failed ({sa.describe(c)}); discarded"
            if not c.ok:
                session.delete(f"{base}/api/model/changesets/{opened}", headers=cs_headers, timeout=60)
        else:
            session.delete(f"{base}/api/model/changesets/{opened}", headers=cs_headers, timeout=60)
            outcome = "discarded"
    return {"response": r, "changeset": outcome}


# ── Commands ─────────────────────────────────────────────────────────────────

def cmd_tags(spec: dict) -> list[dict]:
    rows: dict[str, dict] = {}
    for o in operations(spec):
        row = rows.setdefault(o.tag, {"tag": o.tag, "skill": skill_for_tag(o.tag), "operations": 0, "public": 0})
        row["operations"] += 1
        row["public"] += not o.internal
    return sorted(rows.values(), key=lambda r: (r["skill"], -r["operations"]))


def cmd_ops(spec: dict, tag: str = "", search: str = "", internal: bool = False, limit: int = 200) -> list[dict]:
    words = [w.lower() for w in search.split()]
    out = []
    for o in operations(spec):
        if o.internal and not internal:
            continue
        if tag and o.tag.lower() != tag.lower() and skill_for_tag(o.tag) != tag:
            continue
        text = f"{o.id} {o.path} {o.summary} {o.tag}".lower()
        if words and not all(w in text for w in words):
            continue
        out.append({"operation": o.id, "request": o.key(), "summary": o.summary[:100],
                    **({"internal": True} if o.internal else {}), **({"deprecated": True} if o.deprecated else {})})
    return out[:limit]


def cmd_describe(op: Operation) -> dict:
    body = op.body
    return {
        "operation": op.id, "request": op.key(), "area": op.tag, "skill": skill_for_tag(op.tag),
        "summary": op.summary, "description": (op.raw.get("description") or "").strip()[:1500],
        "internal": op.internal, "deprecated": op.deprecated,
        "parameters": [{k: v for k, v in p.items() if v not in (None, "", False) or k == "required"}
                       for p in op.params if (p.get("name") or "").lower() != "x-mstr-authtoken"],
        "filled_in_by_call": sorted({p["name"] for p in op.params
                                     if (p.get("name") or "").lower() in AUTO_HEADERS - {"x-mstr-authtoken"}}),
        "body": None if body is None else {"required": body["required"], "content_type": body["content_type"],
                                           "skeleton": body_skeleton(op.spec, body["schema"])},
        "responses": {code: (r.get("description") or "")[:120]
                      for code, r in (op.raw.get("responses") or {}).items()},
    }


def cmd_coverage(spec: dict, repo: str) -> tuple[list[dict], dict]:
    """Per area: operations, public, owning skill, and how many of its paths the repo's scripts
    and notes reference (a path mention, not a verified workflow)."""
    templates = {o.path for o in operations(spec)}
    regexes = {t: re.compile("^" + re.sub(r"\\\{[^}]+\\\}", "[^/]+", re.escape(t)) + "$") for t in templates}

    def mentioned(files: list[str]) -> set[str]:
        found: set[str] = set()
        for f in files:
            try:
                text = open(f, encoding="utf-8", errors="ignore").read()
            except OSError:
                continue
            for m in re.finditer(r"/api/[A-Za-z0-9_\-/{}.$<>]+", text):
                raw = re.sub(r"\{[^}/]*\}|<[^>/]*>|\$\w+", "X", m.group(0).split("?")[0].rstrip(".,;:)`'\""))
                found.update(t for t, rx in regexes.items() if rx.match(raw))
        return found

    scripts, notes = [], []
    for dirpath, _dirs, files in os.walk(repo):
        if "/." in dirpath or "/ignore" in dirpath or "/captures" in dirpath or "/tests" in dirpath:
            continue
        for name in files:
            full = os.path.join(dirpath, name)
            if name.endswith(".py"):
                scripts.append(full)
            elif name.endswith(".md"):
                notes.append(full)
    in_code, in_docs = mentioned(scripts), mentioned(notes)
    in_skills: set[str] = set()   # operations a SKILL.md workflow runs: `strategy_api.py call|describe <op>`
    ref_rx = re.compile(r'(?:strategy_api\.py|\$API)\s+(?:call|describe)\s+'
                        r'("(?:GET|POST|PUT|PATCH|DELETE|HEAD) /api/[^"]+"|[A-Za-z][A-Za-z0-9_\-]*[A-Za-z0-9_])')
    for f in notes:
        if os.path.basename(f) != "SKILL.md":
            continue
        for m in ref_rx.finditer(open(f, encoding="utf-8", errors="ignore").read()):
            try:
                in_skills.add(find_operation(spec, m.group(1).strip('"')).key())
            except ApiError:
                pass
    rows: dict[str, dict] = {}
    for o in operations(spec):
        row = rows.setdefault(o.tag, {"area": o.tag, "skill": skill_for_tag(o.tag), "operations": 0, "public": 0,
                                      "in_scripts": 0, "in_skills": 0, "in_notes": 0})
        row["operations"] += 1
        row["public"] += not o.internal
        row["in_scripts"] += o.path in in_code
        row["in_skills"] += o.key() in in_skills
        row["in_notes"] += o.path in in_docs
    totals = {k: sum(r[k] for r in rows.values())
              for k in ("operations", "public", "in_scripts", "in_skills", "in_notes")}
    return sorted(rows.values(), key=lambda r: (r["skill"], -r["operations"])), totals


def coverage_markdown(rows: list[dict], totals: dict, spec: dict) -> str:
    version = (spec.get("info") or {}).get("version", "?")
    lines = [
        "---",
        "name: Strategy REST API surface — every area, its owning skill, and coverage",
        "description: Generated map of the tenant's REST API (operations per area, public vs internal), the skill "
        "that owns each area, and how much of it this repo's scripts and notes reference. Regenerate with "
        "`strategy_api.py coverage --write`.",
        "type: reference",
        "---",
        "",
        f"Generated {time.strftime('%Y-%m-%d')} from the tenant's OpenAPI spec (version {version}) by "
        "`skills/strategy-platform/scripts/strategy_api.py coverage --write`. Do not hand-edit the table; change "
        "`SKILL_TAGS` in `strategy_api.py` to move an area.",
        "",
        "**Every operation is callable** with `strategy_api.py call <operationId>` — validated against the spec, "
        "with project, changeset and `Prefer` headers filled in and writes gated behind `--yes`. The columns "
        "below measure the *extra* layers: typed helpers (operations whose path a script calls), skill "
        "workflows (operations a SKILL.md runs with `strategy_api.py call`), and field notes (paths mentioned "
        "in memory/skills). A reference is a pointer, not proof of a live-tested workflow — each skill's "
        "Status section says what has run live.",
        "",
        f"Totals: {totals['operations']} operations ({totals['public']} public); {totals['in_scripts']} called by "
        f"scripts, {totals['in_skills']} run by skill workflows, {totals['in_notes']} mentioned in notes.",
        "",
        "| Owning skill | API area (spec tag) | Operations | Public | In scripts | In skill workflows | In notes |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(f"| `{r['skill']}` | {r['area']} | {r['operations']} | {r['public']} | "
                     f"{r['in_scripts']} | {r['in_skills']} | {r['in_notes']} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--base", default="", help="Library URL (env MSTR_BASE)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("sync", help="download the tenant's spec into the cache")
    sub.add_parser("tags", help="every API area with operation counts and owning skill")
    op_p = sub.add_parser("ops", help="list operations")
    op_p.add_argument("--tag", default="", help="spec tag (API area) or owning skill name")
    op_p.add_argument("--search", default="", help="words that must all appear (id, path, summary)")
    op_p.add_argument("--internal", action="store_true", help="include operations marked internal")
    op_p.add_argument("--limit", type=int, default=200)
    d_p = sub.add_parser("describe", help="parameters, headers, body skeleton and responses of one operation")
    d_p.add_argument("operation", help='operationId or "VERB /api/path"')
    c_p = sub.add_parser("call", help="validate and send one operation")
    c_p.add_argument("operation", help='operationId or "VERB /api/path"')
    c_p.add_argument("-p", "--param", action="append", default=[], help="name=value (path, query or header); repeat")
    c_p.add_argument("--body", default=None, help="JSON body, or @file.json")
    c_p.add_argument("--file", action="append", default=[],
                     help="multipart file part FIELD=PATH (for operations whose body is multipart/form-data)")
    c_p.add_argument("--form", action="append", default=[], help="multipart text field NAME=VALUE")
    c_p.add_argument("--accept", default="", help="override the Accept header (default: from the spec)")
    c_p.add_argument("--project", default=os.environ.get("MSTR_PROJECT_ID") or os.environ.get("MSTR_PROJECT_NAME", ""),
                     help="project id or name for X-MSTR-ProjectID (env MSTR_PROJECT_ID / MSTR_PROJECT_NAME)")
    c_p.add_argument("--changeset", default="auto", help="auto (default), none, or an existing changeset id")
    c_p.add_argument("--schema-edit", action="store_true", help="open the changeset with schemaEdit=true")
    c_p.add_argument("--yes", action="store_true", help="send a write (anything but GET/HEAD); default: print only")
    c_p.add_argument("--out", default="", help="write the response body to this file")
    c_p.add_argument("--text-limit", type=int, default=20000)
    c_p.add_argument("--reuse-session", action="store_true",
                     help="keep the signed-in session for the next call (env MSTR_REUSE_SESSION=1): report "
                          "instances, search results and running jobs survive between steps; "
                          "end it with strategy_auth.py logout")
    sa.add_auth_method_arg(c_p)
    ex = sub.add_parser("export-index", help="write VERB<TAB>path<TAB>area<TAB>visibility<TAB>operationId lines (CI fixture)")
    ex.add_argument("--out", required=True)
    cov = sub.add_parser("coverage", help="per-area coverage of the repo; --write regenerates the surface note")
    cov.add_argument("--repo", default=os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                                     os.pardir, os.pardir, os.pardir)))
    cov.add_argument("--write", default="", help="write the markdown surface map to this path")
    args = ap.parse_args(argv)
    base = (args.base or os.environ.get("MSTR_BASE", "")).rstrip("/")
    try:
        if args.cmd == "sync":
            print(json.dumps({"ok": True, "cached": sync_spec(base)}, indent=2))
            return 0
        spec = load_spec(base)
        if args.cmd == "tags":
            out: Any = cmd_tags(spec)
        elif args.cmd == "ops":
            out = cmd_ops(spec, args.tag, args.search, args.internal, args.limit)
        elif args.cmd == "describe":
            out = cmd_describe(find_operation(spec, args.operation))
        elif args.cmd == "export-index":
            lines = sorted(f"{o.verb}\t{o.path}\t{o.tag}\t{'internal' if o.internal else 'public'}\t{o.id}"
                           for o in operations(spec))
            with open(args.out, "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
            out = {"operations": len(lines), "written": args.out}
        elif args.cmd == "coverage":
            rows, totals = cmd_coverage(spec, args.repo)
            if args.write:
                with open(args.write, "w", encoding="utf-8") as f:
                    f.write(coverage_markdown(rows, totals, spec))
            out = {"totals": totals, "unassigned": [r["area"] for r in rows if r["skill"] == "unassigned"],
                   "written": args.write or None}
        else:
            return _cmd_call(args, spec, base)
    except (ApiError, sa.AuthError) as e:
        print(f"FATAL: {e}", file=sys.stderr)
        return 2
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


def _cmd_call(args: argparse.Namespace, spec: dict, base: str) -> int:
    op = find_operation(spec, args.operation)
    if op.internal:
        print(f"[api] {op.key()} is internal (not part of the public contract) — it may change without notice.",
              file=sys.stderr)
    if op.deprecated:
        print(f"[api] {op.key()} is deprecated.", file=sys.stderr)
    body = _load_body(args.body)
    files, form = _multipart(op, args.file, args.form, body)
    if files or form:
        body = None
    takes_project = any((p.get("name") or "").lower() == "x-mstr-projectid" for p in op.params)
    project = args.project if (takes_project or needs_changeset(op)) else ""
    is_write = op.verb not in READ_VERBS
    if is_write and not args.yes:
        req = build_request(op, args.param, body if not files and not form else None,
                            project if takes_project else None, multipart=bool(files or form))
        planned = auto_headers(op, args.accept)
        if needs_changeset(op):
            planned["X-MSTR-MS-Changeset"] = ("<opened, committed on success, discarded on failure>"
                                              if args.changeset == "auto" else args.changeset)
        print(json.dumps({"dry_run": True, "operation": op.id, "request": f"{op.verb} {base}{req['path']}",
                          "query": req["query"], "headers": _redact({**planned, **req["headers"]}),
                          "body": req["json"], "multipart": {"files": sorted(files), "form": form} if files or form
                          else None, "note": "writes need --yes"}, indent=2))
        for handle in files.values():
            handle[1].close()
        return 0
    session = requests.Session()
    session.headers.update({"Accept": "application/json", "Content-Type": "application/json"})
    signin = sa.sign_in(session, sa.AuthConfig.from_env(base=base, method=args.auth_method,
                                                        reuse=True if args.reuse_session else None))
    try:
        if project:
            project = _resolve_project(session, base, project)
        req = build_request(op, args.param, body, project if takes_project else None,
                            multipart=bool(files or form))
        result = call(op, req, base=base, session=session, changeset=args.changeset,
                      schema_edit=args.schema_edit, project=project, accept=args.accept, files=files, form=form)
    finally:
        for handle in files.values():
            handle[1].close()
        sa.sign_out(session, base, signin)
    r = result["response"]
    out: dict[str, Any] = {"ok": r.ok, "status": r.status_code, "operation": op.id, "request": f"{op.verb} {req['path']}",
                           "headers": _redact({k: v for k, v in r.headers.items()
                                               if k.lower().startswith("x-mstr") or k.lower() == "location"})}
    if result["changeset"]:
        out["changeset"] = result["changeset"]
    target = args.out
    ctype = (r.headers.get("Content-Type") or "").split(";")[0].strip().lower()
    binary = bool(r.content) and not ("json" in ctype or ctype.startswith("text/") or ctype.endswith("xml")
                                      or ctype.endswith("yaml") or not ctype)
    if not target and (binary or len(r.content) > args.text_limit):   # keep big or binary payloads off the console
        suffix = {"application/pdf": ".pdf", "text/csv": ".csv", "application/yaml": ".yaml",
                  "application/zip": ".zip", "image/png": ".png"}.get(ctype, ".json" if "json" in ctype else ".bin")
        if "spreadsheet" in ctype or "excel" in ctype:
            suffix = ".xlsx"
        fd, target = tempfile.mkstemp(prefix=f"strategy-api-{re.sub(r'[^A-Za-z0-9_-]', '_', op.id)}-", suffix=suffix)
        os.close(fd)
    if target:
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(r.content)
        out["body_written_to"] = target
        out["body_bytes"] = len(r.content)
        out["content_type"] = ctype or None
        try:
            if binary:
                raise ValueError("binary")
            data = r.json()
            out["body_preview"] = (sorted(data)[:20] if isinstance(data, dict)
                                   else f"list of {len(data)}" if isinstance(data, list) else None)
        except ValueError:
            out["body_preview"] = None if binary else r.text[:300]
    else:
        try:
            out["body"] = r.json()
        except ValueError:
            out["body"] = r.text
    print(json.dumps(out, indent=2, ensure_ascii=False, default=str))
    return 0 if r.ok else 1


if __name__ == "__main__":
    sys.exit(main())
