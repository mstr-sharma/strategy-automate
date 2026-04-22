import os
import sys
import unittest


ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(ROOT, "skill", "scripts"))

import strategy_validate_models as svm  # noqa: E402


class StrategyValidateModelsTests(unittest.TestCase):
    def test_compare_rows_reports_ok_with_tolerance(self):
        model = [{"region": "A", "revenue": "100.0000001"}]
        reference = [{"region": "A", "revenue": "100.0"}]

        result = svm.compare_rows(model, reference, ["region"], ["revenue"], 1e-6, "q")

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["matched_rows"], 1)

    def test_compare_rows_reports_missing_and_delta_rows(self):
        model = [{"region": "A", "revenue": "90"}, {"region": "B", "revenue": "5"}]
        reference = [{"region": "A", "revenue": "100"}, {"region": "C", "revenue": "7"}]

        result = svm.compare_rows(model, reference, ["region"], ["revenue"], 1e-6, "q")

        self.assertEqual(result["status"], "mismatch")
        self.assertEqual(result["model_only_rows"], [["B"]])
        self.assertEqual(result["reference_only_rows"], [["C"]])
        self.assertEqual(result["delta_rows"][0]["key"], ["A"])


if __name__ == "__main__":
    unittest.main()
