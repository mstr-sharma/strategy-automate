import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _hermetic  # noqa: E402,F401  (scrub MSTR_*/proxy env, private secret store)

import argparse
import contextlib
import io
import json
import os
import re
import sys
import unittest
from unittest import mock


ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(ROOT, "skills", "build-mosaic-model", "scripts"))

import strategy_validate as sv  # noqa: E402


def make_runner():
    return sv.Runner(m=None, args=argparse.Namespace(run_id="run-test"))


class CreatedInThisRunGatingTests(unittest.TestCase):
    """Regression: workflow 9 cleanup must only delete objects created in the
    current run. Pre-existing objects (reused security filter, reused duplicate
    user) are never appended to Runner.created, so created_in_this_run must
    return False for them — that bool is passed directly as delete_user /
    delete_filter to cleanup_security_workflow."""

    def test_preexisting_filter_is_not_enqueued_for_deletion(self):
        runner = make_runner()
        # find_security_filter returned an existing object: nothing was appended.
        self.assertFalse(runner.created_in_this_run(
            "securityFilter", object_id="PREEXISTING_SF", name=sv.VALIDATE_SF_NAME))

    def test_preexisting_user_is_not_enqueued_for_deletion(self):
        runner = make_runner()
        runner.created.append({"kind": "securityFilter", "id": "SF1", "name": sv.VALIDATE_SF_NAME})
        # Filter was created this run, but the duplicate user was found, not created.
        self.assertFalse(runner.created_in_this_run("user", object_id="PREEXISTING_USER"))

    def test_created_filter_is_deletable_by_id_or_name(self):
        runner = make_runner()
        runner.created.append({"kind": "securityFilter", "id": "SF1", "name": sv.VALIDATE_SF_NAME})
        self.assertTrue(runner.created_in_this_run("securityFilter", object_id="SF1"))
        self.assertTrue(runner.created_in_this_run("securityFilter", name=sv.VALIDATE_SF_NAME))

    def test_created_user_is_deletable_by_id_or_username(self):
        runner = make_runner()
        runner.created.append({"kind": "user", "id": "U1", "username": "validation_duplicate_user"})
        self.assertTrue(runner.created_in_this_run("user", object_id="U1"))
        self.assertTrue(runner.created_in_this_run("user", name="validation_duplicate_user"))

    def test_kind_mismatch_never_matches(self):
        runner = make_runner()
        runner.created.append({"kind": "user", "id": "X1", "username": "n"})
        self.assertFalse(runner.created_in_this_run("securityFilter", object_id="X1", name="n"))

    def test_no_identifiers_never_matches(self):
        # Guard against "delete by kind alone": with neither id nor name,
        # nothing may be considered created-in-this-run.
        runner = make_runner()
        runner.created.append({"kind": "user", "id": "U1", "username": "n"})
        self.assertFalse(runner.created_in_this_run("user"))
        self.assertFalse(runner.created_in_this_run("user", object_id=None, name=None))


class ExactElementTests(unittest.TestCase):
    """Workflow 9 writes a security filter on the resolved element, so only an exact, unique
    match may be used — never a substring hit or the first search result."""

    def test_exact_match_on_name_or_any_form_value(self):
        books = {"id": "h1", "formValues": ["1", "Books"]}
        self.assertIs(sv.exact_element([{"name": "eBooks"}, books], "books", "Category"), books)
        self.assertEqual(sv.exact_element([{"formValues": {"ID": "7", "DESC": "Books"}}], "Books", "C")["formValues"]["ID"], "7")
        self.assertEqual(sv.exact_element([{"name": " Books "}], "Books", "C")["name"], " Books ")

    def test_substring_missing_or_ambiguous_raise(self):
        with self.assertRaisesRegex(RuntimeError, "0 exact matches"):
            sv.exact_element([{"name": "eBooks"}, {"name": "Books & Media"}], "Books", "Category")
        with self.assertRaisesRegex(RuntimeError, "2 exact matches"):
            sv.exact_element([{"name": "Books", "id": "a"}, {"formValues": ["Books"], "id": "b"}], "Books", "Category")
        with self.assertRaisesRegex(RuntimeError, "0 exact matches"):
            sv.exact_element([], "Books", "Category")


class Resp:
    def __init__(self, status=200, body=None):
        self.status_code, self._body, self.headers = status, body, {}
        self.text = "" if body is None else json.dumps(body)

    def json(self):
        return self._body


class FakeM:
    """Just enough of strategy_validate.MSTR for workflow 9; records every call."""
    project_id = "P" * 32

    def __init__(self, elements, *, fail_add=False, existing_filter=None, existing_user=None):
        self.elements, self.fail_add = elements, fail_add
        self.existing_filter, self.existing_user = existing_filter, existing_user
        self.calls = []

    def search(self, name, obj_type=None, limit=20, pattern=4):
        self.calls.append(("SEARCH", name))
        return [{"id": "ATTR1", "name": sv.VALIDATE_ATTR, "type": 12, "ancestors": [{"name": "Schema Objects"}]}]

    def create_changeset(self):
        self.calls.append(("POST", "/api/model/changesets"))
        return "CS1"

    def commit_changeset(self, cs):
        self.calls.append(("POST", f"/api/model/changesets/{cs}/commit"))

    def delete_changeset(self, cs):
        self.calls.append(("DELETE", f"/api/model/changesets/{cs}"))

    def try_request(self, method, path, **kw):
        try:
            return self.request(method, path, **kw)
        except RuntimeError:
            return None

    def request(self, method, path, **kw):
        self.calls.append((method, path))
        params = kw.get("params") or {}
        if re.fullmatch(r"/api/attributes/\w+/elements", path):
            return Resp(200, {"elements": self.elements})
        if (method, path) == ("GET", "/api/users"):
            if params.get("nameBegins") == "validation_duplicate_user":
                return Resp(200, [self.existing_user] if self.existing_user else [])
            return Resp(200, [{"id": "U0", "username": "admin", "abbreviation": "admin"}])
        if (method, path) == ("POST", "/api/users"):
            return Resp(201, {"id": "U1", "username": "validation_duplicate_user"})
        if (method, path) == ("GET", "/api/securityFilters"):
            return Resp(200, {"securityFilters": [self.existing_filter] if self.existing_filter else []})
        if path.startswith("/api/folders/preDefined/"):
            return Resp(200, {"id": "F1"})
        if (method, path) == ("POST", "/api/model/securityFilters"):
            return Resp(201, {"id": "SF1"})
        if method == "GET" and path.endswith("/members"):
            return Resp(200, {"members": []})
        if method == "PATCH" and path.endswith("/members"):
            if self.fail_add and kw["json"]["operationList"][0]["op"] == "addElements":
                raise RuntimeError(f"PATCH {path} -> 500: injected")
            return Resp(204)
        if method in ("GET", "DELETE"):
            return Resp(204 if method == "DELETE" else 200, {} if method == "GET" else None)
        raise AssertionError(f"unexpected {method} {path}")


def workflow9(m):
    runner = sv.Runner(m, argparse.Namespace(run_id="run-test", yes=True, user="admin",
                                             keep_security_artifacts=False))
    with contextlib.redirect_stdout(io.StringIO()):
        runner.workflow_9()
    return runner


class Workflow9Tests(unittest.TestCase):
    BOOKS = [{"elementId": "h1;BOOKS", "name": "Books", "formValues": ["1", "Books"]}]

    def writes(self, m):
        return [c for c in m.calls if c[0] not in ("GET", "SEARCH")]

    def test_inexact_element_raises_before_any_write(self):
        m = FakeM([{"elementId": "h2", "name": "eBooks"}])
        with self.assertRaisesRegex(RuntimeError, "0 exact matches"):
            workflow9(m)
        self.assertEqual(self.writes(m), [])

    def test_failure_after_creating_cleans_up_this_runs_user_and_filter(self):
        m = FakeM(self.BOOKS, fail_add=True)
        with self.assertRaisesRegex(RuntimeError, "injected"):
            workflow9(m)
        self.assertIn(("DELETE", "/api/users/U1"), m.calls)
        self.assertIn(("DELETE", "/api/objects/SF1"), m.calls)

    def test_preexisting_filter_and_user_survive_a_failure(self):
        m = FakeM(self.BOOKS, fail_add=True,
                  existing_filter={"id": "SF0", "name": sv.VALIDATE_SF_NAME},
                  existing_user={"id": "U9", "username": "validation_duplicate_user"})
        with self.assertRaises(RuntimeError):
            workflow9(m)
        self.assertEqual([c for c in m.calls if c[0] == "DELETE"], [])
        self.assertNotIn(("POST", "/api/model/securityFilters"), m.calls)
        self.assertNotIn(("POST", "/api/users"), m.calls)

    def test_validate_attr_override_keeps_its_cached_attribute(self):
        with mock.patch.object(sv, "VALIDATE_ATTR", "Region"), mock.patch.object(sv, "VALIDATE_ELEMENT", "North"):
            m = FakeM([{"name": "North"}, {"name": "North East"}])
            runner = sv.Runner(m, argparse.Namespace(run_id="run-test"))
            runner.cache["category_attr"] = {"id": "R1", "name": "Region"}
            attr, element = runner.resolve_category_and_books()
        self.assertEqual((attr["id"], element["name"]), ("R1", "North"))
        self.assertNotIn("SEARCH", [c[0] for c in m.calls])          # was discarded for not being "Category"


if __name__ == "__main__":
    unittest.main()
