"""Offline tests for skills/build-mosaic-model/scripts/strategy_library_publications.py."""
from __future__ import annotations
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _hermetic  # noqa: E402,F401  (scrub MSTR_*/proxy env, private secret store)


import argparse
import contextlib
import csv
import io
import json
import os
import sys
import tempfile
import unittest


ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(ROOT, "skills", "build-mosaic-model", "scripts"))

import strategy_library_publications as lp  # noqa: E402


SRC, DST = "A" * 32, "B" * 32
DASH, REPORT, GONE = "D" * 32, "E" * 32, "F" * 32
USER, GROUP = "1" * 32, "2" * 32


class FakeResponse:
    def __init__(self, status, body=None):
        self.status_code = status
        self._body = body
        self.text = "" if body is None else json.dumps(body)
        self.headers = {}
        self.ok = status < 400

    def json(self):
        if self._body is None:
            raise ValueError("no body")
        return self._body


class FakeClient:
    """Target project DST holds DASH (published to USER) and REPORT (unpublished).
    POST /api/library behaves additively, like the live server."""

    base = "https://env.example/MicroStrategyLibrary"
    user_name = "tester"

    def __init__(self):
        self.calls = []
        self.recipients = {DASH: {USER}, REPORT: set()}

    def request(self, method, path, project_id=None, retry=None, **kw):
        self.calls.append((method, path, project_id, kw))
        params = kw.get("params") or {}
        if method == "DELETE":
            raise AssertionError("replicate must never DELETE")
        if path == "/api/projects":
            return FakeResponse(200, [{"id": SRC, "name": "Source"}, {"id": DST, "name": "Copy"}])
        if path.startswith("/api/objects/"):
            oid = path.rsplit("/", 1)[1]
            if params.get("type") == 34:
                return FakeResponse(200, {"id": oid, "name": "g" if oid == GROUP else "u",
                                          "subtype": 8705 if oid == GROUP else 8704})
            known = {DASH: 55, REPORT: 3}
            if known.get(oid) == params.get("type"):
                return FakeResponse(200, {"id": oid, "name": "obj-" + oid[0], "ancestors": []})
            return FakeResponse(404, {"code": "ERR004", "message": "not found"})
        if path.startswith("/api/library/") and method == "GET":
            oid = path.rsplit("/", 1)[1]
            if oid not in self.recipients:
                return FakeResponse(404, {"code": "ERR004"})
            return FakeResponse(200, {"id": oid, "recipients": [
                {"id": r, "name": "n", "subtype": 8705 if r == GROUP else 8704} for r in sorted(self.recipients[oid])]})
        if path == "/api/library" and method == "POST":
            body = kw["json"]
            self.recipients[body["id"]] |= {r["id"] for r in body["recipients"]}
            return FakeResponse(204)
        raise AssertionError("unexpected call %s %s" % (method, path))

    def get_json(self, path, project_id=None, **kw):
        return self.request("GET", path, project_id, **kw).json()


def write_mapping(path, rows, fields=None):
    fields = fields or lp.CSV_FIELDS
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


class ClassifyTests(unittest.TestCase):
    def test_dashboard_document_agent_report_cube(self):
        self.assertEqual(lp.classify({"type": 55, "subtype": 14081, "viewMedia": 0x60000000}), "dashboard")
        self.assertEqual(lp.classify({"type": 55, "subtype": 14081, "viewMedia": 0}), "document")
        self.assertEqual(lp.classify({"type": 55, "subtype": 14087}), "agent")
        self.assertEqual(lp.classify({"type": 3, "subtype": 768}), "report")
        self.assertIsNone(lp.classify({"type": 3, "subtype": 776}))       # cube
        self.assertIsNone(lp.classify({"type": 55, "subtype": 14082}))    # theme

    def test_parse_types_usage_error_exits_2(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as cm:
            lp.parse_types("dashboards,bogus")
        self.assertEqual(cm.exception.code, 2)
        self.assertEqual(lp.parse_types("all"), list(lp.TYPE_CHOICES))


class MappingTests(unittest.TestCase):
    def test_formula_names_round_trip_and_trimmed_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            full = os.path.join(tmp, "full.csv")
            lp.write_csv(full, lp.CSV_FIELDS, [
                {"document_id": DASH, "document_name": "=SUM(A1)", "document_kind": "dashboard",
                 "object_type": 55, "recipient_id": USER, "recipient_name": " padded ", "recipient_type": "user"}])
            with open(full, encoding="utf-8-sig") as f:
                self.assertIn("'=SUM(A1)", f.read())                     # escaped for Excel
            _src, objects, problems = lp.load_mapping(full)
            self.assertEqual(objects[DASH]["name"], "=SUM(A1)")           # unescaped on load
            self.assertEqual(objects[DASH]["recipients"][USER]["name"], " padded ")
            self.assertTrue(objects[DASH]["type_known"])
            self.assertEqual(problems, [])

            trimmed = os.path.join(tmp, "trimmed.csv")
            write_mapping(trimmed, [{"document_id": REPORT.lower(), "recipient_id": USER},
                                    {"document_id": "=cmd|1", "recipient_id": "X"}],
                          ["document_id", "recipient_id"])
            _src, objects, problems = lp.load_mapping(trimmed)
            self.assertFalse(objects[REPORT]["type_known"])               # replicate tries 55 then 3
            self.assertEqual(len(problems), 1)

    def test_escape_round_trip(self):
        for v in ("'=quoted", "'-- archive", "'Hello", "=SUM(1)", "+1", "@x", "plain"):
            self.assertEqual(lp._csv_unsafe(lp._csv_safe(v)), v)
        self.assertEqual(lp._int_or_none("55.0"), 55)
        self.assertIsNone(lp._int_or_none("inf"))

    def test_missing_columns_is_fatal(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = os.path.join(tmp, "bad.csv")
            write_mapping(bad, [{"name": "x"}], ["name"])
            with self.assertRaises(SystemExit):
                lp.load_mapping(bad)


class ReplicateTests(unittest.TestCase):
    def run_replicate(self, apply):
        client = FakeClient()
        with tempfile.TemporaryDirectory() as tmp:
            mapping = os.path.join(tmp, "m.csv")
            write_mapping(mapping, [
                {"document_id": DASH, "recipient_id": USER},     # already present in target
                {"document_id": DASH, "recipient_id": GROUP},    # missing -> added as a group
                {"document_id": REPORT, "recipient_id": USER},   # trimmed row: found as a report
                {"document_id": GONE, "recipient_id": USER},     # not in the target project
            ], ["document_id", "recipient_id"])
            args = argparse.Namespace(mapping=mapping, target_project="Copy", apply=apply,
                                      match_by_name=False, skip_recipient_check=False,
                                      report=os.path.join(tmp, "report.csv"))
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                rc = lp.cmd_replicate(args, client)
            with open(args.report, encoding="utf-8-sig") as f:
                rows = list(csv.DictReader(f))
        self.report_rows = rows
        statuses = sorted((r["document_id"][0], r["recipient_id"][0], r["status"]) for r in rows)
        return rc, client, statuses

    def test_dry_run_writes_nothing(self):
        rc, client, statuses = self.run_replicate(apply=False)
        self.assertFalse([c for c in client.calls if c[0] != "GET"])
        self.assertIn(("D", "2", "to_add"), statuses)
        self.assertIn(("D", "1", "already_present"), statuses)
        self.assertIn(("E", "1", "to_add"), statuses)
        self.assertIn(("F", "1", "object_missing"), statuses)
        self.assertEqual(rc, lp.EXIT_PARTIAL)
        # the trimmed mapping had no names/kinds: the report takes them from the target
        report_row = next(r for r in self.report_rows if r["document_id"] == REPORT)
        self.assertEqual((report_row["document_name"], report_row["document_kind"]), ("obj-E", "report"))

    def test_apply_posts_only_missing_with_target_header(self):
        rc, client, statuses = self.run_replicate(apply=True)
        posts = [c for c in client.calls if c[0] == "POST"]
        self.assertEqual(len(posts), 2)
        self.assertTrue(all(c[2] == DST for c in posts))
        by_id = {c[3]["json"]["id"]: c[3]["json"] for c in posts}
        self.assertEqual(by_id[DASH]["recipients"], [{"id": GROUP}])      # group sent as the group
        self.assertEqual(by_id[REPORT]["type"], "report_definition")
        self.assertEqual(client.recipients[DASH], {USER, GROUP})
        self.assertIn(("D", "2", "added_verified"), statuses)
        self.assertIn(("E", "1", "added_verified"), statuses)
        self.assertEqual(rc, lp.EXIT_PARTIAL)                              # GONE is unresolved


if __name__ == "__main__":
    unittest.main()
