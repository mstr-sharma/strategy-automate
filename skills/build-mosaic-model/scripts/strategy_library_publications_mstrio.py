#!/usr/bin/env python3
"""
strategy_library_publications_mstrio.py - the mstrio-py version of strategy_library_publications.py.
Same two commands, same CSV columns (the files are interchangeable). It is the
compact version: the requests-only strategy_library_publications.py adds retries,
--match-by-name, folder paths, a recipient existence check and parallel reads.

Requirements: Python >= 3.10 and mstrio-py >= 11.5.7.101 (tested with 11.6.9.101):
    pip install --upgrade mstrio-py

    export MSTR_BASE=https://host/MicroStrategyLibrary MSTR_USER=admin   # MSTR_PASSWORD optional
    python strategy_library_publications_mstrio.py export    --project "Sales" --out mapping.csv
    python strategy_library_publications_mstrio.py replicate --mapping mapping.csv --target-project "Sales Copy"          # dry run
    python strategy_library_publications_mstrio.py replicate --mapping mapping.csv --target-project "Sales Copy" --apply
Optional env: MSTR_LOGIN_MODE (1 standard, 16 LDAP, 4096 API token + MSTR_API_TOKEN),
MSTR_SSL_VERIFY ("0" to skip certificate checks, or a CA bundle path).

What uses mstrio-py's high-level API:
    * Connection: login, session renewal, logout.
    * list_dashboards / list_documents / list_agents / list_reports: metadata
      search, including the dashboard/document split by viewMedia.

Where it deliberately calls connection.get()/post() with an explicit
X-MSTR-ProjectID header instead of the high-level helpers:
    * Reading recipients. Dashboard/Document(...).recipients builds every
      recipient with User.from_dict, so a user GROUP comes back as a `User`
      object; only `.subtype == 8705` shows it is a group. In mstrio-py
      < 11.5.7.101 it went through list_users() and dropped groups entirely.
      The property also reads the connection's currently *selected* project.
      A duplicated project has the same object IDs, so with the wrong project
      selected it silently returns the other project's recipients.
    * Publishing. Dashboard/Document.publish(recipients=[ids]) looks up each ID
      with User()/UserGroup() and silently drops IDs it cannot read (for example
      403 for a non-admin). In mstrio-py < 11.5.7.101, publish(UserGroup)
      expanded the group to its CURRENT members instead of publishing to the
      group. Raw POST /api/library sends group IDs as groups; it is additive and
      re-posting an existing recipient is a no-op (verified live).
    * Never call Dashboard/Document.unpublish() without arguments: it sends
      DELETE /api/library/{id}, which unpublishes the object for EVERY user.
      This script never unpublishes anything.
Do not run it with root logging at DEBUG: mstrio then logs request bodies,
including the login password.
"""

from __future__ import annotations

import argparse
import collections
import csv
import getpass
import os
import re
import sys
import types
from typing import TYPE_CHECKING

_PLATFORM = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                          os.pardir, os.pardir, "strategy-platform", "scripts"))
if _PLATFORM not in sys.path:
    sys.path.insert(0, _PLATFORM)
import strategy_auth  # noqa: E402  (platform core: the base-URL policy every script shares)

if TYPE_CHECKING:  # mstrio-py is imported late (load_mstrio) so --help works without it
    from mstrio.connection import Connection

# The documented minimum (group recipients, publish semantics; see the docstring). It has
# list_dashboards / list_documents / list_reports, which older releases lack.
MIN_MSTRIO = "11.5.7.101"

ID_RE = re.compile(r"^[0-9A-Fa-f]{32}$")
RECIPIENT_TYPE = {8704: "user", 8705: "group"}
KIND_OBJECT_TYPE = {"dashboard": 55, "document": 55, "agent": 55, "report": 3}
CSV_FIELDS = ["document_id", "document_name", "document_kind", "subtype",
              "recipient_id", "recipient_name", "recipient_type",
              "object_type", "folder_path", "source_project_id", "source_project_name"]
_ESCAPE_START = ("=", "+", "-", "@", "\t", "\r", "'")


def csv_safe(v):
    """Names are author-controlled: keep Excel from running one as a formula (same
    escaping as strategy_library_publications.py, so the two scripts' CSVs stay interchangeable)."""
    return "'" + v if isinstance(v, str) and v.startswith(_ESCAPE_START) else v


def csv_unsafe(v: str) -> str:
    return v[1:] if v.startswith("'") and v[1:].startswith(_ESCAPE_START) else v


def private_open(path: str, **kw):
    """open(path, "w") for a file readable only by this user (0600), also when it already
    existed: the mapping carries recipient names (same rule as strategy_library_publications.py)."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    if hasattr(os, "fchmod"):   # POSIX; O_CREAT's mode only applies to a new file
        os.fchmod(fd, 0o600)
    return os.fdopen(fd, "w", **kw)


def load_mstrio() -> types.SimpleNamespace:
    """Import mstrio-py on demand, so --help works without it. Raises ImportError when
    mstrio-py is missing or older than MIN_MSTRIO."""
    from mstrio.connection import Connection
    from mstrio.project_objects import list_dashboards, list_documents, list_reports
    return types.SimpleNamespace(Connection=Connection, list_dashboards=list_dashboards,
                                 list_documents=list_documents, list_reports=list_reports)


def list_agents_compat(conn, **kw):
    """list_agents arrived in mstrio-py 11.5.10.101; older releases call them bots."""
    try:
        from mstrio.project_objects import list_agents
    except ImportError:
        from mstrio.project_objects.bots import list_bots as list_agents
    return list_agents(conn, **kw)


# --types value -> (kind, object type, name of the mstrio lister; None = list_agents_compat)
LISTERS = {
    "dashboards": ("dashboard", 55, "list_dashboards"),
    "documents": ("document", 55, "list_documents"),
    "agents": ("agent", 55, None),
    # list_reports keeps the report subtypes mstrio's Report class supports
    # (grid, graph, grid+graph, datamart, transaction, ...); cubes are excluded.
    "reports": ("report", 3, "list_reports"),
}


def parse_types(value: str) -> list:
    """--types -> list of LISTERS keys; exits on anything else (before any network call)."""
    types_ = list(LISTERS) if value == "all" else [t.strip() for t in value.split(",") if t.strip()]
    if not types_ or set(types_) - set(LISTERS):
        print("--types takes a comma list of %s, or all" % ",".join(LISTERS), file=sys.stderr)
        raise SystemExit(2)   # usage error, like argparse's own
    return types_


def connect(ms: types.SimpleNamespace) -> Connection:
    base = os.environ.get("MSTR_BASE") or sys.exit("Set MSTR_BASE")
    try:   # same policy as every other script: https (localhost aside), no credentials in the URL
        strategy_auth.check_base(base.rstrip("/"))
    except strategy_auth.AuthError as err:
        sys.exit(str(err))
    mode = int(os.environ.get("MSTR_LOGIN_MODE", "1"))
    ssl = os.environ.get("MSTR_SSL_VERIFY", "1").strip()
    tls = {"ssl_verify": False} if ssl.lower() in ("0", "false", "no", "off") else \
        {"ssl_verify": True} if ssl.lower() in ("", "1", "true", "yes", "on") else \
        {"ssl_verify": True, "certificate_path": ssl}
    if mode == 4096:
        return ms.Connection(base, api_token=os.environ.get("MSTR_API_TOKEN") or sys.exit("Set MSTR_API_TOKEN"),
                             request_timeout=120, **tls)
    user = os.environ.get("MSTR_USER") or sys.exit("Set MSTR_USER")
    password = os.environ.get("MSTR_PASSWORD") or getpass.getpass("Password for %s: " % user)
    return ms.Connection(base, user, password, login_mode=mode, request_timeout=120, **tls)


def resolve_project(conn: Connection, ref: str):
    """Exact ID or exact name -> (id, name). (Project(conn, name=...) goes
    through the monitors API, which needs admin privileges; GET /api/projects
    does not.)"""
    projects = conn.get(endpoint="/api/projects").json()
    hits = [p for p in projects if p["id"].upper() == ref.upper()] or [p for p in projects if p["name"] == ref]
    if len(hits) != 1:
        sys.exit("Project %r not found or ambiguous. Visible projects:\n  %s"
                 % (ref, "\n  ".join("%s  %s" % (p["id"], p["name"]) for p in projects)))
    return hits[0]["id"], hits[0]["name"]


def read_recipients(conn: Connection, project_id: str, object_id: str):
    """GET /api/library/{id} for ONE project. Raw on purpose (see docstring).
    Returns ([{id, name, subtype}], None) or (None, error text). A
    never-published object returns 200 with [].

    High-level equivalent in current mstrio-py (group recipients arrive as
    User objects; check .subtype):
        with conn.temporary_project_change(project_id=project_id):
            [(r.id, r.name, r.subtype) for r in Dashboard(conn, id=object_id).recipients]
    """
    r = conn.get(endpoint="/api/library/%s" % object_id, headers={"X-MSTR-ProjectID": project_id})
    if r.status_code != 200:
        return None, "%s %s" % (r.status_code, r.text[:200])
    return r.json().get("recipients") or [], None


def object_exists(conn: Connection, project_id: str, object_id: str, obj_type: int):
    """True / False (404 ERR004 = no such object) / error text for anything else
    (403, 5xx, ERR001 "project not loaded"...), which is NOT the same as missing."""
    r = conn.get(endpoint="/api/objects/%s" % object_id, params={"type": obj_type},
                 headers={"X-MSTR-ProjectID": project_id})
    if r.status_code == 200:
        return True
    try:
        code = r.json().get("code")
    except ValueError:
        code = None
    return False if (r.status_code == 404 and code == "ERR004") else "%s %s" % (r.status_code, r.text[:150])


def cmd_export(conn: Connection, args, ms: types.SimpleNamespace) -> int:
    wanted_types = parse_types(args.types)
    project_id, project_name = resolve_project(conn, args.project)
    objects = []
    for t in wanted_types:
        kind, obj_type, lister_name = LISTERS[t]
        lister = getattr(ms, lister_name) if lister_name else list_agents_compat
        for o in lister(conn, project_id=project_id, to_dictionary=True):
            objects.append({"id": o["id"], "name": o["name"], "kind": kind, "type": obj_type,
                            "subtype": o.get("subtype")})
    print("Project %s (%s): %d objects to check" % (project_name, project_id, len(objects)), file=sys.stderr)

    rows, errors, by_recipient = [], [], collections.defaultdict(list)
    for i, o in enumerate(objects, 1):
        recips, err = read_recipients(conn, project_id, o["id"])
        if err:
            errors.append((o["id"], o["name"], err))       # record and carry on
            continue
        for r in recips:                                    # [] = never published
            rtype = RECIPIENT_TYPE.get(r.get("subtype"), "other:%s" % r.get("subtype"))
            rows.append({"document_id": o["id"], "document_name": o["name"], "document_kind": o["kind"],
                         "subtype": o["subtype"], "recipient_id": r["id"], "recipient_name": r.get("name", ""),
                         "recipient_type": rtype, "object_type": o["type"], "folder_path": "",
                         "source_project_id": project_id, "source_project_name": project_name})
            by_recipient[(rtype, r["id"], r.get("name", ""))].append(o)
        if i % 100 == 0:
            print("  %d/%d" % (i, len(objects)), file=sys.stderr)

    with private_open(args.out, newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        w.writeheader()
        w.writerows({k: csv_safe(v) for k, v in row.items()} for row in rows)

    print("published objects: %d, rows: %d (users %d, groups %d), read errors: %d -> %s"
          % (len({r["document_id"] for r in rows}), len(rows),
             sum(r["recipient_type"] == "user" for r in rows),
             sum(r["recipient_type"] == "group" for r in rows), len(errors), args.out))
    print("\nBy recipient (direct grants; group members are not expanded):")
    for (rtype, rid, rname), objs in sorted(by_recipient.items(), key=lambda kv: (kv[0][0] != "group", -len(kv[1]))):
        print("  %-5s %s  %s: %d" % (rtype, rid, rname, len(objs)))
        if args.by_recipient:
            for o in objs:
                print("        - [%s] %s (%s)" % (o["kind"], o["name"], o["id"]))
    for oid, name, err in errors:
        print("  READ ERROR %s (%s): %s" % (name, oid, err), file=sys.stderr)
    return 3 if errors else 0


def load_mapping(path: str):
    """CSV written by 'export' -> ({object id: {name, type, type_known, recipients}}, skipped lines)."""
    if not path.lower().endswith(".csv"):
        sys.exit("%s: pass the .csv written by 'export'" % path)
    wanted, skipped = collections.OrderedDict(), []
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if not {"document_id", "recipient_id"} <= set(reader.fieldnames or []):
            sys.exit("%s: needs at least the columns document_id and recipient_id" % path)
        for n, row in enumerate(reader, start=2):
            oid, rid = (row.get("document_id") or "").strip().upper(), (row.get("recipient_id") or "").strip().upper()
            if not (ID_RE.match(oid) and ID_RE.match(rid)):
                skipped.append(n)
                continue
            try:
                known = int(float(row.get("object_type") or 0)) or None
            except (ValueError, OverflowError):
                known = None
            known = known or KIND_OBJECT_TYPE.get((row.get("document_kind") or "").strip())
            for k in ("document_name", "recipient_name"):
                row[k] = csv_unsafe(row.get(k) or "")
            o = wanted.setdefault(oid, {"name": row["document_name"], "type": known or 55,
                                        "type_known": bool(known), "recipients": {}})
            o["recipients"][rid] = row
    return wanted, skipped


def cmd_replicate(conn: Connection, args) -> int:
    target_id, target_name = resolve_project(conn, args.target_project)
    wanted, skipped = load_mapping(args.mapping)
    print("%s -> %s (%s), %d objects" % ("APPLY" if args.apply else "DRY RUN", target_name, target_id, len(wanted)))
    if skipped:
        print("  WARNING: skipped %d mapping line(s) with an invalid id: %s"
              % (len(skipped), ", ".join(map(str, skipped[:20]))))

    counts, failures = collections.Counter(), 0
    hdr = {"X-MSTR-ProjectID": target_id}
    for oid, o in wanted.items():
        # does the same object id exist in the target project?
        found = object_exists(conn, target_id, oid, o["type"])
        if found is False and not o["type_known"]:            # trimmed mapping: maybe a report
            found = object_exists(conn, target_id, oid, 3)
            if found is True:
                o["type"] = 3
        if found is not True:
            counts["object_missing" if found is False else "lookup_error"] += 1
            print("  %s: %s (%s)%s" % ("MISSING in target" if found is False else "LOOKUP ERROR",
                                       o["name"], oid, "" if found is False else " " + found))
            continue
        current, err = read_recipients(conn, target_id, oid)
        if err:
            counts["read_error"] += 1
            print("  READ ERROR %s (%s): %s" % (o["name"], oid, err))
            continue
        have = {r["id"].upper() for r in current}
        missing = [rid for rid in o["recipients"] if rid not in have]
        counts["already_present"] += len(o["recipients"]) - len(missing)
        if not missing:
            continue
        label = ", ".join("%s %s" % (o["recipients"][r].get("recipient_type", ""), o["recipients"][r].get("recipient_name") or r)
                          for r in missing)
        if not args.apply:
            counts["to_add"] += len(missing)
            print("  would publish %s (%s) <- %s" % (o["name"], oid, label))
            continue
        # Raw POST (see docstring): groups stay groups, nothing is silently dropped.
        # POST is additive, so only the missing recipients are sent.
        body = {"id": oid, "recipients": [{"id": rid} for rid in missing]}
        if o["type"] == 3:
            body["type"] = "report_definition"
        resp = conn.post(endpoint="/api/library", headers=hdr, json=body)   # 204 No Content
        after, err = read_recipients(conn, target_id, oid)                   # verify
        after_ids = {r["id"].upper() for r in (after or [])}
        ok = not err and set(missing) <= after_ids and have <= after_ids
        counts["added_verified" if ok else "failed"] += len(missing)
        failures += 0 if ok else 1
        print("  %s %s (%s) <- %s%s" % ("published" if ok else "FAILED", o["name"], oid, label,
                                        "" if ok else " [POST %s %s]" % (resp.status_code, resp.text[:150])))
    print("summary: " + ", ".join("%s %d" % kv for kv in sorted(counts.items())))
    if failures:
        return 4
    return 3 if (counts["object_missing"] or counts["lookup_error"] or counts["read_error"] or skipped) else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="command", required=True)
    e = sub.add_parser("export", help="who has each dashboard/document (read-only)")
    e.add_argument("--project", required=True, help="source project ID or exact name")
    e.add_argument("--types", default="all", help="dashboards,documents,agents,reports or all (default all)")
    e.add_argument("--out", default="library_publications.csv")
    e.add_argument("--by-recipient", action="store_true", help="list every recipient's objects")
    r = sub.add_parser("replicate", help="publish missing grants in the target (dry run unless --apply)")
    r.add_argument("--mapping", required=True, help="the .csv written by export")
    r.add_argument("--target-project", required=True)
    r.add_argument("--apply", action="store_true")
    args = ap.parse_args(argv)
    if args.command == "export":
        parse_types(args.types)      # bad --types fails before mstrio is loaded or anyone signs in

    try:
        ms = load_mstrio()
    except ImportError as err:
        print("FATAL: needs mstrio-py >= %s (pip install -U mstrio-py): %s" % (MIN_MSTRIO, err),
              file=sys.stderr)
        return 2
    conn = connect(ms)
    try:
        return cmd_export(conn, args, ms) if args.command == "export" else cmd_replicate(conn, args)
    finally:
        conn.close()   # POST /api/auth/logout


if __name__ == "__main__":
    sys.exit(main())
