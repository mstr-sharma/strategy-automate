"""Every REST call written literally in the scripts must exist in the tenant spec with that verb.

The index (tests/fixtures/strategy_rest_operations.tsv) is generated from a live tenant's
OpenAPI spec with `strategy_api.py export-index`; regenerate it when the platform moves.
This is the check that would have caught `DELETE /api/auth/login` (not an operation; the
scripts never logged out for months).
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _hermetic  # noqa: E402,F401  (scrub MSTR_*/proxy env, private secret store)

import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
INDEX = ROOT / "tests" / "fixtures" / "strategy_rest_operations.tsv"

# (script file name, VERB, path as written) -> why it is allowed to be absent from the index
ALLOWED = {
    ("build_mosaic.py", "POST", "/api/model/dataModels/{model_id}{path_suffix}"):
        "dynamic suffix (/metrics or /factMetrics) the scanner can't resolve",
    ("build_mosaic.py", "GET", "/api/model/dataModels/{model_id}/{collection}"):
        "dynamic collection (attributes / factMetrics)",
    ("build_mosaic.py", "GET", "/api/model/dataModels/{mid}/{ep}/{oid}"):
        "dynamic object kind",
    ("build_mosaic.py", "POST", "/api/model/dataModels/{args.model_id}/transformations"):
        "create-transformation is marked UNVERIFIED in its --help (spec: POST /api/model/transformations)",
    ("build_mosaic.py", "POST", "/api/model/batch"):
        "UI-internal, not in the spec; opt-in only (--use-batch), per-operation POSTs are the default",
    ("strategy_api.py", "GET", "/api/openapi.json"): "the spec document itself; it does not list its own URL",
    ("strategy_validate.py", "GET", "/api/openapi.yaml"): "the spec document itself; it does not list its own URL",
}

CALL = re.compile(r"""\.(get|post|put|patch|delete|head)\(\s*(?:[\w.]*base\s*\+\s*)?f?["'](?:\{[a-z_.]*base\})?(/api/[^"'?\s]*)""", re.I)
REQUEST = re.compile(r"""(?:request|_send|_request)\(\s*["'](GET|POST|PUT|PATCH|DELETE|HEAD)["']\s*,\s*"""
                     r"""(?:[\w.]*base\s*\+\s*)?f?["'](?:\{[a-z_.]*base\})?(/api/[^"'?\s]*)""")
GET_JSON = re.compile(r"""get_json\(\s*f?["'](/api/[^"'?\s]*)""")
PREFIX_VAR = re.compile(r"""^\s*(\w+)\s*=\s*f?["'](/api/[^"'?\s]*)["']\s*$""", re.M)
VIA_PREFIX = r"""\.(get|post|put|patch|delete|head)\(\s*f["']\{{({names})\}}(/[^"'?\s]*)"""
# The spec's catch-all proxies (/api/{path}, /api/{service}/{path}) match any short path; a
# call that only matches one of them is not a real operation (DELETE /api/auth/login did).
CATCH_ALL = re.compile(r"^/api(/\{[^}]+\})+$")


def _template(path: str) -> re.Pattern:
    return re.compile("^" + re.sub(r"\\\{[^}]+\\\}", "[^/]+", re.escape(path)) + "$")


def spec_ops(index: pathlib.Path = INDEX) -> list:
    ops = []
    for line in index.read_text(encoding="utf-8").splitlines():
        if line.strip():
            verb, path = line.split("\t")[:2]
            if not CATCH_ALL.match(path):
                ops.append((verb, _template(path)))
    return ops


def script_calls(text: str):
    """(verb, path as written, offset) for every literal REST call in a script's source."""
    for rx in (CALL, REQUEST):
        for m in rx.finditer(text):
            yield m.group(1).upper(), m.group(2), m.start()
    for m in GET_JSON.finditer(text):
        yield "GET", m.group(1), m.start()
    prefixes = dict(PREFIX_VAR.findall(text))
    if prefixes:
        rx = re.compile(VIA_PREFIX.format(names="|".join(map(re.escape, prefixes))), re.I)
        for m in rx.finditer(text):
            yield m.group(1).upper(), prefixes[m.group(2)] + m.group(3), m.start()


def matches(ops: list, verb: str, raw: str) -> bool:
    concrete = re.sub(r"\{[^}]*\}", "X", raw).rstrip("/")
    return any(v == verb and t.match(concrete) for v, t in ops)


class RestContractTests(unittest.TestCase):
    def test_script_calls_exist_in_the_spec(self):
        ops = spec_ops()
        problems = []
        for script in sorted((ROOT / "skills").rglob("*.py")):
            text = script.read_text(encoding="utf-8")
            for verb, raw, offset in script_calls(text):
                if matches(ops, verb, raw) or (script.name, verb, raw) in ALLOWED:
                    continue
                line = text[:offset].count("\n") + 1
                problems.append(f"{script.relative_to(ROOT)}:{line} {verb} {raw}")
        self.assertEqual(sorted(set(problems)), [],
                         "REST calls not in the spec index (fix them, or add to ALLOWED with a reason)")

    def test_the_matcher_rejects_what_it_exists_to_catch(self):
        ops = spec_ops()
        self.assertFalse(matches(ops, "DELETE", "/api/auth/login"))
        self.assertFalse(matches(ops, "GET", "/api/totally/bogus"))
        self.assertTrue(matches(ops, "POST", "/api/auth/logout"))
        self.assertTrue(matches(ops, "GET", "/api/model/dataModels/{model_id}/attributes"))

    def test_the_scanner_sees_every_call_style(self):
        text = """
            self.session.post(self.base + "/api/auth/logout", timeout=30)
            r = self._send("POST", "/api/auth/login", json=body)
            projects = client.get_json("/api/projects")
            mp = f"/api/model/dataModels/{args.model_id}"
            r = m.get(f"{mp}/factMetrics")
            r = m.s.get(f"{m.base}/api/sessions")
        """
        found = {(v, p) for v, p, _ in script_calls(text)}
        self.assertEqual(found, {("POST", "/api/auth/logout"), ("POST", "/api/auth/login"), ("GET", "/api/projects"),
                                 ("GET", "/api/model/dataModels/{args.model_id}/factMetrics"),
                                 ("GET", "/api/sessions")})

    def test_allowlist_entries_still_exist(self):
        """Drop an ALLOWED entry once the code no longer makes that call."""
        stale = []
        for name, verb, raw in ALLOWED:
            hits = [p for p in (ROOT / "skills").rglob(name) if raw in p.read_text(encoding="utf-8")]
            if not hits:
                stale.append((name, verb, raw))
        self.assertEqual(stale, [])


if __name__ == "__main__":
    unittest.main()
