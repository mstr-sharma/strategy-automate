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


if __name__ == "__main__":
    unittest.main()
