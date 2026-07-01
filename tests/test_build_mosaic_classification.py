import os
import sys
import unittest


ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(ROOT, "skills", "build-mosaic-model", "scripts"))

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
                # Decimal with sentinel scale is the ONE exception to "sentinel
                # scale -> 0": zeroing it here would make it indistinguishable
                # from a confirmed scale of 0, and schema_object_translator.
                # normalize_datatype() maps a confirmed 0 to int64 -- which
                # silently discards real fractional values (see
                # test_decimal_sentinel_scale_becomes_double_not_int64 in
                # tests/test_schema_object_import.py for the concrete example).
                # The sentinel must survive this step untouched so that function
                # can tell "confirmed whole number" apart from "unknown scale".
                {"type": "decimal", "precision": 4, "scale": -2147483648},
                {"type": "decimal", "precision": 4, "scale": -2147483648},
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

    def test_find_entity_key_underscored_convention(self):
        # The explicit, unambiguous convention -- must keep working.
        self.assertEqual(
            bm._find_entity_key("OPPORTUNITIES", ["OPPORTUNITY_ID", "AMOUNT"]),
            "OPPORTUNITY_ID",
        )
        self.assertEqual(
            bm._find_entity_key("PURCHASE_ORDERS", ["PO_ID", "AMOUNT"]),
            "PO_ID",
        )

    def test_find_entity_key_compact_no_underscore_convention(self):
        # Regression test: the Ergast/Kaggle-style F1 schema (drivers, races,
        # constructors, ...) names every key with no separator (driverid,
        # raceid, constructorid). Before this fix, _entity_candidates() only
        # ever tried the underscored suffix (DRIVER_ID), so this returned None
        # for every table in such a schema -- entity-key detection, and
        # therefore cross-table conformance, silently never fired at all.
        self.assertEqual(
            bm._find_entity_key("drivers", ["DRIVERID", "DRIVERREF", "FORENAME"]),
            "DRIVERID",
        )
        self.assertEqual(
            bm._find_entity_key("constructors", ["CONSTRUCTORID", "NAME"]),
            "CONSTRUCTORID",
        )

    def test_find_entity_key_lowercase_table_name(self):
        # Postgres table names come back lowercase. _entity_prefix's
        # plural-stripping used to compare against literal uppercase suffixes
        # ("S", "IES", ...), so a lowercase tname like "drivers" was never
        # singularized (stayed "DRIVERS" after the final .upper()) and could
        # never match a "DRIVER..." column no matter which suffix list was
        # tried. This must work for lowercase, UPPERCASE, and mixed-case names.
        self.assertEqual(
            bm._find_entity_key("drivers", ["DRIVERID"]), "DRIVERID"
        )
        self.assertEqual(
            bm._find_entity_key("DRIVERS", ["DRIVERID"]), "DRIVERID"
        )
        self.assertEqual(
            bm._find_entity_key("Drivers", ["DRIVERID"]), "DRIVERID"
        )

    def test_find_entity_key_does_not_false_match_unrelated_columns(self):
        # "results" singularizes to "RESULT"; grid/points/laps must not be
        # mistaken for the table's entity key just because they're numeric.
        self.assertEqual(
            bm._find_entity_key("results", ["RESULTID", "GRID", "POINTS", "LAPS"]),
            "RESULTID",
        )

    def test_find_entity_key_returns_none_when_no_candidate_matches(self):
        self.assertIsNone(
            bm._find_entity_key("driver_standings", ["DRIVER_ID", "RACE_ID", "POINTS"])
        )

    def test_grid_column_classified_as_metric_not_identifier(self):
        # Regression test: "grid" (F1 starting grid position) ends in the bare
        # letters "ID" the same way "driverid" does, but is an ordinary word,
        # not a key. Before the denylist, classify_columns put it in attrs and
        # it was silently dropped from the model entirely wherever a second
        # occurrence collided on the resulting default attribute name.
        columns = [
            {"name": "grid",  "dataType": {"type": "integer"}},
            {"name": "points", "dataType": {"type": "decimal"}},
        ]
        attrs, metrics = bm.classify_columns(columns, attr_override=set(), metric_override=set())
        self.assertEqual(attrs, [])
        self.assertEqual([c["name"] for c in metrics], ["grid", "points"])

    def test_compact_key_columns_still_classified_as_attributes(self):
        # The denylist must not swallow genuine compact-style identifiers --
        # only the specific known false positives it names.
        columns = [
            {"name": "driverid", "dataType": {"type": "integer"}},
            {"name": "raceid",   "dataType": {"type": "integer"}},
            {"name": "resultid", "dataType": {"type": "integer"}},
        ]
        attrs, metrics = bm.classify_columns(columns, attr_override=set(), metric_override=set())
        self.assertEqual([c["name"] for c in attrs], ["driverid", "raceid", "resultid"])
        self.assertEqual(metrics, [])

    def test_add_table_expression_to_form_appends_new_table(self):
        forms = [{
            "id": "F1", "category": "ID",
            "expressions": [{
                "expression": {"tokens": [{"type": "column_reference", "value": "primary_customer_id"}]},
                "tables": [{"objectId": "T1", "subType": "logical_table", "name": "orders"}],
            }],
        }]
        added = bm._add_table_expression_to_form(forms, "T2", "invoices", "customer_id")
        self.assertTrue(added)
        exprs = forms[0]["expressions"]
        self.assertEqual(len(exprs), 2)
        self.assertEqual(exprs[1]["tables"][0]["name"], "invoices")
        self.assertEqual(exprs[1]["expression"]["tokens"][0]["value"], "customer_id")

    def test_add_table_expression_to_form_is_idempotent(self):
        # Calling it twice for the same table must not add a duplicate expression.
        forms = [{"id": "F1", "category": "ID", "expressions": []}]
        bm._add_table_expression_to_form(forms, "T1", "orders", "customer_id")
        bm._add_table_expression_to_form(forms, "T1", "orders", "customer_id")
        self.assertEqual(len(forms[0]["expressions"]), 1)

    def test_add_table_expression_to_form_returns_false_with_no_forms(self):
        self.assertFalse(bm._add_table_expression_to_form([], "T1", "orders", "customer_id"))


if __name__ == "__main__":
    unittest.main()
