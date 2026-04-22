import os
import sys
import unittest


ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(ROOT, "skill", "scripts"))

import build_mosaic as bm  # noqa: E402


class BuildMosaicClassificationTests(unittest.TestCase):
    def test_numeric_identifier_columns_default_to_attributes(self):
        columns = [
            {"name": "CUSTOMER_ID", "dataType": {"type": "integer"}},
            {"name": "PRODUCTKEY", "dataType": {"type": "integer"}},
            {"name": "ORDER_TOTAL", "dataType": {"type": "decimal"}},
        ]

        attrs, metrics = bm.classify_columns(columns, attr_override=set(), metric_override=set())

        self.assertEqual([c["name"] for c in attrs], ["CUSTOMER_ID", "PRODUCTKEY"])
        self.assertEqual([c["name"] for c in metrics], ["ORDER_TOTAL"])

    def test_metric_override_can_force_numeric_identifier_metric(self):
        columns = [{"name": "LINE_NUMBER", "dataType": {"type": "integer"}}]

        attrs, metrics = bm.classify_columns(columns, attr_override=set(), metric_override={"line_number"})

        self.assertEqual(attrs, [])
        self.assertEqual([c["name"] for c in metrics], ["LINE_NUMBER"])


if __name__ == "__main__":
    unittest.main()
