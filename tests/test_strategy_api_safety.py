"""strategy_api safety rails from the round-2 adversarial review: dot-segment path values,
secret-bearing response and dry-run bodies, self-referential schemas, honest `describe`."""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _hermetic  # noqa: E402,F401  (scrub MSTR_*/proxy env, private secret store)

import contextlib
import io
import json
import os
import stat
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "skills", "strategy-platform", "scripts"))

import strategy_api as api  # noqa: E402
from fake_tenant import FakeTenant  # noqa: E402

SPEC = {
    "openapi": "3.0.1",
    "paths": {
        "/api/explorer/chats/{chatId}": {"delete": {
            "operationId": "deleteChat", "tags": ["Explorer"],
            "parameters": [{"name": "chatId", "in": "path", "required": True, "schema": {"type": "string"}}],
            "responses": {"204": {"description": "deleted"}}}},
        "/api/loops": {"post": {
            "operationId": "createLoop", "tags": ["Misc"],
            "parameters": [{"name": "Prefer", "in": "header", "required": False, "schema": {"type": "string"}}],
            "requestBody": {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/A"}}}},
            "responses": {"200": {"description": "ok"}}}},
        "/api/either": {"post": {
            "operationId": "createEither", "tags": ["Misc"],
            "requestBody": {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/B"}}}},
            "responses": {"200": {"description": "ok"}}}},
    },
    "components": {"schemas": {
        "A": {"allOf": [{"$ref": "#/components/schemas/A"}, {"properties": {"name": {"type": "string"}}}]},
        "B": {"oneOf": [{"$ref": "#/components/schemas/B"}]},
    }},
}


class PathParameterTests(unittest.TestCase):
    def test_empty_and_dot_segments_are_refused(self):
        op = api.find_operation(SPEC, "deleteChat")
        for value in ("", ".", ".."):
            with self.assertRaisesRegex(api.ApiError, "cannot be"):
                api.build_request(op, [f"chatId={value}"], None, None)

    def test_slashes_are_encoded_so_the_path_keeps_its_shape(self):
        op = api.find_operation(SPEC, "deleteChat")
        req = api.build_request(op, ["chatId=../../users/1"], None, None)
        self.assertEqual(req["path"], "/api/explorer/chats/..%2F..%2Fusers%2F1")
        self.assertTrue(api._template_matches(op.path, req["path"]))


class RecursiveSchemaTests(unittest.TestCase):
    def test_describe_survives_self_referential_all_of_and_one_of(self):
        for name in ("createLoop", "createEither"):
            out = api.cmd_describe(api.find_operation(SPEC, name))
            self.assertIn("skeleton", out["body"])

    def test_optional_prefer_is_not_claimed_as_auto_filled(self):
        out = api.cmd_describe(api.find_operation(SPEC, "createLoop"))
        self.assertEqual(out["filled_in_by_call"], [])
        self.assertIn("Prefer", [p["name"] for p in out["parameters"]])


class RedactionTests(unittest.TestCase):
    def test_redact_body_hides_secret_fields_at_any_depth(self):
        data = {"apiToken": "t-1", "expireTime": "2099", "user": {"password": "pw", "name": "n"},
                "iams": [{"clientSecret": "cs", "clientId": "id"}], "tokenType": "Bearer", "count": 3}
        clean, hidden = api.redact_body(data)
        self.assertEqual(sorted(hidden), ["apiToken", "iams[0].clientSecret", "user.password"])
        self.assertNotIn("t-1", json.dumps(clean))
        self.assertEqual(clean["tokenType"], "Bearer")       # not a secret, kept
        self.assertEqual(clean["iams"][0]["clientId"], "id")
        self.assertEqual(data["apiToken"], "t-1")            # the original is untouched


class CliRedactionTests(unittest.TestCase):
    def setUp(self):
        self.tenant = FakeTenant()
        self.addCleanup(self.tenant.close)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        env = {k: v for k, v in os.environ.items() if not k.startswith("MSTR_")}
        env.update({"MSTR_BASE": self.tenant.base, "MSTR_SECRET_STORE": "file", "XDG_CONFIG_HOME": tmp.name,
                    "XDG_CACHE_HOME": tmp.name, "MSTR_USER": "alice", "MSTR_PASSWORD": "correct horse",
                    "TMPDIR": tmp.name})
        patcher = mock.patch.dict(os.environ, env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        tempfile.tempdir = None
        self.addCleanup(setattr, tempfile, "tempdir", None)
        self.tenant.spec["paths"]["/api/auth/apiTokens"] = {"post": {
            "operationId": "createApiToken", "tags": ["Authentication"],
            "requestBody": {"content": {"application/json": {"schema": {"type": "object"}}}},
            "responses": {"201": {"description": "ok", "content": {"application/json": {}}}}}}
        self.tenant.spec["paths"]["/api/users"] = {"post": {
            "operationId": "createUser", "tags": ["User Management"],
            "requestBody": {"required": True, "content": {"application/json": {"schema": {"type": "object"}}}},
            "responses": {"201": {"description": "ok"}}}}

    def run_api(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = api.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_new_api_token_is_kept_privately_not_printed(self):
        self.run_api("sync")
        code, out, err = self.run_api("call", "createApiToken", "--body", "{}", "--yes")
        self.assertEqual(code, 0, err)
        token = next(t for t, u in self.tenant.state.api_tokens.items() if t != "api-token-alice")
        self.assertNotIn(token, out + err)
        result = json.loads(out)
        self.assertEqual(result["secret_fields_redacted"], ["apiToken"])
        path = result["full_body_written_to"]
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
        with open(path, encoding="utf-8") as f:
            self.assertEqual(json.load(f)["apiToken"], token)

    def test_dry_run_does_not_echo_a_password_from_the_body(self):
        self.run_api("sync")
        code, out, _ = self.run_api("call", "createUser", "--body",
                                    '{"username": "bob", "password": "fake-S3cret-pass!"}')
        self.assertEqual(code, 0)
        self.assertNotIn("fake-S3cret-pass!", out)
        self.assertEqual(json.loads(out)["body"]["password"], "<redacted>")


if __name__ == "__main__":
    unittest.main()
