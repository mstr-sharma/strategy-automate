import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _hermetic  # noqa: E402,F401  (scrub MSTR_*/proxy env, private secret store)

import io
import json
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(ROOT, "skills", "strategy-platform", "scripts"))

from requests.structures import CaseInsensitiveDict  # noqa: E402

import strategy_api as api  # noqa: E402

PROJECT = "1" * 32
HEADER_TOKEN = {"name": "X-MSTR-AuthToken", "in": "header", "required": True, "schema": {"type": "string"}}
HEADER_PROJECT = {"name": "X-MSTR-ProjectID", "in": "header", "required": True, "schema": {"type": "string"}}
SPEC = {
    "info": {"version": "test"},
    "paths": {
        "/api/subscriptions": {
            "get": {"operationId": "listSubscriptions", "tags": ["Subscriptions"], "summary": "List subscriptions",
                    "parameters": [HEADER_TOKEN, HEADER_PROJECT,
                                   {"name": "limit", "in": "query", "schema": {"type": "integer"}},
                                   {"name": "type", "in": "query",
                                    "schema": {"type": "array", "items": {"enum": ["email", "cache"]}}}]},
            "post": {"operationId": "createSubscription", "tags": ["Subscriptions"], "summary": "Create",
                     "parameters": [HEADER_TOKEN, HEADER_PROJECT],
                     "requestBody": {"required": True, "content": {"application/json": {
                         "schema": {"$ref": "#/components/schemas/Sub"}}}}},
        },
        "/api/subscriptions/{id}": {
            "delete": {"operationId": "deleteSubscription", "tags": ["Subscriptions"],
                       "parameters": [HEADER_TOKEN, {"name": "id", "in": "path", "required": True,
                                                     "schema": {"type": "string"}},
                                      {"name": "Prefer", "in": "header", "required": True,
                                       "schema": {"type": "string"}}]},
        },
        "/api/model/dataModels/{dataModelId}/attributes": {
            "post": {"operationId": "createAttribute", "tags": ["Data Models"],
                     "parameters": [HEADER_TOKEN, {"name": "dataModelId", "in": "path", "required": True},
                                    {"name": "X-MSTR-MS-Changeset", "in": "header", "required": True}],
                     "requestBody": {"content": {"application/json": {"schema": {"type": "object"}}}}},
            "get": {"operationId": "getAttributes", "tags": ["Data Models"],
                    "parameters": [HEADER_TOKEN, {"name": "dataModelId", "in": "path", "required": True},
                                   {"name": "X-MSTR-MS-Changeset", "in": "header", "required": True}]},
        },
        "/api/a/settings": {"get": {"operationId": "getSettings", "tags": ["System Administration"]}},
        "/api/documents/{id}/pdf": {"post": {"operationId": "exportPdf", "tags": ["Reports"],
                                            "parameters": [{"name": "id", "in": "path", "required": True}],
                                            "responses": {"200": {"content": {"application/pdf": {}}}}}},
        "/api/packages/{id}/binary": {"put": {"operationId": "uploadPackageBinary", "tags": ["Packages"],
                                              "parameters": [{"name": "id", "in": "path", "required": True},
                                                             {"name": "Prefer", "in": "header", "required": True}],
                                              "requestBody": {"required": True, "content": {
                                                  "multipart/form-data": {"schema": {"type": "object"}}}}}},
        "/api/old/thing": {"get": {"operationId": "oldThing", "tags": ["Reports"],
                                   "x-microstrategy": {"visibility": "deprecated"}}},
        "/api/b/settings": {"get": {"operationId": "getSettings", "tags": ["Preferences"],
                                    "x-microstrategy": {"visibility": "internal"}}},
    },
    "components": {"schemas": {"Sub": {"type": "object", "required": ["name", "delivery"], "properties": {
        "name": {"type": "string"},
        "delivery": {"$ref": "#/components/schemas/Delivery"},
        "sendNow": {"type": "boolean"}}},
        "Delivery": {"type": "object", "required": ["mode"],
                     "properties": {"mode": {"type": "string", "enum": ["EMAIL", "HISTORY_LIST"]}}}}},
}


class Resp:
    def __init__(self, status=200, body=None, headers=None):
        self.status_code, self.ok = status, 200 <= status < 300
        self._body = {} if body is None else body
        self.headers = CaseInsensitiveDict(headers or {"Content-Type": "application/json"})
        self.content = json.dumps(self._body).encode()
        self.text = self.content.decode()

    def json(self):
        return self._body


class FakeSession:
    def __init__(self, status=200):
        self.calls, self.status = [], status

    def request(self, verb, url, **kw):
        self.calls.append((verb, url, kw))
        return Resp(self.status, {"ok": True})

    def post(self, url, **kw):
        self.calls.append(("POST", url, kw))
        if url.endswith("/api/model/changesets"):
            return Resp(201, {"id": "CS1"})
        return Resp(204)

    def delete(self, url, **kw):
        self.calls.append(("DELETE", url, kw))
        return Resp(204)


class LookupTests(unittest.TestCase):
    def test_by_id_by_verb_path_and_by_concrete_path(self):
        self.assertEqual(api.find_operation(SPEC, "createSubscription").key(), "POST /api/subscriptions")
        self.assertEqual(api.find_operation(SPEC, "delete /api/subscriptions/{id}").id, "deleteSubscription")
        self.assertEqual(api.find_operation(SPEC, "DELETE /api/subscriptions/ABC").id, "deleteSubscription")

    def test_duplicate_ids_need_verb_and_path(self):
        with self.assertRaisesRegex(api.ApiError, "ambiguous"):
            api.find_operation(SPEC, "getSettings")
        self.assertTrue(api.find_operation(SPEC, "GET /api/b/settings").internal)

    def test_unknown_operation_suggests(self):
        with self.assertRaisesRegex(api.ApiError, "similar: .*listSubscriptions"):
            api.find_operation(SPEC, "Subscriptions")

    def test_every_area_has_an_owning_skill(self):
        self.assertEqual(api.skill_for_tag("Subscriptions"), "strategy-distribution")
        self.assertEqual(api.skill_for_tag("Dashboards(Dossiers) and Documents"), "strategy-content")
        self.assertEqual(api.skill_for_tag("Baseline Test (Test Center)"), "strategy-validation")
        self.assertEqual(api.skill_for_tag("Something New"), "unassigned")


class ValidationTests(unittest.TestCase):
    def build(self, ref, pairs=(), body=None, project=PROJECT):
        return api.build_request(api.find_operation(SPEC, ref), list(pairs), body, project)

    def test_query_params_enums_and_repeats(self):
        req = self.build("listSubscriptions", ["limit=5", "type=email", "type=cache"])
        self.assertEqual(req["query"], {"limit": "5", "type": ["email", "cache"]})
        self.assertEqual(req["headers"]["X-MSTR-ProjectID"], PROJECT)
        with self.assertRaisesRegex(api.ApiError, "not one of"):
            self.build("listSubscriptions", ["type=pdf"])
        with self.assertRaisesRegex(api.ApiError, "unknown parameter 'limt'.*limit"):
            self.build("listSubscriptions", ["limt=5"])

    def test_project_required(self):
        with self.assertRaisesRegex(api.ApiError, "needs a project"):
            self.build("listSubscriptions", project=None)

    def test_path_params_are_required_and_quoted(self):
        with self.assertRaisesRegex(api.ApiError, "missing required path parameter 'id'"):
            self.build("deleteSubscription")
        self.assertEqual(self.build("deleteSubscription", ["id=a/b c"])["path"], "/api/subscriptions/a%2Fb%20c")

    def test_body_rules(self):
        with self.assertRaisesRegex(api.ApiError, "needs a request body"):
            self.build("createSubscription")
        with self.assertRaisesRegex(api.ApiError, "missing required field.*delivery"):
            self.build("createSubscription", body={"name": "x"})
        with self.assertRaisesRegex(api.ApiError, "takes no request body"):
            self.build("listSubscriptions", body={"x": 1})
        ok = self.build("createSubscription", body={"name": "x", "delivery": {"mode": "EMAIL"}})
        self.assertEqual(ok["json"]["name"], "x")

    def test_skeleton_follows_refs_and_marks_optional(self):
        op = api.find_operation(SPEC, "createSubscription")
        skel = api.body_skeleton(SPEC, op.body["schema"])
        self.assertEqual(skel["delivery"], {"mode": "EMAIL|HISTORY_LIST"})
        self.assertIn("sendNow?", skel)


class CallTests(unittest.TestCase):
    def test_write_opens_and_commits_a_changeset(self):
        op = api.find_operation(SPEC, "createAttribute")
        req = api.build_request(op, ["dataModelId=M1"], {"a": 1}, None)
        s = FakeSession()
        out = api.call(op, req, base="https://t.example/Lib", session=s)
        self.assertEqual(out["changeset"], "committed")
        sent = [c for c in s.calls if c[0] == "POST" and "/attributes" in c[1]][0]
        self.assertEqual(sent[2]["headers"]["X-MSTR-MS-Changeset"], "CS1")
        self.assertTrue(any(c[1].endswith("/changesets/CS1/commit") for c in s.calls))

    def test_failed_write_and_reads_discard(self):
        op = api.find_operation(SPEC, "createAttribute")
        s = FakeSession(status=400)
        out = api.call(op, api.build_request(op, ["dataModelId=M1"], {"a": 1}, None),
                       base="https://t.example/Lib", session=s)
        self.assertEqual(out["changeset"], "discarded")
        op = api.find_operation(SPEC, "getAttributes")
        s = FakeSession()
        self.assertEqual(api.call(op, api.build_request(op, ["dataModelId=M1"], None, None),
                                  base="https://t.example/Lib", session=s)["changeset"], "discarded")

    def test_binary_exports_ask_for_their_type_and_deprecations_show(self):
        op = api.find_operation(SPEC, "exportPdf")
        s = FakeSession()
        api.call(op, api.build_request(op, ["id=D1"], None, None), base="https://t.example/Lib", session=s)
        self.assertEqual(s.calls[0][2]["headers"]["Accept"], "application/pdf")
        self.assertTrue(api.find_operation(SPEC, "oldThing").deprecated)
        self.assertFalse(api.find_operation(SPEC, "oldThing").internal)

    def test_changeset_is_opened_in_the_project(self):
        op = api.find_operation(SPEC, "createAttribute")
        s = FakeSession()
        api.call(op, api.build_request(op, ["dataModelId=M1"], {"a": 1}, None), base="https://t.example/Lib",
                 session=s, project=PROJECT)
        opened = [c for c in s.calls if c[1].endswith("/api/model/changesets")][0]
        self.assertEqual(opened[2]["headers"]["X-MSTR-ProjectID"], PROJECT)

    def test_multipart_upload(self):
        import tempfile
        op = api.find_operation(SPEC, "uploadPackageBinary")
        with tempfile.NamedTemporaryFile(suffix=".mmp", delete=False) as f:
            f.write(b"PK")
        try:
            files, form = api._multipart(op, [f"file={f.name}"], [], None)
            req = api.build_request(op, ["id=P1"], None, None, multipart=True)
            s = FakeSession()
            api.call(op, req, base="https://t.example/Lib", session=s, files=files, form=form)
            sent = s.calls[0][2]
            self.assertIn("file", sent["files"])
            self.assertIsNone(sent["headers"]["Content-Type"])
            self.assertEqual(sent["headers"]["Prefer"], "respond-async")
            files["file"][1].close()
            with self.assertRaisesRegex(api.ApiError, "does not take a multipart"):
                api._multipart(api.find_operation(SPEC, "createSubscription"), [f"file={f.name}"], [], None)
        finally:
            os.unlink(f.name)

    def test_prefer_header_is_filled(self):
        op = api.find_operation(SPEC, "deleteSubscription")
        s = FakeSession()
        api.call(op, api.build_request(op, ["id=S1"], None, None), base="https://t.example/Lib", session=s)
        self.assertEqual(s.calls[0][2]["headers"]["Prefer"], "respond-async")


class CliTests(unittest.TestCase):
    def run_main(self, argv):
        buf = io.StringIO()
        with mock.patch.object(api, "load_spec", return_value=SPEC), mock.patch("sys.stdout", buf), \
             mock.patch.object(api.sa, "sign_in", side_effect=AssertionError("must not sign in")):
            code = api.main(["--base", "https://t.example/Lib"] + argv)
        return code, buf.getvalue()

    def test_writes_without_yes_are_printed_not_sent(self):
        code, out = self.run_main(["call", "deleteSubscription", "-p", "id=S1"])
        self.assertEqual(code, 0)
        plan = json.loads(out)
        self.assertTrue(plan["dry_run"])
        self.assertEqual(plan["headers"]["Prefer"], "respond-async")   # auto headers are shown
        code, out = self.run_main(["call", "createAttribute", "-p", "dataModelId=M1", "--body", "{}"])
        self.assertIn("opened", json.loads(out)["headers"]["X-MSTR-MS-Changeset"])

    def test_tags_and_ops(self):
        code, out = self.run_main(["tags"])
        self.assertEqual({r["tag"] for r in json.loads(out)},
                         {"Subscriptions", "Data Models", "System Administration", "Preferences", "Reports",
                          "Packages"})
        code, out = self.run_main(["ops", "--tag", "strategy-distribution"])
        self.assertEqual(len(json.loads(out)), 3)
        code, out = self.run_main(["ops", "--search", "settings"])
        self.assertEqual(len(json.loads(out)), 1)          # the internal duplicate is hidden by default


class SpecContractTests(unittest.TestCase):
    """Every area in the checked-in index of the real spec has an owning skill."""

    def test_index_areas_are_all_assigned(self):
        index = os.path.join(ROOT, "tests", "fixtures", "strategy_rest_operations.tsv")
        with open(index, encoding="utf-8") as f:
            areas = {line.split("\t")[2] for line in f if line.strip()}
        self.assertGreater(len(areas), 100)
        self.assertEqual(sorted(a for a in areas if api.skill_for_tag(a) == "unassigned"), [])


if __name__ == "__main__":
    unittest.main()
