"""Regression fixture: a public Kaggle/Ergast-style F1 schema.

Found by actually building a Mosaic model against this exact public dataset
(14 tables in Postgres: drivers, constructors, circuits, seasons, status,
races, results, sprint_results, qualifying, lap_times, pit_stops,
driver_standings, constructor_standings, constructor_results). Every ID
column uses a compact, no-underscore naming convention (driverid, raceid,
constructorid, statusid) instead of the underscored form (driver_id) the
existing test fixtures (TPC-DS/AdventureWorks/FoodMart/Snowflake SAMPLE_DATA
style) all use.

This single naming convention change, on an otherwise completely ordinary
star/snowflake schema, triggered three separate, independent bugs at once:
  1. Entity-key detection (_find_entity_key) never matched any table's own
     key, because it only tried underscored suffixes.
  2. A deeper bug found while fixing #1: the plural-stripping inside that
     same detector never fired for lowercase table names (the normal case
     for Postgres), independent of the underscore question.
  3. _looks_like_identifier_col's bare-suffix matching, which #1/#2 rely on
     to correctly classify FK columns as attributes rather than metrics, is
     ambiguous by nature and produces a real false positive on this exact
     schema: "grid" (F1 starting grid position, a genuine metric) ends in
     the same bare "ID" letters as "driverid" does.

Each bug has its own targeted unit test elsewhere in this suite
(test_build_mosaic_classification.py). This file additionally exercises
_find_entity_key and classify_columns together across a representative
slice of the real schema, as one fixture, to catch interaction bugs the
per-function unit tests could each pass individually while still combining
incorrectly.
"""
import os
import sys
import unittest


ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(ROOT, "skills", "build-mosaic-model", "scripts"))

import build_mosaic as bm  # noqa: E402


# A representative 4-table slice: a simple dim (drivers), a lookup dim
# (status), and two fact tables at different grains (results, one row per
# driver per race; driver_standings, a periodic-snapshot fact) -- enough to
# cover a table's own key, a shared FK to a different table, an isolated
# per-table surrogate key, and the grid/points classification split.
ERGAST_SLICE = {
    "drivers": [
        {"name": "driverid",  "dataType": {"type": "integer"}},
        {"name": "driverref", "dataType": {"type": "varchar"}},
        {"name": "forename",  "dataType": {"type": "varchar"}},
        {"name": "surname",   "dataType": {"type": "varchar"}},
    ],
    "status": [
        {"name": "statusid", "dataType": {"type": "integer"}},
        {"name": "status",   "dataType": {"type": "varchar"}},
    ],
    "results": [
        {"name": "resultid",     "dataType": {"type": "integer"}},
        {"name": "raceid",       "dataType": {"type": "integer"}},
        {"name": "driverid",     "dataType": {"type": "integer"}},
        {"name": "statusid",     "dataType": {"type": "integer"}},
        {"name": "grid",         "dataType": {"type": "integer"}},   # metric, not a key
        {"name": "points",       "dataType": {"type": "decimal"}},   # metric
        {"name": "positiontext", "dataType": {"type": "varchar"}},   # descriptor
    ],
    "driver_standings": [
        {"name": "driverstandingsid", "dataType": {"type": "integer"}},
        {"name": "raceid",            "dataType": {"type": "integer"}},
        {"name": "driverid",          "dataType": {"type": "integer"}},
        {"name": "points",            "dataType": {"type": "decimal"}},
        {"name": "wins",              "dataType": {"type": "integer"}},
    ],
}


class ErgastCompactKeySchemaTests(unittest.TestCase):
    def _names(self, table):
        return [(c["name"] or "").upper() for c in ERGAST_SLICE[table]]

    def test_every_tables_own_entity_key_is_found(self):
        # drivers.driverid, status.statusid, results.resultid,
        # driver_standings.driverstandingsid must all resolve as THAT
        # table's own entity key despite the compact naming.
        self.assertEqual(bm._find_entity_key("drivers", self._names("drivers")), "DRIVERID")
        self.assertEqual(bm._find_entity_key("status", self._names("status")), "STATUSID")
        self.assertEqual(bm._find_entity_key("results", self._names("results")), "RESULTID")
        self.assertEqual(
            bm._find_entity_key("driver_standings", self._names("driver_standings")),
            "DRIVERSTANDINGSID",
        )

    def test_grid_and_points_classified_as_metrics_everywhere_they_appear(self):
        for table in ("results",):
            attrs, metrics = bm.classify_columns(
                ERGAST_SLICE[table], attr_override=set(), metric_override=set()
            )
            metric_names = {c["name"] for c in metrics}
            attr_names = {c["name"] for c in attrs}
            self.assertIn("grid", metric_names)
            self.assertIn("points", metric_names)
            self.assertNotIn("grid", attr_names)
            self.assertNotIn("points", attr_names)

        # driver_standings.points is semi-additive (cumulative) rather than a
        # plain per-race total, but that's a metric *function* choice (see
        # reference_mosaic_business_logic_translation.md's aggregation-by-
        # semantics table) -- it must still land in the metrics bucket here.
        attrs, metrics = bm.classify_columns(
            ERGAST_SLICE["driver_standings"], attr_override=set(), metric_override=set()
        )
        self.assertIn("points", {c["name"] for c in metrics})
        self.assertIn("wins", {c["name"] for c in metrics})

    def test_key_and_descriptor_columns_classified_as_attributes(self):
        for table, key_cols in [
            ("drivers", {"driverid"}),
            ("status", {"statusid"}),
            ("results", {"resultid", "raceid", "driverid", "statusid", "positiontext"}),
            ("driver_standings", {"driverstandingsid", "raceid", "driverid"}),
        ]:
            attrs, _metrics = bm.classify_columns(
                ERGAST_SLICE[table], attr_override=set(), metric_override=set()
            )
            attr_names = {c["name"] for c in attrs}
            self.assertEqual(
                attr_names & key_cols, key_cols,
                f"{table}: expected all of {key_cols} classified as attributes, got {attr_names}",
            )

    def test_shared_fk_columns_use_identical_names_across_tables(self):
        # Prerequisite for cross-table conformance: driverid/raceid/statusid
        # must be the exact same physical column name (case aside) everywhere
        # they occur, which is what lets them collapse into one conformed
        # attribute once entity-key detection (fixed above) recognizes them.
        driverid_tables = [t for t, cols in ERGAST_SLICE.items()
                          if any((c["name"] or "").lower() == "driverid" for c in cols)]
        self.assertEqual(set(driverid_tables), {"drivers", "results", "driver_standings"})


if __name__ == "__main__":
    unittest.main()
