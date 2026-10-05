"""Performance budgets: generous wall-clock limits that only a complexity regression would
break (a quadratic scan over ~1,700 operations, a lookup that re-parses the spec, ...).
Request-count budgets live in test_integration_fake_tenant.py."""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _hermetic  # noqa: E402,F401  (scrub MSTR_*/proxy env, private secret store)

import os
import sys
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "strategy-platform", "scripts"))

import strategy_api as api  # noqa: E402
import strategy_auth as sa  # noqa: E402

INDEX = os.path.join(ROOT, "tests", "fixtures", "strategy_rest_operations.tsv")


def spec_from_index() -> dict:
    """A spec with the real tenant's ~1,700 operations (from the CI fixture), each with a path
    parameter set and a small body, so lookups and validation see realistic sizes."""
    paths: dict = {}
    with open(INDEX, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            verb, path, tag, visibility, op_id = line.rstrip("\n").split("\t")
            params = [{"name": n, "in": "path", "required": True, "schema": {"type": "string"}}
                      for n in __import__("re").findall(r"\{([^}]+)\}", path)]
            op = {"operationId": op_id, "tags": [tag], "parameters": params, "summary": f"{verb} {path}",
                  "responses": {"200": {"description": "ok"}}}
            if visibility == "internal":
                op["x-microstrategy"] = {"visibility": "internal"}
            paths.setdefault(path, {})[verb.lower()] = op
    return {"openapi": "3.0.1", "paths": paths}


class Budget(unittest.TestCase):
    def assertFast(self, seconds, fn, *args):
        started = time.perf_counter()
        result = fn(*args)
        elapsed = time.perf_counter() - started
        self.assertLess(elapsed, seconds, f"{fn.__name__} took {elapsed:.2f}s (budget {seconds}s)")
        return result


class SpecBudgets(Budget):
    @classmethod
    def setUpClass(cls):
        cls.spec = spec_from_index()

    def test_indexing_the_whole_spec(self):
        ops = self.assertFast(1.0, api.operations, self.spec)
        self.assertGreater(len(ops), 1600)

    def test_lookups_validation_and_listings(self):
        ids = [o.id for o in api.operations(self.spec)][::40]

        def lookups():
            for ref in ids:
                op = api.find_operation(self.spec, ref)
                api.build_request(op, [f"{p['name']}=x" for p in op.params], None, None)
        self.assertFast(3.0, lookups)
        self.assertFast(1.0, api.cmd_tags, self.spec)
        self.assertFast(1.0, api.cmd_ops, self.spec, "", "user group", False, 200)


class ParserBudgets(Budget):
    def test_timestamp_parser_is_linear_on_hostile_input(self):
        self.assertFast(0.5, lambda: [sa._epoch("2026-10-06T01:00:00" + "0" * 50_000) for _ in range(20)])

    def test_redaction_handles_big_bodies(self):
        body = {"rows": [{"id": i, "name": f"n{i}", "apiToken": "t"} for i in range(50_000)]}
        clean, hidden = self.assertFast(2.0, api.redact_body, body)
        self.assertEqual(len(hidden), 50_000)


if __name__ == "__main__":
    unittest.main()
