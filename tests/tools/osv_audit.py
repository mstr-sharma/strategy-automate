"""Check every package pinned in uv.lock against the OSV vulnerability database.

    python3 tests/tools/osv_audit.py     # exit 1 on an advisory that is not reviewed below, 2 if OSV is unreachable

Stdlib only (no pip-audit needed). CI runs it weekly and whenever uv.lock or pyproject.toml
changes (.github/workflows/security.yml). Accepted advisories are listed in ACCEPTED with the
reason they cannot hurt this repo and the condition that retires them; a new advisory against
an accepted pin still fails, so every acceptance is a deliberate, dated review.
"""
from __future__ import annotations

import json
import pathlib
import re
import sys
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[2]
OSV = "https://api.osv.dev/v1"   # fixed https endpoint (the nosec B310 below)

# Python 3.9 forks of the lock: requests 2.32.5 and urllib3 2.6.3 are the newest releases that
# still install on 3.9 (later ones need 3.10). Retire all of these when requires-python >= 3.10.
_PY39 = ("Python 3.9-only pin; the fix needs Python >= 3.10. Reviewed 2026-10-05: ")
ACCEPTED: dict[tuple[str, str], dict[str, str]] = {
    ("requests", "2.32.5"): {
        "GHSA-gc5v-m9x4-r6x2": _PY39 + "temp-file reuse in extract_zipped_paths, reached only when the CA "
                               "bundle is read from inside a zip archive; these scripts never do that.",
        "PYSEC-2026-2275": "alias of GHSA-gc5v-m9x4-r6x2",
    },
    ("urllib3", "2.6.3"): {
        "GHSA-qccp-gfcp-xxvc": _PY39 + "headers forwarded on urllib3-level redirects through a proxy; requests "
                               "turns urllib3 redirects off and follows them itself, and SafeSession strips "
                               "Strategy tokens on any cross-origin hop.",
        "PYSEC-2026-141": "alias of GHSA-qccp-gfcp-xxvc",
        "GHSA-mf9v-mfxr-j63j": _PY39 + "decompression-bomb limits bypassed in the streaming API; needs a hostile "
                               "server, and the scripts only talk to the operator's own tenant.",
        "PYSEC-2026-142": "alias of GHSA-mf9v-mfxr-j63j",
        "GHSA-8988-9cw3-xx77": _PY39 + "TLS settings of an https:// proxy can be ignored; only matters when "
                               "HTTPS_PROXY points at an https proxy.",
        "PYSEC-2026-4175": "alias of GHSA-8988-9cw3-xx77",
        "GHSA-gh4c-6fx4-qh6g": _PY39 + "infinite loop on hostile chunked deflate streams (denial of service by "
                               "the server itself).",
        "PYSEC-2026-4176": "alias of GHSA-gh4c-6fx4-qh6g",
        "GHSA-vxq7-64xx-v4gw": _PY39 + "unbounded chunk-size line buffered in memory (denial of service by the "
                               "server itself).",
        "PYSEC-2026-4177": "alias of GHSA-vxq7-64xx-v4gw",
    },
}


def locked_packages(lock_text: str) -> list[tuple[str, str]]:
    """(name, version) for every registry package in uv.lock, including each Python-version fork."""
    out = set()
    for block in lock_text.split("[[package]]")[1:]:
        head = block.split("\n[", 1)[0]
        name = re.search(r'^name = "([^"]+)"', head, re.M)
        version = re.search(r'^version = "([^"]+)"', head, re.M)
        if name and version and "registry" in head:
            out.add((name.group(1).lower(), version.group(1)))
    return sorted(out)


def _post(url: str, payload: dict) -> dict:
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:  # nosec B310
        return json.load(r)


def _summary(vuln_id: str) -> str:
    try:
        with urllib.request.urlopen(f"{OSV}/vulns/{vuln_id}", timeout=30) as r:  # nosec B310
            data = json.load(r)
    except (OSError, ValueError):
        return ""
    fixed = sorted({e["fixed"] for a in data.get("affected", []) for rng in a.get("ranges", [])
                    for e in rng.get("events", []) if "fixed" in e})
    return f"{data.get('summary', '')} (fixed in {', '.join(fixed) or 'n/a'})"


def audit(packages: list[tuple[str, str]]) -> tuple[list[str], list[str], list[str]]:
    """Returns (unreviewed findings, accepted findings, stale acceptances)."""
    results = _post(f"{OSV}/querybatch", {"queries": [
        {"package": {"name": n, "ecosystem": "PyPI"}, "version": v} for n, v in packages]})["results"]
    findings, accepted, used = [], [], set()
    for (name, version), res in zip(packages, results):
        for vuln in res.get("vulns") or []:
            vid = vuln["id"]
            if vid in ACCEPTED.get((name, version), {}):
                accepted.append(f"{name} {version}: {vid}")
                used.add((name, version, vid))
            else:
                findings.append(f"{name} {version}: {vid} {_summary(vid)}".rstrip())
    stale = [f"{n} {v}: {vid}" for (n, v), ids in ACCEPTED.items() for vid in ids
             if (n, v, vid) not in used]
    return findings, accepted, stale


def main() -> int:
    packages = locked_packages((ROOT / "uv.lock").read_text(encoding="utf-8"))
    try:
        findings, accepted, stale = audit(packages)
    except (OSError, ValueError, KeyError) as err:
        print(f"could not query OSV: {err}", file=sys.stderr)
        return 2
    print(f"checked {len(packages)} locked packages against OSV")
    for line in accepted:
        print(f"  accepted    {line}")
    for line in stale:
        print(f"  stale entry {line} (no longer reported - remove it from ACCEPTED)")
    for line in findings:
        print(f"  VULNERABLE  {line}")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
