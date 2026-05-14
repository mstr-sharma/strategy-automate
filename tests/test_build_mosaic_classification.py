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

    def test_sk_surrogate_key_columns_classified_as_attributes(self):
        # Kimball-style surrogate keys end in _SK. Without this rule, every
        # FK on a fact table classifies as a metric (because they're INTEGER)
        # and downstream conformance/relationship wiring has nothing to bind
        # to. The TPC-DS, AdventureWorks, FoodMart, and Snowflake SAMPLE_DATA
        # warehouses all use this convention.
        columns = [
            {"name": "d_date_sk",       "dataType": {"type": "integer"}},
            {"name": "ss_sold_date_sk", "dataType": {"type": "integer"}},
            {"name": "i_item_sk",       "dataType": {"type": "integer"}},
            {"name": "SK",              "dataType": {"type": "integer"}},  # bare 'SK' column
            {"name": "ss_quantity",     "dataType": {"type": "integer"}},  # genuine metric
        ]

        attrs, metrics = bm.classify_columns(columns, attr_override=set(), metric_override=set())

        self.assertEqual(
            [c["name"] for c in attrs],
            ["d_date_sk", "ss_sold_date_sk", "i_item_sk", "SK"],
        )
        self.assertEqual([c["name"] for c in metrics], ["ss_quantity"])


if __name__ == "__main__":
    unittest.main()
