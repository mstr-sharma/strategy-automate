"""Regression tests for the 2026-10-05 audit fixes in build_mosaic.py."""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _hermetic  # noqa: E402,F401  (scrub MSTR_*/proxy env, private secret store)

import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(ROOT, "skills", "build-mosaic-model", "scripts"))

import build_mosaic as bm  # noqa: E402


class Resp:
    def __init__(self, status=200, body=None):
        self.status_code, self.ok = status, 200 <= status < 300
        self._body = body
        self.text = "" if body is None else "x"

    def json(self):
        return self._body


class FakeM:
    """Routes (verb, path-prefix) to canned responses and records calls."""

    def __init__(self, routes):
        self.routes, self.calls, self.verbose = routes, [], False
        self.s = mock.Mock(headers={})

    def _do(self, verb, path, **kw):
        self.calls.append((verb, path, kw))
        for (v, prefix), resp in self.routes.items():
            if v == verb and path.startswith(prefix):
                return resp(path, kw) if callable(resp) else resp
        return Resp(404, {})

    def get(self, path, **kw):
        return self._do("GET", path, **kw)

    def put(self, path, **kw):
        return self._do("PUT", path, **kw)

    def post(self, path, **kw):
        return self._do("POST", path, **kw)


class RightsMaskTests(unittest.TestCase):
    def test_names_follow_the_access_right_flags(self):
        self.assertEqual(bm._rights_mask("browse,read"), 1 | 4)
        self.assertEqual(bm._rights_mask("write"), 8)
        self.assertEqual(bm._rights_mask("view"), 197)
        self.assertEqual(bm._rights_mask("modify"), 221)
        self.assertEqual(bm._rights_mask("full"), 255)
        self.assertEqual(bm._rights_mask("6"), 6)

    def test_unknown_right_stops(self):
        with self.assertRaises(SystemExit), mock.patch("sys.stderr"):
            bm._rights_mask("inherit")


class MemberResolutionTests(unittest.TestCase):
    def resolve(self, users, groups=None, names=("Ann Lee",)):
        m = FakeM({("GET", "/api/users/"): Resp(404, {}),
                   ("GET", "/api/users"): Resp(200, users),
                   ("GET", "/api/searches/results"): Resp(200, {"result": []}),
                   ("GET", "/api/usergroups"): Resp(200, groups or [])})
        return bm._resolve_member_ids(m, list(names))

    def test_exact_unique_match_wins_over_substring_matches(self):
        users = [{"id": "A" * 32, "username": "joann", "fullName": "Joann Leeds"},
                 {"id": "B" * 32, "username": "alee", "fullName": "Ann Lee"}]
        self.assertEqual(self.resolve(users), ["B" * 32])

    def test_only_substring_matches_stop_the_run(self):
        users = [{"id": "A" * 32, "username": "joann", "fullName": "Joann Leeds"}]
        with self.assertRaises(SystemExit), mock.patch("sys.stderr"):
            self.resolve(users, names=("ann",))

    def test_ambiguous_exact_matches_stop_the_run(self):
        users = [{"id": "A" * 32, "username": "a1", "fullName": "Ann Lee"},
                 {"id": "B" * 32, "username": "a2", "fullName": "Ann Lee"}]
        with self.assertRaises(SystemExit), mock.patch("sys.stderr"):
            self.resolve(users)

    def test_group_by_exact_name_and_literal_ids(self):
        groups = [{"id": "C" * 32, "name": "Analysts"}, {"id": "D" * 32, "name": "Analysts EMEA"}]
        self.assertEqual(self.resolve([], groups, names=("Analysts",)), ["C" * 32])
        self.assertEqual(self.resolve([], names=("e" * 32,)), ["E" * 32])


class BatchIndexTests(unittest.TestCase):
    def test_results_keep_their_op_index(self):
        body = {"results": [{"status": 201, "response": {"information": {"objectId": "X1"}}},
                            {"status": 400, "error": "bad"},
                            {"status": 201, "response": {"information": {"objectId": "X3"}}}]}
        m = FakeM({("POST", "/api/model/batch"): Resp(207, body)})
        passed, failed = bm.batch_call(m, "M", "CS", [{"op": "create"}] * 3, atomic=False)
        self.assertEqual([r["_index"] for r in passed], [0, 2])
        self.assertEqual([r["_index"] for r in failed], [1])

    def test_rejected_atomic_batch_reports_every_op_failed(self):
        m = FakeM({("POST", "/api/model/batch"): Resp(400, {"code": "ERR"})})
        passed, failed = bm.batch_call(m, "M", "CS", [{"op": "create"}] * 2)
        self.assertEqual((passed, [f["_index"] for f in failed]), ([], [0, 1]))


class RelationshipMergeTests(unittest.TestCase):
    def test_failed_read_refuses_the_destructive_put(self):
        m = FakeM({("GET", "/api/model/dataModels/M/attributes/A"): Resp(500, {})})
        ok, *_rest, err = bm.put_relationships_merged(m, "M", "A", [{"parent": {"objectId": "P"}}], "CS")
        self.assertFalse(ok)
        self.assertIn("refusing", err)
        self.assertFalse(any(verb == "PUT" for verb, *_ in m.calls))

    def test_existing_relationships_are_kept(self):
        existing = {"relationships": [{"parent": {"objectId": "P0"}, "child": {"objectId": "A"}}]}
        m = FakeM({("GET", "/api/model/dataModels/M/attributes/A"): Resp(200, existing),
                   ("PUT", "/api/model/dataModels/M/attributes/A/relationships"): Resp(200, {})})
        new = [{"parent": {"objectId": "P1"}, "child": {"objectId": "A"}}]
        ok, added, total, _ = bm.put_relationships_merged(m, "M", "A", new, "CS")
        self.assertEqual((ok, added, total), (True, 1, 2))
        put_body = [kw["json"] for verb, path, kw in m.calls if verb == "PUT"][0]
        self.assertEqual(len(put_body["relationships"]), 2)


class ErdDirectionTests(unittest.TestCase):
    def parse(self, text):
        with tempfile.NamedTemporaryFile("w", suffix=".dbml", delete=False) as f:
            f.write(text)
        try:
            return bm.load_erd(f.name)
        finally:
            os.unlink(f.name)

    def test_dbml_operators(self):
        many_to_one = self.parse("Ref: posts.user_id > users.id")[0]
        one_to_many = self.parse("Ref: users.id < posts.user_id")[0]
        for rel in (many_to_one, one_to_many):
            self.assertEqual((rel["parent"], rel["child"]), ("users.id", "posts.user_id"))
        self.assertEqual(self.parse("Ref: a.x - b.y")[0]["type"], "one_to_one")


class TimeoutSessionTests(unittest.TestCase):
    def test_default_timeout_is_applied_and_overridable(self):
        seen = []
        with mock.patch("requests.Session.request", lambda self, method, url, **kw: seen.append(kw.get("timeout"))):
            s = bm._TimeoutSession()
            s.get("https://x.example/api")
            s.get("https://x.example/api", timeout=5)
        self.assertEqual(seen[0][0], 15)
        self.assertEqual(seen[1], 5)


if __name__ == "__main__":
    unittest.main()
