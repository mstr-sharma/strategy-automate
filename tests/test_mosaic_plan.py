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

    def test_a_switched_off_relationship_is_left_out_and_the_check_says_what_it_costs(self):
        spec = copy.deepcopy(FIX["spec"])
        spec["excluded_relationships"] = ["Region → Customer"]
        p = plan(spec)
        self.assertIsNone(rel(p, "Region", "Customer"))
        self.assertEqual([(r["parent"], r["child"]) for r in p["excluded"]], [("Region", "Customer")])
        self.assertIn("attribute_reaches_no_metric", codes(p))          # Region then answers nothing

    def test_a_column_the_catalog_does_not_have_is_refused(self):
        spec = copy.deepcopy(FIX["spec"])
        spec["metrics"][0]["column"] = "NOT_THERE"
        with self.assertRaises(mp.PlanError):
            plan(spec)


class CheckTests(unittest.TestCase):
    def test_a_pair_on_two_tables_is_planned_once_on_the_childs_lookup_and_twice_is_an_error(self):
        # Strategy keeps one relationship per pair (live: the second table's copy answered HTTP 400)
        spec = copy.deepcopy(FIX["spec"])
        ship_date = next(a for a in spec["attributes"] if a["name"] == "Ship Date")
        ship_date["forms"].append({"name": "ID", "category": "ID", "table": PERF, "column": "delivered_date"})   # both tables keyed by shipment
        p = mp.from_spec(spec, FIX["catalog"], FIX["profile"])
        self.assertEqual([r["table"] for r in p["relationships"] if (r["parent"], r["child"]) == ("Ship Date", "Shipment")], [SHIP])
        p["relationships"].append({**rel(p, "Customer", "Shipment"), "table": PERF})
        self.assertIn("relationship_twice", codes(p))

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


class SpecFromTablesTests(unittest.TestCase):
    def test_tables_alone_plan_like_a_hand_made_design(self):
        spec = mp.spec_from_tables(FIX["catalog"], FIX["profile"], "Freight")
        p = mp.from_spec(spec, FIX["catalog"], FIX["profile"])
        self.assertEqual(codes(p), set(), mp.check(p))
        self.assertEqual(p["keys"], {SHIP: "Shipment", "SD_RETAIL_FREIGHT_PRODUCTS": "Product", CUST: "Customer", CARR: "Carrier",
                                     PERF: "Shipment", INV: "Invoice"})
        shipment = next(a for a in spec["attributes"] if a["name"] == "Shipment")
        self.assertEqual(len(shipment["forms"]), 3)                     # SHIPMENT_ID and both shipment_id, one attribute
        self.assertTrue(all(m["function"] == "sum" for m in spec["metrics"]))

    def test_a_bare_id_is_never_shared_and_names_never_collide(self):
        cat = {"tables": [{"datasource_id": "D", "datasource": "S", "dbms": "PostgreSQL", "schema": "s", "table": t,
                           "columns": [{"name": "id", "dataType": {"type": "integer"}}, {"name": "name", "dataType": {"type": "utf8_char"}},
                                       {"name": "amount", "dataType": {"type": "double"}}]} for t in ("orders", "refunds")]}
        spec = mp.spec_from_tables(cat, {}, "Two")
        ids = [a for a in spec["attributes"] if any(f["column"] == "id" for f in a["forms"])]
        self.assertEqual(len(ids), 2)                                   # one per table
        names = [a["name"] for a in spec["attributes"]] + [m["name"] for m in spec["metrics"]]
        self.assertEqual(len(names), len({n.casefold() for n in names}))

    def test_an_unmeasured_key_candidate_never_breaks_key_ranking(self):
        prof = copy.deepcopy(FIX["profile"])
        prof[INV]["distinct"].pop("invoice_number")                    # one candidate measured, one not
        p = mp.from_spec(copy.deepcopy(FIX["spec"]), FIX["catalog"], prof)
        self.assertIn(INV, p["keys"])
