"""Read-only smoke test against a real Strategy tenant — by hand, or from the live-smoke workflow.

    export MSTR_BASE=https://<tenant>.strategy.com/MicroStrategyLibrary
    export MSTR_API_TOKEN=...            # or MSTR_USER + MSTR_PASSWORD, or a cached SSO session
    python3 tests/live/smoke.py [--project "<name or id>"] [--json report.json]

Signs in once (strategy_auth `auto`), sends only GET requests besides sign-in and logout, and checks:
the tenant answers, sign-in works, the session is valid, projects are listed, every REST call the
scripts make exists in the live spec (drift against tests/fixtures is reported), a spec-validated
read through strategy_api.call, a search, discovery of both MCP servers, and that logout really
ends the session. One line per step with its timing. The output never carries a secret, the
tenant host or any object name, so it is safe in a CI log. Exit 0 when nothing failed.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.parse
from typing import Any, Callable

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "skills", "strategy-platform", "scripts"))
sys.path.insert(0, os.path.dirname(HERE))   # tests/, for the REST contract scanner

import strategy_api as api  # noqa: E402
import strategy_auth as sa  # noqa: E402
import strategy_mcp as mcp  # noqa: E402

FIXTURE = os.path.join(ROOT, "tests", "fixtures", "strategy_rest_operations.tsv")


class Smoke:
    def __init__(self, base: str, slow_ms: int):
        self.base, self.slow_ms = base, slow_ms
        self.host = urllib.parse.urlsplit(base).hostname or ""
        self.steps: list[dict] = []

    def _clean(self, text: str) -> str:
        text = str(text)
        if self.host:
            text = text.replace(self.host, "<tenant>")
        return re.sub(r"\b[0-9A-F]{32}\b", "<id>", text)[:300]

    def step(self, name: str, fn: Callable[[], str], *, required: bool = True) -> Any:
        started = time.monotonic()
        try:
            detail, status = fn(), "ok"
        except SkipStep as e:
            detail, status = str(e), "skip"
        except Exception as e:  # noqa: BLE001 — every failure becomes a report line
            detail, status = f"{type(e).__name__}: {e}", "FAIL" if required else "warn"
        ms = int((time.monotonic() - started) * 1000)
        slow = status == "ok" and ms > self.slow_ms
        row = {"step": name, "status": status, "ms": ms, "detail": self._clean(detail) + (" (slow)" if slow else "")}
        self.steps.append(row)
        print(f"{status:>4}  {name:<18} {ms:>6} ms  {row['detail']}", flush=True)
        return status == "ok"

    @property
    def failed(self) -> bool:
        return any(s["status"] == "FAIL" for s in self.steps)


class SkipStep(Exception):
    pass


def _spec_index(spec: dict) -> set[tuple[str, str]]:
    return {(o.verb, o.path) for o in api.operations(spec)}


def _fixture_index() -> set[tuple[str, str]]:
    out = set()
    with open(FIXTURE, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                verb, path = line.split("\t")[:2]
                out.add((verb, path))
    return out


def _contract_gaps(spec: dict) -> list[str]:
    """REST calls written in the scripts that the live spec does not have (same scan as the
    hermetic test_rest_contract, but against this tenant's own spec)."""
    import pathlib
    import test_rest_contract as contract
    templates = [(o.verb, contract._template(o.path)) for o in api.operations(spec)]
    gaps = []
    for script in sorted((pathlib.Path(ROOT) / "skills").rglob("*.py")):
        text = script.read_text(encoding="utf-8")
        for rx in (contract.CALL, contract.REQUEST):
            for m in rx.finditer(text):
                verb, raw = m.group(1).upper(), m.group(2)
                concrete = re.sub(r"\{[^}]*\}", "X", raw).rstrip("/")
                if (script.name, verb, raw) in contract.ALLOWED:
                    continue
                if not any(v == verb and t.match(concrete) for v, t in templates):
                    gaps.append(f"{verb} {raw}")
    return sorted(set(gaps))


def run(args: argparse.Namespace) -> Smoke:
    base = (os.environ.get("MSTR_BASE") or "").rstrip("/")
    smoke = Smoke(base, args.slow_ms)
    if not smoke.step("base url", lambda: sa.check_base(base) or "Library URL accepted"):
        return smoke
    session = sa.SafeSession()
    session.headers.update({"Accept": "application/json", "Content-Type": "application/json"})
    logins: list[int] = []
    session.hooks["response"].append(
        lambda r, *a, **k: logins.append(1) if r.request.method == "POST"
        and r.request.path_url.endswith("/api/auth/login") else None)
    state: dict[str, Any] = {}

    def reachable() -> str:
        r = session.get(f"{base}/api/config/authModes", timeout=30)
        r.raise_for_status()
        return f"{len((r.json() or {}).get('modes', []))} login modes enabled"

    def sign_in() -> str:
        state["signin"] = sa.sign_in(session, sa.AuthConfig.from_env(base=base))
        return f"method {state['signin'].method}"

    def valid_session() -> str:
        for path in ("/api/sessions", "/api/sessions/userInfo"):
            r = session.get(base + path, timeout=30)
            if r.status_code != 200:
                raise AssertionError(f"GET {path} -> {sa.describe(r)}")
        return "session and user info readable"

    def projects() -> str:
        r = session.get(f"{base}/api/projects", timeout=60)
        r.raise_for_status()
        listed = r.json()
        if not listed:
            raise AssertionError("no projects visible to this user")
        want = (args.project or "").lower()
        hit = next((p for p in listed if want and want in (str(p.get("id", "")).lower(),
                                                            str(p.get("name", "")).lower())), None)
        if want and not hit:
            raise AssertionError("the --project given is not visible to this user")
        state["project"] = (hit or {}).get("id")
        return f"{len(listed)} visible" + (", target found" if hit else "")

    def spec() -> str:
        r = session.get(f"{base}/api/openapi.json", params={"visibility": "all"}, timeout=120)
        r.raise_for_status()
        state["spec"] = r.json()
        live, fixture = _spec_index(state["spec"]), _fixture_index()
        return (f"{len(live)} operations; vs tests/fixtures: {len(fixture - live)} gone, "
                f"{len(live - fixture)} new" + (" — refresh with `strategy_api.py export-index`"
                                                 if fixture != live else ""))

    def contract() -> str:
        if args.no_contract:
            raise SkipStep("--no-contract")
        if "spec" not in state:
            raise SkipStep("no spec")
        gaps = _contract_gaps(state["spec"])
        if gaps:
            raise AssertionError(f"{len(gaps)} script calls missing from the live spec: {', '.join(gaps[:5])}")
        return "every REST call in the scripts exists in this tenant's spec"

    def api_read() -> str:
        if "spec" not in state:
            raise SkipStep("no spec")
        op = api.find_operation(state["spec"], "GET /api/projects")
        result = api.call(op, api.build_request(op, [], None, None), base=base, session=session)
        if not result["response"].ok:
            raise AssertionError(f"strategy_api.call -> {sa.describe(result['response'])}")
        return "spec-validated GET through strategy_api.call"

    def search() -> str:
        if not state.get("project"):
            raise SkipStep("no --project")
        r = session.get(f"{base}/api/searches/results", timeout=60, headers={"X-MSTR-ProjectID": state["project"]},
                        params={"pattern": 4, "type": 3, "limit": 5, "getAncestors": "false"})
        r.raise_for_status()
        return "quick search answered"

    def mcp_server(name: str) -> Callable[[], str]:
        def check() -> str:
            if args.no_mcp:
                raise SkipStep("--no-mcp")
            with sa.SafeSession() as anonymous:   # discovery is public; no REST token goes along
                meta = mcp.discover(anonymous, base=base, server=name)
            for key in ("authorization_endpoint", "token_endpoint"):
                if not meta.get(key):
                    raise AssertionError(f"metadata has no {key}")
            return "OAuth metadata found (resource, issuer, endpoints)"
        return check

    def logout() -> str:
        signin = state.get("signin")
        if signin is None:
            raise SkipStep("not signed in")
        if not signin.owns_session:
            raise SkipStep("shared/cached session left open on purpose")
        sa.sign_out(session, base, signin)
        r = session.get(f"{base}/api/sessions", timeout=30,
                        headers={"X-MSTR-AuthToken": state.get("token", "")})
        if r.status_code == 200:
            raise AssertionError("the session still answers after logout")
        return f"session ended (GET /api/sessions -> {r.status_code})"

    def hygiene() -> str:
        if len(logins) > 1:
            raise AssertionError(f"{len(logins)} sign-ins for one run")
        return f"{len(logins)} sign-in for the whole run"

    smoke.step("reachable", reachable)
    if smoke.step("sign in", sign_in):
        state["token"] = session.headers.get("X-MSTR-AuthToken", "")
        smoke.step("session", valid_session)
        smoke.step("projects", projects)
        smoke.step("spec", spec)
        smoke.step("contract", contract)
        smoke.step("api read", api_read)
        smoke.step("search", search)
    smoke.step("mcp mosaic", mcp_server("mosaic"))
    smoke.step("mcp agent", mcp_server("agent"), required=False)
    smoke.step("logout", logout)
    smoke.step("session hygiene", hygiene)
    session.close()
    return smoke


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--project", default=os.environ.get("MSTR_PROJECT_ID") or os.environ.get("MSTR_PROJECT_NAME", ""),
                    help="project name or id to search in (env MSTR_PROJECT_ID / MSTR_PROJECT_NAME)")
    ap.add_argument("--json", default="", help="also write the report to this file")
    ap.add_argument("--slow-ms", type=int, default=10000, help="mark steps slower than this")
    ap.add_argument("--no-mcp", action="store_true", help="skip MCP discovery")
    ap.add_argument("--no-contract", action="store_true", help="skip the script-calls-vs-live-spec check")
    args = ap.parse_args(argv)
    started = time.monotonic()
    smoke = run(args)
    total = int((time.monotonic() - started) * 1000)
    verdict = "FAILED" if smoke.failed else "passed"
    print(f"smoke {verdict} in {total} ms ({sum(s['status'] == 'ok' for s in smoke.steps)} ok, "
          f"{sum(s['status'] == 'skip' for s in smoke.steps)} skipped)")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump({"verdict": verdict, "total_ms": total, "steps": smoke.steps}, f, indent=2)
    return 1 if smoke.failed else 0


if __name__ == "__main__":
    sys.exit(main())
