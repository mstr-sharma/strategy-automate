"""strategy_semantic_mine.py: seed resolution never guesses, and repeated lineage reads are
served once per run without changing the table scores."""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _hermetic  # noqa: E402,F401  (scrub MSTR_*/proxy env, private secret store)

import argparse
import collections
import json
import os
import stat
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "build-mosaic-model", "scripts"))

import strategy_semantic_mine as mine  # noqa: E402

REPORT_A, REPORT_B = "A" * 32, "B" * 32


class Resp:
    def __init__(self, body):
        self._body, self.status_code = body, 200
        self.text = json.dumps(body)

    def json(self):
        return self._body


class StubMSTR(mine.MSTR):
    """No network: canned search rows and lineage, every request counted."""

    def __init__(self, search_rows=None):
        super().__init__("https://tenant.invalid/MicroStrategyLibrary", "u", "p", 1, "P")
        self.project_id = "P" * 32
        self.search_rows = search_rows or {}
        self.searches, self.requests = [], collections.Counter()

    def search_results(self, name="", obj_type=None, *, pattern=4, limit=200, **kw):
        self.searches.append((name, obj_type, pattern))
        return list(self.search_rows.get((name, pattern), []))

    def try_request(self, method, path, **kw):
        params = kw.get("params") or {}
        self.requests[(method, path, params.get("usedByObject"), params.get("type"))] += 1
        if path == "/api/metadataSearches/results":
            by = params.get("usedByObject", "")
            if by.endswith(";3") and params.get("type") == 12:          # both reports use one attribute
                return Resp([{"id": "ATTR1", "name": "Customer", "type": 12}])
            if by == "ATTR1;12" and params.get("type") == 15:           # ...which lives on one table
                return Resp([{"id": "TBL1", "name": "CUSTOMER_DIM", "type": 15}])
            return Resp([])
        if path == "/api/model/attributes/ATTR1":
            return Resp({"forms": [{"expressions": [{"tables": [{"objectId": "TBL1", "subType": "logical_table",
                                                                  "name": "CUSTOMER_DIM"}]}]}]})
        return None


def row(oid, name, typ=3, folder="Reports"):
    return {"id": oid, "name": name, "type": typ, "ancestors": [{"name": "Public Objects"}, {"name": folder}]}


class SeedResolutionTests(unittest.TestCase):
    def test_unique_exact_match_uses_an_exact_search(self):
        m = StubMSTR({("Revenue by Region", 2): [row(REPORT_A, "Revenue by Region")]})
        seed = mine.resolve_seed(m, {"name": "Revenue by Region", "type": 3}, [3, 55])
        self.assertEqual(seed["id"], REPORT_A)
        self.assertEqual(m.searches, [("Revenue by Region", 3, mine.PATTERN_EXACTLY)])

    def test_case_variants_prefer_the_same_case(self):
        m = StubMSTR({("Revenue", 2): [row(REPORT_A, "REVENUE"), row(REPORT_B, "Revenue")]})
        self.assertEqual(mine.resolve_seed(m, {"name": "Revenue", "type": 3}, [3])["id"], REPORT_B)

    def test_duplicates_are_ambiguous_not_first_hit(self):
        m = StubMSTR({("Revenue", 2): [row(REPORT_A, "Revenue", folder="Sales"),
                                       row(REPORT_B, "Revenue", folder="Finance")]})
        with self.assertRaisesRegex(RuntimeError, r"ambiguous: 2 objects.*Finance.*ID;type"):
            mine.resolve_seed(m, {"name": "Revenue", "type": 3}, [3])

    def test_no_exact_match_suggests_similar_names(self):
        m = StubMSTR({("Revenue", 4): [row(REPORT_A, "Revenue 2024"), row(REPORT_B, "Net Revenue")]})
        with self.assertRaisesRegex(RuntimeError, r"no object named exactly 'Revenue'.*Net Revenue"):
            mine.resolve_seed(m, {"name": "Revenue", "type": 3}, [3])


class MemoTests(unittest.TestCase):
    def test_shared_components_are_read_once_and_still_scored_per_seed(self):
        m = StubMSTR()
        seeds = [mine.parse_seed(REPORT_A + ";3"), mine.parse_seed(REPORT_B + ";3")]
        state = mine.mine_top_down(m, seeds, argparse.Namespace(direct_only=False))
        self.assertEqual(m.requests[("POST", "/api/metadataSearches/results", "ATTR1;12", 15)], 1)
        self.assertEqual(m.requests[("GET", "/api/model/attributes/ATTR1", None, None)], 1)
        # Each seed still adds its evidence: 4 (lineage) + 3 (definition) per seed.
        self.assertEqual(state.table_scores["TBL1"], 14)
        self.assertEqual(len(state.table_reasons["TBL1"]), 4)

    def test_seeds_are_checked_before_anyone_signs_in(self):
        with mock.patch.object(mine, "client_from_args", side_effect=AssertionError("signed in")):
            with self.assertRaisesRegex(SystemExit, "at least one --seed"):
                mine.main(["--mode", "top-down"])


class OutputTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "posix", "file modes")
    def test_out_file_is_private_even_when_it_existed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "mine.json")
            with open(path, "w") as f:
                f.write("old")
            os.chmod(path, 0o644)
            with mine.private_open(path, encoding="utf-8") as f:
                f.write("{}\n")
            self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)


if __name__ == "__main__":
    unittest.main()
