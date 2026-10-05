"""Run the repo's quality gates locally exactly as CI runs them.

    python3 tests/tools/check.py                 # all offline stages
    python3 tests/tools/check.py unit lint       # selected stages
    python3 tests/tools/check.py --online        # also the OSV dependency audit (network)
    python3 tests/tools/check.py --install ...   # CI: pip-install the pinned tools into this Python

Stages: unit (unittest, current interpreter), lint (ruff), types (mypy, platform core),
security (bandit, medium severity and up), coverage (branch coverage, gate on the platform
core), deps (OSV audit of uv.lock; needs --online or naming it).

Tools are pinned in TOOLS below — the single place to bump them. Without --install, tools run
through `uvx` (nothing is installed into your Python); mypy, bandit and coverage need
Python >= 3.10, which uvx fetches by itself.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TOOLS = {"ruff": "0.16.10", "mypy": "2.4.0", "types-requests": "2.33.0.20260906",
         "bandit": "1.9.4", "coverage": "7.16.2"}
TOOL_PYTHON = "3.13"            # interpreter uvx uses for the tools
CORE = "skills/strategy-platform/scripts"
TYPED_EXTRA = ("skills/create-unstructured-data/scripts/pptx_to_md.py",
               "skills/build-mosaic-model/scripts/mosaic_safety.py",
               "skills/build-mosaic-model/scripts/strategy_validate_models.py")
COVERAGE_FLOOR = 80            # % branch coverage of the platform core (CORE); raise, never lower
TOTAL_FLOOR = 45               # % branch coverage of everything under skills/ (2026-10-05: 49)
STAGES = ("unit", "lint", "types", "security", "coverage", "deps")
OFFLINE = STAGES[:-1]


def _tool(name: str, *args: str, install: bool, with_: tuple[str, ...] = ()) -> list[str]:
    """Command line for a pinned tool: `python -m tool` after --install, else uvx."""
    if install:
        return [sys.executable, "-m", name, *args]
    if not shutil.which("uvx"):
        raise SystemExit(f"{name}: uvx not found — install uv (https://docs.astral.sh/uv/) or rerun with --install")
    extra = [a for pkg in with_ for a in ("--with", pkg)]
    return ["uvx", "--python", TOOL_PYTHON, *extra, f"{name}@{TOOLS[name]}", *args]


def _install() -> None:
    pins = [f"{k}=={v}" for k, v in TOOLS.items()]
    subprocess.run([sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "-q", *pins],
                   check=True)


def commands(stage: str, install: bool, tmp: str) -> list[list[str]]:
    if stage == "unit":
        return [[sys.executable, "-m", "unittest", "discover", "-s", "tests"]]
    if stage == "lint":
        return [_tool("ruff", "check", ".", install=install)]
    if stage == "types":
        # (Python 3.9 syntax is checked by running the suite and every script's --help on 3.9 in CI;
        # current mypy can no longer target 3.9.)
        pkgs = (f"types-requests=={TOOLS['types-requests']}", "requests")
        files = sorted(os.path.join(CORE, f) for f in os.listdir(os.path.join(ROOT, CORE)) if f.endswith(".py"))
        return [_tool("mypy", "--ignore-missing-imports", "--follow-imports=silent",
                      "--no-error-summary", *files, *TYPED_EXTRA, install=install, with_=pkgs)]
    if stage == "security":
        return [_tool("bandit", "-q", "-r", "skills", "tests/tools", "-ll", install=install)]
    if stage == "coverage":
        os.environ["COVERAGE_FILE"] = os.path.join(tmp, ".coverage")   # keep data files out of the repo
        # branch coverage and the source tree come from [tool.coverage] in pyproject.toml
        run = _tool("coverage", "run", "-m", "unittest", "discover", "-s", "tests", "-q",
                    install=install, with_=("requests", "PyYAML"))
        report = _tool("coverage", "report", "--skip-covered", "--sort=cover", f"--fail-under={TOTAL_FLOOR}",
                       install=install)
        gate = _tool("coverage", "report", f"--include={CORE}/*", f"--fail-under={COVERAGE_FLOOR}",
                     install=install)
        return [run, report, gate]
    if stage == "deps":
        return [[sys.executable, os.path.join("tests", "tools", "osv_audit.py")]]
    raise SystemExit(f"unknown stage {stage!r}; choose from {', '.join(STAGES)}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("stages", nargs="*", help=f"any of: {', '.join(STAGES)} (default: all offline stages)")
    ap.add_argument("--online", action="store_true", help="include the OSV dependency audit")
    ap.add_argument("--install", action="store_true", help="pip-install the pinned tools into this Python")
    args = ap.parse_args(argv)
    stages = args.stages or list(OFFLINE) + (["deps"] if args.online else [])
    if args.install:
        _install()
    failed = []
    with tempfile.TemporaryDirectory(prefix="strategy-checks-") as tmp:
        for stage in stages:
            started = time.monotonic()
            print(f"\n=== {stage} ===", flush=True)
            ok = True
            for cmd in commands(stage, args.install, tmp):
                if subprocess.run(cmd, cwd=ROOT).returncode != 0:
                    ok = False
                    break
            print(f"--- {stage}: {'ok' if ok else 'FAILED'} ({time.monotonic() - started:.1f}s)", flush=True)
            if not ok:
                failed.append(stage)
    print("\nall checks passed" if not failed else f"\nfailed: {', '.join(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
