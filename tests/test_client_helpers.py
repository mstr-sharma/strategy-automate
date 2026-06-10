"""Tests for the shared helpers in skill/scripts/_client.py."""
from __future__ import annotations

import argparse
import json
import os
import sys
import unittest
from unittest import mock


ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(ROOT, "skill", "scripts"))

import _client  # noqa: E402
from _client import (  # noqa: E402
    BaseMSTR, add_auth_args, client_from_args, collect_named_values, collect_texts,
    dedupe_by_id, expression_kind, normalize_id, normalize_name, oid, oname, walk,
)


MSTR_ENV = {
    "MSTR_BASE": "https://env.example/MicroStrategyLibrary",
    "MSTR_USER": "envuser",
    "MSTR_PASSWORD": "envpw",
    "MSTR_LOGIN_MODE": "16",
    "MSTR_PROJECT_NAME": "Env Project",
    "MSTR_PROJECT_ID": "ENVPID",
}


class AccessorTests(unittest.TestCase):
    def test_oid_prefers_information_object_id(self):
        obj = {"information": {"objectId": "INFO1", "name": "Revenue"}, "id": "FLAT1"}
        self.assertEqual(oid(obj), "INFO1")

    def test_oid_falls_back_to_flat_fields(self):
        self.assertEqual(oid({"id": "A"}), "A")
        self.assertEqual(oid({"objectId": "B"}), "B")
        self.assertEqual(oid({"object_id": "C"}), "C")
        self.assertIsNone(oid({}))
        self.assertIsNone(oid(None))

    def test_oname_prefers_information_name(self):
        obj = {"information": {"name": "Info Name"}, "name": "Flat Name"}
        self.assertEqual(oname(obj), "Info Name")
        self.assertEqual(oname({"display": "D"}), "D")
        self.assertEqual(oname({"title": "T"}), "T")
        self.assertEqual(oname(None), "")

    def test_normalize_id_is_flat_only(self):
        obj = {"information": {"objectId": "INFO1"}, "id": "FLAT1"}
        self.assertEqual(normalize_id(obj), "FLAT1")
        self.assertIsNone(normalize_id({"information": {"objectId": "INFO1"}}))

    def test_normalize_name_accepts_username(self):
        self.assertEqual(normalize_name({"username": "u1"}), "u1")
        self.assertEqual(normalize_name({"name": "n", "username": "u1"}), "n")
        # mine's local oname() deliberately lacks the username fallback
        self.assertEqual(oname({"username": "u1"}), "")

    def test_dedupe_by_id(self):
        rows = [{"id": "A"}, {"id": "B"}, {"id": "A", "name": "dupe"}, {"name": "no id"}]
        self.assertEqual(dedupe_by_id(rows), [{"id": "A"}, {"id": "B"}])


class TreeHelperTests(unittest.TestCase):
    def test_walk_yields_every_dict_depth_first(self):
        payload = {"a": [{"b": {"c": 1}}, 2], "d": {"e": [{"f": 3}]}}
        seen = list(walk(payload))
        self.assertEqual(seen[0], payload)
        self.assertIn({"c": 1}, seen)
        self.assertIn({"f": 3}, seen)
        self.assertEqual(len(seen), 5)
        self.assertEqual(list(walk("scalar")), [])

    def test_collect_texts_unique_in_order_with_limit(self):
        payload = {"text": "t1", "kids": [{"text": "t2"}, {"text": "t1"}, {"text": ""}, {"text": "t3"}]}
        self.assertEqual(collect_texts(payload), ["t1", "t2", "t3"])
        self.assertEqual(collect_texts(payload, limit=2), ["t1", "t2"])

    def test_collect_named_values(self):
        payload = {"function": "sum", "args": [{"function": "avg"}, {"function": "sum"}, {"function": 7}]}
        self.assertEqual(collect_named_values(payload, "function"), ["sum", "avg"])
        self.assertEqual(collect_named_values(payload, "function", limit=1), ["sum"])
        self.assertEqual(collect_named_values(payload, "operator"), [])

    def test_expression_kind(self):
        self.assertEqual(expression_kind({"expression": {"tree": {"type": "predicate_filter"}}}),
                         "predicate_filter")
        self.assertEqual(expression_kind({"qualification": {"predicateTree": {"type": "elem"}}}), "elem")
        self.assertEqual(expression_kind({"definition": {"text": "Sum(x)"}}), "text")
        self.assertEqual(expression_kind({"unrelated": 1}), "")
        self.assertEqual(expression_kind(None), "")
        self.assertEqual(expression_kind([]), "")


class FakeResp:
    def __init__(self, payload):
        self._payload = payload
        self.text = json.dumps(payload)
        self.status_code = 200

    def json(self):
        return self._payload


class StubClient(BaseMSTR):
    """BaseMSTR whose request() pops canned pages and records call params."""

    def __init__(self, pages):
        super().__init__("https://x.example", "u", "p", 1, "proj")
        self.pages = list(pages)
        self.calls = []

    def request(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs.get("params")))
        return FakeResp(self.pages.pop(0))


class SearchResultsTests(unittest.TestCase):
    def test_paginates_until_short_page(self):
        pages = [
            {"result": [{"id": "a"}, {"id": "b"}]},
            {"result": [{"id": "c"}, {"id": "d"}]},
            {"result": []},
        ]
        m = StubClient(pages)
        rows = m.search_results(obj_type=4, limit=2)
        self.assertEqual([r["id"] for r in rows], ["a", "b", "c", "d"])
        self.assertEqual(len(m.calls), 3)
        self.assertEqual([c[1] for c in m.calls], ["/api/searches/results"] * 3)
        self.assertEqual([c[2]["offset"] for c in m.calls], [0, 2, 4])
        first = m.calls[0][2]
        self.assertEqual(first["name"], "")
        self.assertEqual(first["type"], 4)
        self.assertEqual(first["pattern"], 4)
        self.assertEqual(first["getAncestors"], "true")

    def test_single_page_mode_omits_offset_and_optional_type(self):
        m = StubClient([{"result": [{"id": "a"}]}])
        rows = m.search_results("Revenue", limit=50, paginate=False)
        self.assertEqual(rows, [{"id": "a"}])
        self.assertEqual(len(m.calls), 1)
        params = m.calls[0][2]
        self.assertNotIn("offset", params)
        self.assertNotIn("type", params)
        self.assertEqual(params["name"], "Revenue")

    def test_narrow_keys_skip_modeling_containers(self):
        payload = {"attributes": [{"id": "hidden"}]}
        m = StubClient([payload, payload])
        self.assertEqual(m.search_results(paginate=False, keys=_client.SEARCH_LIST_KEYS), [])
        self.assertEqual(m.search_results(paginate=False), [{"id": "hidden"}])


class AuthArgsTests(unittest.TestCase):
    def test_defaults_from_env(self):
        with mock.patch.dict(os.environ, MSTR_ENV, clear=False):
            parser = argparse.ArgumentParser()
            add_auth_args(parser, project_id=True)
            args = parser.parse_args([])
        self.assertEqual(args.base, MSTR_ENV["MSTR_BASE"])
        self.assertEqual(args.user, "envuser")
        self.assertEqual(args.password, "envpw")
        self.assertEqual(args.login_mode, 16)
        self.assertEqual(args.project_name, "Env Project")
        self.assertEqual(args.project_id, "ENVPID")

    def test_defaults_without_env(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            parser = argparse.ArgumentParser()
            add_auth_args(parser)
            args = parser.parse_args([])
        self.assertEqual(args.base, "")
        self.assertEqual(args.user, "")
        self.assertEqual(args.password, "")
        self.assertEqual(args.login_mode, 1)
        self.assertEqual(args.project_name, "")
        self.assertFalse(hasattr(args, "project_id"))

    def test_flags_override_env_and_toggles_drop_flags(self):
        with mock.patch.dict(os.environ, MSTR_ENV, clear=False):
            parser = argparse.ArgumentParser()
            add_auth_args(parser, password=False, login_mode=False,
                          help_text={"base": "custom help"})
            args = parser.parse_args(["--base", "https://cli.example"])
        self.assertEqual(args.base, "https://cli.example")
        self.assertFalse(hasattr(args, "password"))
        self.assertFalse(hasattr(args, "login_mode"))
        base_action = next(a for a in parser._actions if a.option_strings == ["--base"])
        self.assertEqual(base_action.help, "custom help")

    def test_client_from_args_skips_getpass_when_password_present(self):
        args = argparse.Namespace(base="https://x/", user="u", password="pw",
                                  login_mode=1, project_name="P")
        with mock.patch.object(_client.getpass, "getpass",
                               side_effect=AssertionError("should not prompt")):
            client = client_from_args(args)
        self.assertIsInstance(client, BaseMSTR)
        self.assertEqual(client.base, "https://x")
        self.assertEqual(client.password, "pw")
        self.assertEqual(client.project_name, "P")

    def test_client_from_args_prompts_when_password_missing(self):
        args = argparse.Namespace(base="https://x", user="u", password="",
                                  login_mode=1, project_name="P")
        with mock.patch.object(_client.getpass, "getpass", return_value="typed"):
            client = client_from_args(args)
        self.assertEqual(client.password, "typed")


if __name__ == "__main__":
    unittest.main()
