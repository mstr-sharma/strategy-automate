import os
import sys
import unittest


ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(ROOT, "skills", "build-mosaic-model", "scripts"))

import build_mosaic as bm  # noqa: E402
import preflight_model_check as pf  # noqa: E402


# Fixture spans the cases that drifted historically: Kimball surrogate keys
# (_SK / bare SK), classic ID/key/no columns, datatypes the old preflight
# NUMERIC_DATATYPES set was missing (money, int64, int32, fixed_numeric,
# long, short), plain numerics, numeric dimension tokens, and text columns.
COLUMNS = [
    {"name": "I_ITEM_SK",       "dataType": {"type": "integer"}},
    {"name": "ss_sold_date_sk", "dataType": {"type": "integer"}},
    {"name": "SK",              "dataType": {"type": "integer"}},
    {"name": "CUSTOMER_ID",     "dataType": {"type": "bigint"}},
    {"name": "ORDER_NO",        "dataType": {"type": "integer"}},
    {"name": "PRODUCT_KEY",     "dataType": {"type": "integer"}},
    {"name": "UNIT_PRICE",      "dataType": {"type": "money"}},
    {"name": "QUANTITY_SOLD",   "dataType": {"type": "int64"}},
    {"name": "DISCOUNT_AMT",    "dataType": {"type": "int32"}},
    {"name": "NET_PROFIT",      "dataType": {"type": "fixed_numeric"}},
    {"name": "TAX_RATE",        "dataType": {"type": "long"}},
    {"name": "REORDER_LEVEL",   "dataType": {"type": "short"}},
    {"name": "ORDER_TOTAL",     "dataType": {"type": "decimal", "precision": 18, "scale": 2}},
    {"name": "WEIGHT_KG",       "dataType": {"type": "double"}},
    {"name": "FISCAL_YEAR",     "dataType": {"type": "integer"}},
    {"name": "MONTH_OF_YEAR",   "dataType": {"type": "smallint"}},
    {"name": "CUSTOMER_NAME",   "dataType": {"type": "varchar"}},
    {"name": "ITEM_DESC",       "dataType": {"type": "varchar"}},
]


def build_role(col):
    """Role build_mosaic's auto-builder assigns: 'attribute' | 'metric'."""
    attrs, metrics = bm.classify_columns([col], attr_override=set(), metric_override=set())
    assert len(attrs) + len(metrics) == 1, col["name"]
    return "attribute" if attrs else "metric"


class PreflightBuildAgreementTests(unittest.TestCase):
    """preflight_model_check exists to PREDICT build_mosaic's classification.

    The two used to keep separate heuristic copies and drifted (I_ITEM_SK
    predicted 'metric' while the build classified 'attribute'; money/int64
    columns predicted 'attribute' while the build summed them). preflight now
    delegates to build_mosaic; this test pins the agreement column by column.
    """

    def test_predicted_role_agrees_with_build_for_every_column(self):
        for col in COLUMNS:
            ci = pf.classify_column("STORE_SALES", col)
            predicted = pf.predict_role(ci)
            self.assertEqual(
                predicted, build_role(col),
                f"preflight/build disagree on {col['name']} ({col['dataType']['type']})",
            )

    def test_historic_drift_cases_pinned(self):
        # Kimball surrogate key: integer but an attribute, never a metric.
        sk = pf.classify_column("ITEM", {"name": "I_ITEM_SK", "dataType": {"type": "integer"}})
        self.assertEqual(pf.predict_role(sk), "attribute")
        # Datatypes missing from the old local NUMERIC_DATATYPES set: metrics.
        for dt in ("money", "int64", "int32", "fixed_numeric", "long", "short"):
            ci = pf.classify_column("STORE_SALES", {"name": "SOME_MEASURE", "dataType": {"type": dt}})
            self.assertEqual(pf.predict_role(ci), "metric", dt)

    def test_preflight_no_longer_defines_local_heuristic_copies(self):
        for stale in ("ID_TOKENS", "NUMERIC_DATATYPES", "NATURAL_NUMERIC_DIMS"):
            self.assertFalse(hasattr(pf, stale), f"{stale} redefined in preflight — drift risk")


if __name__ == "__main__":
    unittest.main()
