#!/usr/bin/env python3
"""
build_mosaic.py — discovery + build CLI for Strategy Mosaic semantic models.

Subcommands:
  auth-probe                 Confirm login + identity-token flow works.
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
  discover                   Probe endpoint variants when the server version is unknown.

All subcommands take optional --base / --project-id / --user / --password or read them
from env vars MSTR_BASE / MSTR_PROJECT_ID / MSTR_USER / MSTR_PASSWORD. Do not hardcode
secrets in this file; set MSTR_PASSWORD in the shell or keychain-backed environment.

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

# ── Defaults (tenant-specific; override via env or flags) ─────────────────────
DEFAULT_BASE       = os.environ.get("MSTR_BASE", "https://studio.strategy.com/MicroStrategyLibrary")
DEFAULT_PROJECT_ID = os.environ.get("MSTR_PROJECT_ID", "1FC5A43B374C963CC773C285DF86E2F6")
DEFAULT_USER       = os.environ.get("MSTR_USER", "<operator-user>")
DEFAULT_PASSWORD   = os.environ.get("MSTR_PASSWORD", "")
DEFAULT_LOGIN_MODE = int(os.environ.get("MSTR_LOGIN_MODE", "1"))
DEFAULT_DEST_FOLDER = os.environ.get("MSTR_DEST_FOLDER", "DC377018BD4CACD81B7E4CAEB8DB62B4")
FORM_ID            = "45C11FA478E745FEA08D781CEA190FE5"   # universal ID form

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
        self.s       = requests.Session()
        self.s.headers.update({"Content-Type":"application/json","Accept":"application/json"})
        self.verbose = args.verbose

    def login(self):
        if not self.pw:
            die("missing password. Set MSTR_PASSWORD or pass --password; do not store secrets in skill/memory files.")
        r = self.s.post(f"{self.base}/api/auth/login",
                        json={"username": self.user, "password": self.pw, "loginMode": self.mode})
        r.raise_for_status()
        tok = r.headers.get("X-Mstr-Authtoken") or r.headers.get("X-MSTR-AuthToken","")
        if not tok:
            die(f"login: no auth token in response headers: {dict(r.headers)}")
        self.s.headers["X-MSTR-AuthToken"] = tok
        self.s.headers["X-MSTR-ProjectID"] = self.project
        # Identity token — required for Modeling Service changesets
        r2 = self.s.post(f"{self.base}/api/auth/identityToken")
        if r2.ok:
            id_tok = r2.headers.get("X-Mstr-Identitytoken") or r2.headers.get("X-MSTR-IdentityToken","")
            if id_tok:
                self.s.headers["X-MSTR-IdentityToken"] = id_tok
        if self.verbose:
            print(f"[auth] token={tok[:12]}…  identity={'yes' if 'X-MSTR-IdentityToken' in self.s.headers else 'no'}", file=sys.stderr)

    # raw helpers
    def get(self, path, **kw):  return self.s.get(f"{self.base}{path}", **kw)
    def post(self, path, **kw): return self.s.post(f"{self.base}{path}", **kw)
    def put(self, path, **kw):  return self.s.put(f"{self.base}{path}", **kw)
    def patch(self, path, **kw): return self.s.patch(f"{self.base}{path}", **kw)
    def delete(self, path, **kw): return self.s.delete(f"{self.base}{path}", **kw)

    def logout(self):
        try:
            self.delete("/api/auth/login")
        except requests.RequestException:
            pass

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
    m.login()
    print(json.dumps({
        "ok": True,
        "base": m.base,
        "project_id": m.project,
        "user": m.user,
        "has_auth_token": "X-MSTR-AuthToken" in m.s.headers,
        "has_identity_token": "X-MSTR-IdentityToken" in m.s.headers,
    }, indent=2))


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
        m.login()
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


def fetch_table_metadata(m: MSTR, ds_id: str, namespace: str, tname: str) -> dict:
    ns_id = resolve_namespace_id(m, ds_id, namespace)
    tb_id = encode_tb_id(namespace, tname)
    path, body = m.try_candidates("describe_table", id=ds_id, ns_id=ns_id, tb_id=tb_id)
    cols = body.get("columns") or body.get("physicalTable",{}).get("columns") or []
    return {"raw": body, "columns": cols, "tb_id": tb_id, "ns_id": ns_id}


def _col_dtype(c: dict) -> str:
    """Return a lowercase string dataType, handling both flat string and nested {type,scale,precision} shapes."""
    dt = c.get("dataType") or c.get("type") or ""
    if isinstance(dt, dict): dt = dt.get("type","")
    return str(dt).lower()


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
        if any(t in dtype for t in NUMERIC_TYPES):
            metrics.append(c)
        else:
            attrs.append(c)
    return attrs, metrics


def open_cs(m: MSTR) -> str:
    r = m.post("/api/model/changesets", json={})
    r.raise_for_status()
    d = r.json()
    cs = d.get("id") or d.get("changesetId","")
    if not cs: die(f"open_cs: {d}")
    m.s.headers["X-MSTR-MS-Changeset"] = cs
    return cs


def commit_cs(m: MSTR, cs: str):
    r = m.post(f"/api/model/changesets/{cs}/commit")
    m.s.headers.pop("X-MSTR-MS-Changeset", None)
    if not r.ok:
        die(f"commit {cs}: {r.status_code} {r.text[:400]}")


def cmd_build(m: MSTR, args):
    m.login()
    sources = [parse_source(s) for s in args.source]
    if args.instance and args.schema and args.tables:
        sources.append((args.instance, args.schema, args.tables))
    if not sources:
        die("provide at least one --source INSTANCE:SCHEMA:T1,T2 or --instance/--schema/--tables")

    # Load optional overrides / ERD
    dictionary = load_dictionary(getattr(args,"dictionary",None))
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
    patch_body = {"operationList":[{"op":"addElements", "path":"/members", "value": member_ids}]}
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


def _apply_security_filter(m: MSTR, model_id: str, spec: str):
    """spec format: 'NAME=qualification_text|USER,USER' — minimal; for richer
    qualifications use --sf-config pointing at a JSON file."""
    parts = spec.split("|")
    nq, users = parts[0], (parts[1].split(",") if len(parts)>1 else [])
    name, _, qual = nq.partition("=")
    cs = open_cs(m)
    r = m.post(f"/api/model/dataModels/{model_id}/securityFilters?changesetId={cs}",
               json={"information":{"name": name},
                     "qualification":{"tree":{"type":"predicate_false","predicateText": qual}},
                     "topLevel":[],"bottomLevel":[]})
    if not r.ok: die(f"security filter '{name}': {r.status_code} {r.text[:300]}")
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


def _publish(m: MSTR, model_id: str):
    for path in [f"/api/cubes/{model_id}",
                 f"/api/model/dataModels/{model_id}/publish",
                 f"/api/model/dataModels/{model_id}/import",
                 f"/api/cubes/{model_id}/publish"]:
        r = m.post(path, json={})
        if r.ok:
            print(f"  ✓ published via {path}", file=sys.stderr); return
    print(f"  WARN: no publish endpoint accepted", file=sys.stderr)


def cmd_set_serve_mode(m: MSTR, args):
    m.login()
    r = m.s.patch(f"{m.base}/api/model/dataModels/{args.model_id}",
                  json={"dataServeMode": args.mode})
    print(f"HTTP {r.status_code}: {r.text[:300]}")

def cmd_publish(m: MSTR, args):  m.login(); _publish(m, args.model_id)
def cmd_refresh(m: MSTR, args):
    m.login()
    r = m.post(f"/api/cubes/{args.model_id}/refresh",
               params={"refreshType": args.refresh_type})
    print(f"HTTP {r.status_code}: {r.text[:300]}")
def cmd_delete_model(m: MSTR, args):
    m.login()
    r = m.delete(f"/api/objects/{args.model_id}?type=3")
    print(f"HTTP {r.status_code}: {r.text[:300]}")
def cmd_set_acl(m: MSTR, args):
    m.login(); _apply_acl(m, args.object_id, args.grant, model_id=args.model_id,
                          sub_type=args.sub_type, denies=args.deny)
def cmd_add_security_filter(m: MSTR, args):
    m.login(); _apply_security_filter(m, args.model_id, args.spec)
def cmd_translate(m: MSTR, args):
    m.login(); _apply_translations(m, args.model_id, args.entry, default_sub_type=args.sub_type)
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
    m.login()
    path, _ = _model_object_path(args.kind, args.model_id, args.object_id)
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
    m.login()
    path, info = _model_object_path(args.kind, args.model_id, args.object_id)
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
    m.login()
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
    m.login()
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
    m.login()
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
    m.login()
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
    sp.add_argument("--security-filter", action="append", default=[],
                    help="'NAME=qualification|USER,USER' (repeatable)")
    sp.add_argument("--grant", action="append", default=[],
                    help="ACL grant 'trusteeId:right1,right2' (repeatable)")
    sp.add_argument("--deny", action="append", default=[],
                    help="ACL deny 'trusteeId:right1,right2' (repeatable)")
    sp.add_argument("--translate", action="append", default=[],
                    help="'objectId[:subType]:locale[:name|description]=translation' (repeatable)")
    sp.add_argument("--certify", action="store_true")
    sp.add_argument("--publish", action="store_true", help="publish cube for in_memory mode")

    sp = sub.add_parser("build-from-config")
    sp.add_argument("--config", required=True, help="path to YAML/JSON spec file")
    sp.add_argument("--dest-folder", default=DEFAULT_DEST_FOLDER)

    sp = sub.add_parser("set-serve-mode")
    sp.add_argument("--model-id", required=True)
    sp.add_argument("--mode", required=True, choices=["connect_live","in_memory","hybrid"])

    sp = sub.add_parser("publish"); sp.add_argument("--model-id", required=True)

    sp = sub.add_parser("refresh")
    sp.add_argument("--model-id", required=True)
    sp.add_argument("--refresh-type", default="incremental",
                    choices=["update","add","replace","incremental"])

    sp = sub.add_parser("delete-model"); sp.add_argument("--model-id", required=True)

    sp = sub.add_parser("set-acl")
    sp.add_argument("--model-id", help="required for data-model-contained objects")
    sp.add_argument("--object-id", required=True)
    sp.add_argument("--sub-type", default="data_model",
                    help="object subtype for data model ACL endpoint, e.g. data_model, fact_metric, attribute")
    sp.add_argument("--grant", action="append", default=[], help="'trusteeId:rights' (repeatable)")
    sp.add_argument("--deny", action="append", default=[], help="'trusteeId:rights' (repeatable)")

    sp = sub.add_parser("add-security-filter")
    sp.add_argument("--model-id", required=True)
    sp.add_argument("--spec", required=True, help="'NAME=qualification|USER,USER'")

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
            "set-serve-mode":  cmd_set_serve_mode,
            "publish":         cmd_publish,
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
        if args.verbose:
            print(f"[wall] {int((time.monotonic()-t0)*1000)}ms", file=sys.stderr)


if __name__ == "__main__":
    main()
