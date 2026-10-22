import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _hermetic  # noqa: E402,F401  (scrub MSTR_*/proxy env, private secret store)

# The plan and its check (skills/build-mosaic-model/REBUILD.md), on a catalog and data profile captured from a real
# tenant: four Snowflake tables (shipments and their customer, product and carrier dimensions) and two Postgres fact
# tables keyed by the same shipment id in lower case. Both failures that reached Strategy as HTTP 400 or as a model
# that could not answer by name are check errors here, before any write.
import copy  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import sys  # noqa: E402
import unittest  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "skills", "build-mosaic-model", "scripts"))
import mosaic_plan as mp  # noqa: E402

FIX = json.load(open(os.path.join(HERE, "fixtures", "mosaic_plan_freight.json")))
SHIP, CUST, CARR = "SD_RETAIL_FREIGHT_SHIPMENTS", "SD_RETAIL_FREIGHT_CUSTOMERS", "SD_RETAIL_FREIGHT_CARRIERS"
PERF, INV = "shipment_delivery_performance", "shipment_freight_invoice"


def plan(spec=None, prof=None):
    return mp.from_spec(spec or copy.deepcopy(FIX["spec"]), FIX["catalog"], FIX["profile"] if prof is None else prof)


def codes(p):
    return {f["code"] for f in mp.check(p) if f["level"] == "error"}


def rel(p, parent, child):
    return next((r for r in p["relationships"] if r["parent"] == parent and r["child"] == child), None)


class PlanFromSpecTests(unittest.TestCase):
    def test_the_captured_model_plans_and_checks_clean(self):
        p = plan()
        self.assertEqual(codes(p), set(), mp.check(p))
        self.assertEqual(p["keys"][SHIP], "Shipment")
        self.assertEqual(p["keys"][PERF], "Shipment")
        self.assertEqual(p["keys"][INV], "Invoice")
        self.assertEqual(p["keys"][CARR], "Carrier")                 # not Service Level, unique only by accident

    def test_a_key_spelled_differently_per_store_keeps_each_tables_spelling(self):
        shipment = next(a for a in plan()["attributes"] if a["name"] == "Shipment")
        cols = {e["table"]: e["column"] for e in shipment["forms"][0]["expressions"]}
        self.assertEqual(cols, {SHIP: "SHIPMENT_ID", PERF: "shipment_id", INV: "shipment_id"})

    def test_names_are_forms_of_their_attribute_and_every_attribute_reaches_the_facts(self):
        p = plan()
        customer = next(a for a in p["attributes"] if a["name"] == "Customer")
        self.assertEqual([f["name"] for f in customer["forms"]], ["ID", "Name"])
        for parent, child in (("Customer", "Shipment"), ("Product", "Shipment"), ("Carrier", "Shipment"), ("Region", "Customer"),
                              ("Service Level", "Carrier"), ("Delivered Date", "Shipment"), ("Shipment", "Invoice")):
            self.assertIsNotNone(rel(p, parent, child), (parent, child))
        self.assertEqual(rel(p, "Shipment", "Invoice")["type"], "one_to_one")      # one invoice per shipment, both keys
        self.assertEqual(rel(p, "Service Level", "Carrier")["type"], "one_to_many")
        self.assertNotIn("attribute_reaches_no_metric", codes(p))

    def test_an_explicit_relationship_is_added_not_a_switch_that_drops_the_rest(self):
        p = plan()
        self.assertEqual(rel(p, "Product Category", "Product")["source"], "specification")
        self.assertIsNotNone(rel(p, "Customer", "Shipment"))
        self.assertGreater(len(p["relationships"]), 10)

    def test_without_a_measured_profile_the_specification_still_decides_the_keys(self):
        p = plan(prof={})
        self.assertEqual(p["keys"][SHIP], "Shipment")
        self.assertTrue(any("could not be measured" in n for n in p["notes"]))

    def test_a_column_the_catalog_does_not_have_is_refused(self):
        spec = copy.deepcopy(FIX["spec"])
        spec["metrics"][0]["column"] = "NOT_THERE"
        with self.assertRaises(mp.PlanError):
            plan(spec)


class CheckTests(unittest.TestCase):
    def test_a_relationship_through_a_table_its_parent_is_not_on_is_an_error(self):
        p = plan()
        p["relationships"].append({"parent": "Customer", "child": "Invoice", "table": INV, "type": "one_to_many"})
        self.assertIn("relationship_end_off_table", codes(p))

    def test_an_attribute_with_no_route_to_any_metric_is_an_error(self):
        p = plan()
        p["relationships"] = [r for r in p["relationships"] if r["parent"] != "Region"]
        self.assertIn("attribute_reaches_no_metric", codes(p))

    def test_loops_and_two_way_pairs_are_errors(self):
        p = plan()
        p["relationships"].append({"parent": "Shipment", "child": "Customer", "table": SHIP, "type": "one_to_many"})
        self.assertTrue({"relationship_cycle", "relationship_both_ways"} <= codes(p))

    def test_keys_of_different_kinds_across_tables_are_an_error(self):
        cat = copy.deepcopy(FIX["catalog"])
        for t in cat["tables"]:
            if t["table"] == PERF:
                for c in t["columns"]:
                    if c["name"] == "shipment_id":
                        c["dataType"] = {"type": "utf8_char", "precision": 20, "scale": 0}
        p = mp.from_spec(copy.deepcopy(FIX["spec"]), cat, FIX["profile"])
        self.assertIn("key_types_differ", codes(p))

    def test_summing_a_key_or_text_is_an_error(self):
        p = plan()
        p["metrics"].append({"name": "Shipment Id Total", "table": SHIP, "column": "SHIPMENT_ID", "function": "sum", "format": "integer"})
        p["metrics"].append({"name": "Mode Total", "table": SHIP, "column": "SHIPPING_MODE", "function": "sum", "format": "integer"})
        self.assertTrue({"sum_of_key", "aggregation_type"} <= codes(p))

    def test_two_equally_likely_keys_are_refused_not_guessed(self):
        spec = copy.deepcopy(FIX["spec"])
        invoice = next(a for a in spec["attributes"] if a["name"] == "Invoice")
        spec["attributes"].append({**copy.deepcopy(invoice), "name": "Billing Document"})     # claims the table just as well
        p = mp.from_spec(spec, FIX["catalog"], FIX["profile"])
        self.assertNotIn(INV, p["keys"])
        self.assertTrue(any("could each be its key" in n for n in p["notes"]))


if __name__ == "__main__":
    unittest.main()
