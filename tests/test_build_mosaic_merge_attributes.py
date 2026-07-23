"""Tests for the merge-attributes helpers.

merge-attributes is the Kimball conformance pattern for warehouses where
column names are prefixed per table (i_item_sk vs ss_item_sk). The end-to-end
flow requires a live Modeling Service, but the parsing and lock-recovery
helpers are pure and worth covering.
"""
import json
import os
import sys
import tempfile
import unittest


ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(ROOT, "skills", "build-mosaic-model", "scripts"))

import build_mosaic as bm  # noqa: E402


class ReadMergeHintsTests(unittest.TestCase):
    def _write(self, payload):
        # load_structured_file dispatches on suffix; .json is universal.
        f = tempfile.NamedTemporaryFile(
            "w", suffix=".json", delete=False, encoding="utf-8"
        )
        try:
            json.dump(payload, f)
        finally:
            f.close()
        self.addCleanup(os.remove, f.name)
        return f.name

    def test_flat_shape_parses_in_order(self):
        path = self._write({
            "store_sales.ss_item_sk":     "item.i_item_sk",
            "catalog_sales.cs_item_sk":   "item.i_item_sk",
            "store_sales.ss_customer_sk": "customer.c_customer_sk",
        })
        pairs = bm._read_merge_hints(path)
        self.assertEqual(len(pairs), 3)
        # Pairs preserved as (child, parent) tuples
        self.assertEqual(
            pairs[0],
            ("store_sales.ss_item_sk", "item.i_item_sk"),
        )

    def test_envelope_shape_parses(self):
        path = self._write({
            "merges": [
                {"child": "store_sales.ss_item_sk",   "parent": "item.i_item_sk"},
                {"child": "store_sales.ss_promo_sk",  "parent": "promotion.p_promo_sk"},
            ]
        })
        pairs = bm._read_merge_hints(path)
        self.assertEqual(len(pairs), 2)
        self.assertEqual(pairs[1], ("store_sales.ss_promo_sk", "promotion.p_promo_sk"))

    def test_envelope_skips_malformed_entries(self):
        path = self._write({
            "merges": [
                {"child": "a.b", "parent": "c.d"},
                {"child": "a.b"},                # missing parent
                "not a dict",                     # wrong type
            ]
        })
        pairs = bm._read_merge_hints(path)
        self.assertEqual(pairs, [("a.b", "c.d")])

    def test_empty_path_returns_empty_list(self):
        self.assertEqual(bm._read_merge_hints(""), [])

    def test_non_string_values_skipped_in_flat_shape(self):
        path = self._write({
            "store_sales.ss_item_sk": "item.i_item_sk",
            "store_sales.ss_qty":     42,         # not a string — skip
        })
        pairs = bm._read_merge_hints(path)
        self.assertEqual(pairs, [("store_sales.ss_item_sk", "item.i_item_sk")])


class LockConflictParsingTests(unittest.TestCase):
    """Covers the 8004cc41 lock-conflict error-body parser used by open_cs's
    auto-release path and the release-locks subcommand."""

    def test_extracts_lockid_from_xml_comment(self):
        body = {
            "errors": [{
                "code": "8004cc41",
                "additionalProperties": {
                    "existingLock": {
                        "comment": "<COMMENTS><PRODUCT>X</PRODUCT><LOCKID>DEADBEEF1234ABCD5678EF0123456789</LOCKID></COMMENTS>",
                        "ownerId": "OWNER123",
                    },
                    "userId": "OWNER123",
                },
            }]
        }
        self.assertEqual(
            bm._extract_lockid_from_error(body),
            "DEADBEEF1234ABCD5678EF0123456789",
        )

    def test_returns_none_when_no_lockid_present(self):
        body = {"errors": [{"code": "8004cc41", "additionalProperties": {}}]}
        self.assertIsNone(bm._extract_lockid_from_error(body))

    def test_returns_none_on_unrelated_error_body(self):
        self.assertIsNone(bm._extract_lockid_from_error({"errors": []}))
        self.assertIsNone(bm._extract_lockid_from_error(None))
        self.assertIsNone(bm._extract_lockid_from_error("not a dict"))

    def test_lock_owned_by_self_detects_match(self):
        body = {
            "errors": [{
                "additionalProperties": {
                    "existingLock": {"ownerId": "ME"},
                    "userId": "ME",
                }
            }]
        }
        self.assertTrue(bm._lock_owned_by_self(body, "ME"))

    def test_lock_owned_by_self_detects_other_owner(self):
        body = {
            "errors": [{
                "additionalProperties": {
                    "existingLock": {"ownerId": "BOB"},
                    "userId": "ME",
                }
            }]
        }
        self.assertFalse(bm._lock_owned_by_self(body, "ME"))

    def test_lock_owned_by_self_requires_user_id(self):
        body = {
            "errors": [{
                "additionalProperties": {
                    "existingLock": {"ownerId": "ME"},
                }
            }]
        }
        # No userId in body means we can't compare safely; treat as not self.
        self.assertFalse(bm._lock_owned_by_self(body, None))


class PlanAttributeMergesTests(unittest.TestCase):
    """merge-attributes previously required the CHILD column to already have
    its own attribute to merge from. When entity-key detection fails for the
    child's table (e.g. a compact-key naming convention like Ergast's
    driverid/raceid), the column never gets an attribute created at all --
    it 400s as a duplicate name during build and is dropped. There is
    nothing to "merge" in that case, but the parent should still be able to
    gain the expression directly. These tests cover that both the original
    (child exists) and new (child never existed) cases plan correctly."""

    def _attr(self, name):
        return {"information": {"name": name, "objectId": f"id-{name}"}}

    def test_merge_when_child_exists(self):
        parent = self._attr("Item")
        child = self._attr("StoreSalesItem")
        by_tcol = {
            ("item", "i_item_sk"): parent,
            ("store_sales", "ss_item_sk"): child,
        }
        table_ids = {"item": "T1", "store_sales": "T2"}
        plan, skips = bm._plan_attribute_merges(
            [("store_sales.ss_item_sk", "item.i_item_sk")], by_tcol, table_ids
        )
        self.assertEqual(skips, [])
        self.assertEqual(len(plan), 1)
        p, c, ct, cc, label = plan[0]
        self.assertIs(p, parent)
        self.assertIs(c, child)
        self.assertEqual((ct, cc), ("store_sales", "ss_item_sk"))

    def test_add_when_child_never_existed(self):
        # Regression test for the compact-key gap: child column has no entry
        # in by_tcol at all (no attribute was ever created for it), but the
        # child TABLE is still in the model. This must plan an "add", not a
        # pre-flight skip.
        parent = self._attr("Driver")
        by_tcol = {("drivers", "driverid"): parent}
        table_ids = {"drivers": "T1", "sprint_results": "T2"}
        plan, skips = bm._plan_attribute_merges(
            [("sprint_results.driverid", "drivers.driverid")], by_tcol, table_ids
        )
        self.assertEqual(skips, [])
        self.assertEqual(len(plan), 1)
        p, c, ct, cc, label = plan[0]
        self.assertIs(p, parent)
        self.assertIsNone(c)
        self.assertEqual((ct, cc), ("sprint_results", "driverid"))

    def test_skip_when_parent_missing(self):
        plan, skips = bm._plan_attribute_merges(
            [("child_t.c", "parent_t.p")], {}, {"child_t": "T1"}
        )
        self.assertEqual(plan, [])
        self.assertEqual(len(skips), 1)
        self.assertIn("parent attribute", skips[0][1])

    def test_skip_when_child_table_not_in_model(self):
        parent = self._attr("Item")
        by_tcol = {("item", "i_item_sk"): parent}
        plan, skips = bm._plan_attribute_merges(
            [("nonexistent_table.x", "item.i_item_sk")], by_tcol, {"item": "T1"}
        )
        self.assertEqual(plan, [])
        self.assertEqual(len(skips), 1)
        self.assertIn("not in model", skips[0][1])

    def test_skip_when_already_conformed(self):
        same = self._attr("Item")
        by_tcol = {
            ("item", "i_item_sk"): same,
            ("store_sales", "i_item_sk"): same,
        }
        plan, skips = bm._plan_attribute_merges(
            [("store_sales.i_item_sk", "item.i_item_sk")], by_tcol, {"store_sales": "T2"}
        )
        self.assertEqual(plan, [])
        self.assertEqual(len(skips), 1)
        self.assertIn("already conformed", skips[0][1])

    def test_skip_malformed_pair(self):
        plan, skips = bm._plan_attribute_merges([("no_dot_here", "also_no_dot")], {}, {})
        self.assertEqual(plan, [])
        self.assertEqual(len(skips), 1)
        self.assertIn("malformed pair", skips[0][1])


if __name__ == "__main__":
    unittest.main()
