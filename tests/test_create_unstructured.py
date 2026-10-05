"""create_unstructured.py end to end against the fake tenant: deck -> Markdown in a private temp
dir -> multipart upload -> status poll -> logout, leaving nothing beside the deck."""
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
import zipfile
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "skills", "create-unstructured-data", "scripts"))

from fake_tenant import FakeTenant  # noqa: E402

import create_unstructured as cu  # noqa: E402

A = "http://schemas.openxmlformats.org/drawingml/2006/main"
P = "http://schemas.openxmlformats.org/presentationml/2006/main"
SLIDE = (f'<p:sld xmlns:a="{A}" xmlns:p="{P}"><p:cSld><p:spTree>'
         f'<p:sp><p:txBody><a:p><a:r><a:t>Quarterly pipeline</a:t></a:r></a:p></p:txBody></p:sp>'
         f'</p:spTree></p:cSld></p:sld>').encode()


class CreateUnstructuredTests(unittest.TestCase):
    def setUp(self):
        self.tenant = FakeTenant()
        self.addCleanup(self.tenant.close)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = tmp.name
        self.decks = os.path.join(self.tmp, "decks")
        os.mkdir(self.decks)
        self.deck = os.path.join(self.decks, "deck.pptx")
        with zipfile.ZipFile(self.deck, "w") as z:
            z.writestr("ppt/slides/slide1.xml", SLIDE)
        self.uploads = []

        @self.tenant.route("POST", r"/api/nuggets")
        def upload(call, m):
            if self.tenant._user(call) is None:
                return 401, {"code": "ERR009", "message": "expired"}, {}
            self.uploads.append(call)
            return 201, {"id": "N1"}, {}

        @self.tenant.route("POST", r"/api/nuggets/status/query")
        def status(call, m):
            return 200, {"nuggets": [{"id": "N1", "nuggetStatus": 2}]}, {}

    def run_main(self, *extra, source=None):
        argv = [source or self.deck, "--base", self.tenant.base, "--user", "alice", "--password", "correct horse",
                "--auth-method", "password", "--project", "Tutorial", "--folder-id", "F" * 32, *extra]
        out = io.StringIO()
        with mock.patch.object(cu.time, "sleep"), contextlib.redirect_stdout(out), \
                contextlib.redirect_stderr(io.StringIO()):
            cu.main(argv)
        return json.loads(out.getvalue())

    def test_deck_is_converted_privately_uploaded_and_polled(self):
        result = self.run_main()
        self.assertEqual((result["nuggetId"], result["uploadedFile"], result["source"]), ("N1", "deck.md", self.deck))
        self.assertEqual(os.listdir(self.decks), ["deck.pptx"])           # no Markdown left beside the deck
        body = self.uploads[0].body
        for field, value in (("fileName", b"deck.md"), ("fileType", b"3"), ("folderId", b"F" * 32)):
            self.assertRegex(body, b'name="%s"\\r\\n\\r\\n%s\\r\\n' % (field.encode(), value))
        self.assertIn(b"Quarterly pipeline", body)
        self.assertEqual(self.uploads[0].query.get("type"), "unstructuredData")
        self.assertEqual(self.tenant.count("POST", r"/api/nuggets/status/query"), 3)   # stops after 2 stable reads
        self.assertEqual(self.tenant.open_sessions, 0)

    def test_markdown_can_be_kept_on_request_and_stays_private(self):
        keep = os.path.join(self.tmp, "kept.md")
        self.run_main("--save-markdown", keep, "--no-poll")
        with open(keep, encoding="utf-8") as f:
            self.assertIn("Quarterly pipeline", f.read())
        if os.name == "posix":
            self.assertEqual(stat.S_IMODE(os.stat(keep).st_mode), 0o600)
        self.assertEqual(self.tenant.count("POST", r"/api/nuggets/status/query"), 0)

    def test_an_upload_whose_status_never_answers_is_not_ok(self):
        out = io.StringIO()
        argv = [self.deck, "--base", self.tenant.base, "--user", "alice", "--password", "correct horse",
                "--auth-method", "password", "--project", "Tutorial", "--folder-id", "F" * 32]
        with mock.patch.object(cu, "poll_status", return_value=[]), contextlib.redirect_stdout(out), \
                contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as cm:
                cu.main(argv)
        self.assertEqual(cm.exception.code, 3)
        result = json.loads(out.getvalue())
        self.assertFalse(result["ok"])
        self.assertIn("no status reply", result["note"])
        self.assertEqual(self.tenant.open_sessions, 0)

    def test_a_bad_deck_is_a_clean_error_before_any_request(self):
        bad = os.path.join(self.decks, "bad.pptx")
        with open(bad, "w") as f:
            f.write("not a zip")
        with self.assertRaises(SystemExit) as cm:
            self.run_main(source=bad)
        self.assertIn("error:", str(cm.exception.code))
        self.assertEqual(self.tenant.calls, [])


if __name__ == "__main__":
    unittest.main()
