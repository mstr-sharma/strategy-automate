"""Every REST call written literally in the scripts must exist in the tenant spec with that verb.

The index (tests/fixtures/strategy_rest_operations.tsv) is generated from a live tenant's
OpenAPI spec with `strategy_api.py export-index`; regenerate it when the platform moves.
This is the check that would have caught `DELETE /api/auth/login` (not an operation; the
scripts never logged out for months).
"""
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
}

CALL = re.compile(r"""\.(get|post|put|patch|delete|head)\(\s*f?["'](?:\{[a-z_.]*base\})?(/api/[^"'?\s]*)""", re.I)
REQUEST = re.compile(r"""request\(\s*["'](GET|POST|PUT|PATCH|DELETE|HEAD)["']\s*,\s*f?["']"""
                     r"""(?:\{[a-z_.]*base\})?(/api/[^"'?\s]*)""")


def _template(path: str) -> re.Pattern:
    return re.compile("^" + re.sub(r"\\\{[^}]+\\\}", "[^/]+", re.escape(path)) + "$")


class RestContractTests(unittest.TestCase):
    def test_script_calls_exist_in_the_spec(self):
        ops = []
        for line in INDEX.read_text(encoding="utf-8").splitlines():
            if line.strip():
                verb, path = line.split("\t")[:2]
                ops.append((verb, _template(path)))
        problems = []
        for script in sorted((ROOT / "skills").rglob("*.py")):
            text = script.read_text(encoding="utf-8")
            for rx in (CALL, REQUEST):
                for m in rx.finditer(text):
                    verb, raw = m.group(1).upper(), m.group(2)
                    concrete = re.sub(r"\{[^}]*\}", "X", raw).rstrip("/")
                    if any(v == verb and t.match(concrete) for v, t in ops):
                        continue
                    if (script.name, verb, raw) in ALLOWED:
                        continue
                    line = text[:m.start()].count("\n") + 1
                    problems.append(f"{script.relative_to(ROOT)}:{line} {verb} {raw}")
        self.assertEqual(problems, [], "REST calls not in the spec index (fix them, or add to ALLOWED with a reason)")

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
