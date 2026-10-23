import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _hermetic  # noqa: E402,F401  (scrub MSTR_*/proxy env, private secret store)

# Seen live on 2026-10-22: after a publish Strategy reported complete, the SQL endpoint lagged; the automatic second publish
# then failed at once because the model's table list answered 500 one time, and the build said it "did not complete
# within 1667 s". A passing 5xx is retried, and a refused publish is not called a timeout.
import os  # noqa: E402
import sys  # noqa: E402
import unittest  # noqa: E402
from unittest import mock  # noqa: E402

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "skills", "build-mosaic-model", "scripts"))
import build_mosaic as bm  # noqa: E402
import mosaic_apply as ma  # noqa: E402


class R:
    def __init__(self, status, body=None):
        self.status_code, self.ok, self._body, self.text = status, status < 400, body or {}, "{}"

    def json(self):
        return self._body


class ListRetryTests(unittest.TestCase):
    def test_a_passing_server_error_is_retried(self):
        answers = [R(500), R(200, {"tables": [{"information": {"objectId": "T1"}}], "total": 1})]
        m = mock.Mock(get=mock.Mock(side_effect=lambda *a, **k: answers.pop(0)))
        with mock.patch.object(bm.time, "sleep"):
            items, failed = bm._list_all(m, "/api/model/dataModels/X/tables", "tables")
        self.assertIsNone(failed)
        self.assertEqual(len(items), 1)

    def test_a_refusal_is_not_retried(self):
        m = mock.Mock(get=mock.Mock(return_value=R(403)))
        items, failed = bm._list_all(m, "/x", "tables")
        self.assertEqual((items, failed.status_code, m.get.call_count), ([], 403, 1))


class PublishErrorTests(unittest.TestCase):
    def test_a_refused_publish_says_so_and_a_timeout_says_timeout(self):
        with mock.patch.object(bm, "_publish", side_effect=SystemExit("_mosaic_publish_verified: list tables failed HTTP 500")):
            with self.assertRaises(ma.ApplyError) as e:
                ma.publish(None, "M", 1000)
        self.assertEqual(str(e.exception), "publish failed: _mosaic_publish_verified: list tables failed HTTP 500")
        with mock.patch.object(bm, "_publish", side_effect=SystemExit("publish did not complete within 1200 s")):
            with self.assertRaises(ma.ApplyError) as e:
                ma.publish(None, "M", 1000)
        self.assertIn("did not complete within 1200 s", str(e.exception))


if __name__ == "__main__":
    unittest.main()
