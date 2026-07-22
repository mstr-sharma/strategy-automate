#!/usr/bin/env python3
"""Create a Strategy unstructured-data nugget from a local file, end to end.

Wraps POST /api/nuggets?type=unstructuredData (multipart/form-data) plus the
status poll (POST /api/nuggets/status/query). PowerPoint files are converted to
Markdown first via pptx_to_md.py, because the API only accepts:

    fileType 0=PDF  1=DOCX  3=MD  4=TXT  5=EMAIL

Usage (creds via the standard env vars MSTR_BASE / MSTR_USER / MSTR_PASSWORD /
MSTR_PROJECT_ID or MSTR_PROJECT_NAME / MSTR_DEST_FOLDER_ID):

    python3 create_unstructured.py DECK.pptx                 # convert + upload
    python3 create_unstructured.py notes.md --folder-id ID   # direct upload
    python3 create_unstructured.py report.pdf --no-poll

Prints a JSON result: {"ok": ..., "nuggetId": ..., "uploadedFile": ..., "status": [...]}.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_BUILD_SCRIPTS = os.path.normpath(os.path.join(_HERE, "..", "..", "build-mosaic-model", "scripts"))
for _p in (_HERE, _BUILD_SCRIPTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from _client import BaseMSTR, response_json  # noqa: E402
import pptx_to_md  # noqa: E402

# API fileType codes. 2 is unassigned/undocumented on observed tenants.
FILE_TYPES = {".pdf": "0", ".docx": "1", ".md": "3", ".markdown": "3",
              ".txt": "4", ".eml": "5"}
CONVERTIBLE = {".pptx", ".potx"}


def resolve_upload_file(path: str, *, include_notes: bool, title: str | None) -> str:
    ext = os.path.splitext(path)[1].lower()
    if ext in CONVERTIBLE:
        out = pptx_to_md.convert(path, include_notes=include_notes, doc_title=title)
        print(f"[convert] {path} -> {out}", file=sys.stderr)
        return out
    if ext not in FILE_TYPES:
        raise ValueError(f"unsupported extension '{ext}'. Accepted: "
                         f"{', '.join(sorted(FILE_TYPES))} (pptx/potx are auto-converted to md)")
    return path


def create_nugget(m: BaseMSTR, path: str, folder_id: str, *, name: str | None = None) -> str:
    ext = os.path.splitext(path)[1].lower()
    file_name = name or os.path.basename(path)
    with open(path, "rb") as fh:
        resp = m.request(
            "POST", "/api/nuggets", params={"type": "unstructuredData"},
            # None drops the session-level application/json so requests can set
            # the multipart boundary itself.
            headers={"Content-Type": None},
            data={"fileName": file_name,
                  "fileType": FILE_TYPES[ext],
                  "fileSize": str(os.path.getsize(path)),
                  "folderId": folder_id},
            files={"file": (file_name, fh)},
        )
    body = response_json(resp) or {}
    nugget_id = body.get("id") or body.get("nuggetId") or ""
    if not nugget_id:
        raise RuntimeError(f"upload accepted (HTTP {resp.status_code}) but no nugget id "
                           f"in response: {json.dumps(body)[:400]}")
    return nugget_id


def poll_status(m: BaseMSTR, nugget_id: str, *, timeout: int = 120,
                interval: int = 5) -> list[dict]:
    """Poll status/query until nuggetStatus stops changing twice in a row or timeout.

    Status semantics are tenant-version-specific, so the raw records are returned
    for the caller to report rather than mapped to guessed labels here."""
    observations: list[dict] = []
    deadline = time.monotonic() + timeout
    stable = 0
    while time.monotonic() < deadline:
        resp = m.try_request("POST", "/api/nuggets/status/query",
                             json={"nuggets": [{"id": nugget_id,
                                                "projectId": m.project_id}]})
        if resp is not None:
            body = response_json(resp)
            records = body if isinstance(body, list) else (body or {}).get("nuggets", body)
            observations.append({"t": round(time.monotonic() - deadline + timeout, 1),
                                 "response": records})
            if len(observations) >= 2 and observations[-1]["response"] == observations[-2]["response"]:
                stable += 1
                if stable >= 2:
                    break
            else:
                stable = 0
        time.sleep(interval)
    return observations


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("file", help="source file: pdf/docx/md/txt/eml, or pptx/potx (auto-converted)")
    ap.add_argument("--name", help="display file name for the nugget (default: basename)")
    ap.add_argument("--folder-id", default=os.environ.get("MSTR_DEST_FOLDER_ID", ""),
                    help="destination folder ID (default: MSTR_DEST_FOLDER_ID)")
    ap.add_argument("--notes", action="store_true", help="include PPT speaker notes in the conversion")
    ap.add_argument("--title", help="document title used when converting a deck")
    ap.add_argument("--no-poll", action="store_true", help="skip the status poll after upload")
    ap.add_argument("--poll-timeout", type=int, default=120)
    ap.add_argument("--base", default=os.environ.get("MSTR_BASE", ""))
    ap.add_argument("--user", default=os.environ.get("MSTR_USER", ""))
    ap.add_argument("--password", default=os.environ.get("MSTR_PASSWORD", ""))
    ap.add_argument("--project", default=os.environ.get("MSTR_PROJECT_ID")
                    or os.environ.get("MSTR_PROJECT_NAME", ""),
                    help="project ID or name (default: MSTR_PROJECT_ID / MSTR_PROJECT_NAME)")
    ap.add_argument("--login-mode", type=int, default=int(os.environ.get("MSTR_LOGIN_MODE", "1")))
    args = ap.parse_args()

    for flag, value in (("--base", args.base), ("--user", args.user),
                        ("--password", args.password), ("--project", args.project)):
        if not value:
            sys.exit(f"error: {flag} missing (set the MSTR_* env vars or pass flags)")
    if not args.folder_id:
        sys.exit("error: --folder-id missing (or set MSTR_DEST_FOLDER_ID)")
    if not os.path.isfile(args.file):
        sys.exit(f"error: no such file: {args.file}")

    upload_path = resolve_upload_file(args.file, include_notes=args.notes, title=args.title)

    m = BaseMSTR(args.base, args.user, args.password, args.login_mode, args.project)
    m.login()
    try:
        m.resolve_project()
        nugget_id = create_nugget(m, upload_path, args.folder_id, name=args.name)
        result = {"ok": True, "nuggetId": nugget_id,
                  "uploadedFile": upload_path, "folderId": args.folder_id}
        if not args.no_poll:
            result["status"] = poll_status(m, nugget_id, timeout=args.poll_timeout)
        print(json.dumps(result, indent=2))
    finally:
        m.logout()


if __name__ == "__main__":
    main()
