import argparse
import os
import sys
import unittest


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


if __name__ == "__main__":
    unittest.main()
