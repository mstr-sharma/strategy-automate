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

    def test_normalize_catalog_datatype_replaces_int_min_sentinel(self):
        # Strategy's catalog probe for Postgres returns scale=INT32_MIN on
        # every integer column. Build flow used to forward that into the
        # model body verbatim, and the UI's preview engine then fails with
        # "DssDataType '4' is invalid or not supported" — code 4 maps to the
        # legacy "Numeric" type which the engine can't render. Same sentinel
        # has been seen on fixed_length_string scale.
        # The sanitizer should replace the sentinel with 0 (safe default
        # for every type we've observed) without touching valid values.
        cases = [
            # (input, expected)
            (
                {"type": "integer", "precision": 4, "scale": -2147483648},
                {"type": "integer", "precision": 4, "scale": 0},
            ),
            (
                {"type": "fixed_length_string", "precision": 60, "scale": -2147483648},
                {"type": "fixed_length_string", "precision": 60, "scale": 0},
            ),
            (
                # Date catalog probe returns scale=-1 which some preview paths reject.
                {"type": "date", "precision": 4, "scale": -1},
                {"type": "date", "precision": 4, "scale": 0},
            ),
            (
                # Already-clean decimal — pass through untouched.
                {"type": "decimal", "precision": 7, "scale": 2},
                {"type": "decimal", "precision": 7, "scale": 2},
            ),
            (
                # Precision sentinel — rare but seen on unknown-precision probes.
                {"type": "varchar", "precision": -2147483648, "scale": 0},
                {"type": "varchar", "precision": 0, "scale": 0},
            ),
        ]
        for input_dt, expected in cases:
            self.assertEqual(bm._normalize_catalog_datatype(input_dt), expected,
                             f"sanitize failed for {input_dt}")

    def test_normalize_catalog_datatype_is_idempotent(self):
        clean = {"type": "integer", "precision": 4, "scale": 0}
        self.assertEqual(bm._normalize_catalog_datatype(clean), clean)
        # Calling twice produces the same result.
        once = bm._normalize_catalog_datatype({"type": "integer", "precision": 4, "scale": -2147483648})
        twice = bm._normalize_catalog_datatype(once)
        self.assertEqual(once, twice)

    def test_normalize_catalog_datatype_handles_non_dict(self):
        self.assertIsNone(bm._normalize_catalog_datatype(None))
        self.assertEqual(bm._normalize_catalog_datatype("integer"), "integer")

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
