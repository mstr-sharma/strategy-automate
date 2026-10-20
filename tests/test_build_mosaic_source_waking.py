import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _hermetic  # noqa: E402,F401  (scrub MSTR_*/proxy env, private secret store)

# A serverless source database (Postgres that suspends when idle) answers Strategy's first table description with
# ERR001 "Database error connection" while it wakes. The build must retry that endpoint instead of stopping before the
# model is created; any other failure keeps the old behavior (next candidate, then stop).
import types  # noqa: E402
import unittest  # noqa: E402
from unittest import mock  # noqa: E402

from test_build_mosaic_round2 import Resp, bm, quiet  # noqa: E402

WAKING = {"code": "ERR001", "iServerCode": -2147216380, "message": "Database error connection. Please try again or contact your System Administrator."}


def fake(responses):
    seq = list(responses)
    m = types.SimpleNamespace(verbose=False, get=lambda path: seq.pop(0))
    return m


class SourceWakingTests(unittest.TestCase):
    def setUp(self):
        self.sleep = mock.patch.object(bm.time, "sleep", lambda s: None).start()
        self.addCleanup(mock.patch.stopall)
        self.kind = next(iter(bm.ENDPOINT_CANDIDATES))

    def run_candidates(self, responses, **kw):
        m = fake(responses)
        with quiet():
            return bm.MSTR.try_candidates(m, self.kind, **kw), m

    def test_a_waking_source_is_retried_until_it_answers(self):
        (path, body), _ = self.run_candidates([Resp(500, WAKING), Resp(500, WAKING), Resp(200, {"ok": 1})] + [Resp(404, {})] * 5)
        self.assertEqual(body, {"ok": 1})

    def test_a_source_that_never_wakes_still_stops_with_its_error(self):
        with self.assertRaises(SystemExit):
            self.run_candidates([Resp(500, WAKING)] * 4 * len(bm.ENDPOINT_CANDIDATES[self.kind]))

    def test_other_failures_are_not_retried(self):
        n = len(bm.ENDPOINT_CANDIDATES[self.kind])
        (path, body), m = self.run_candidates([Resp(404, {"code": "ERR004"})] * n, required=False)
        self.assertIsNone(body)

    def test_the_waking_signature(self):
        self.assertTrue(bm._source_waking(Resp(500, WAKING)))
        self.assertFalse(bm._source_waking(Resp(500, {"message": "other"})))
        self.assertFalse(bm._source_waking(Resp(400, WAKING)))


if __name__ == "__main__":
    unittest.main()
