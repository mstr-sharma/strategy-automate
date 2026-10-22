import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _hermetic  # noqa: E402,F401  (scrub MSTR_*/proxy env, private secret store)

# The model recommender's pure steps (infer, recommend) on an invented catalog: a Snowflake retail dataset with declared
# keys, an unrelated Snowflake dataset that reuses CUSTOMER_ID, and a Postgres table that really belongs to the first.
import copy  # noqa: E402
import os  # noqa: E402
import sys  # noqa: E402
import unittest  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "skills", "build-mosaic-model", "scripts"))
import mosaic_discover as md  # noqa: E402
import mosaic_plan as mp  # noqa: E402

N, T = {"type": "integer"}, {"type": "utf8_char"}
D = {"type": "date"}


def table(ds, dbms, schema, name, cols, pk=(), rows=100):
    return {"datasource_id": ds, "datasource": ds, "dbms": dbms, "schema": schema, "table": name, "rows": rows, "pk": list(pk),
            "family": md._family_key(name), "columns": [{"name": c, "dataType": t} for c, t in cols]}


def graph():
    a = "SD_RETAIL_SHOPA_20260101_0000_"
    b = "SD_TECH_OTHERCO_20260101_0000_"
    ts = [
        table("SF", "Snowflake", "S", a + "CUSTOMERS", [("CUSTOMER_ID", N), ("CUSTOMER_NAME", T), ("REGION", T)], ["CUSTOMER_ID"], 200),
        table("SF", "Snowflake", "S", a + "CALENDAR", [("CALENDAR_DATE", D), ("MONTH_NAME", T)], ["CALENDAR_DATE"], 365),
        table("SF", "Snowflake", "S", a + "ORDERS", [("ORDER_ID", N), ("CUSTOMER_ID", N), ("ORDER_DAY", D), ("AMOUNT", {"type": "double"})], ["ORDER_ID"], 5000),
        table("SF", "Snowflake", "S", b + "CUSTOMERS", [("CUSTOMER_ID", N), ("SEGMENT", T)], ["CUSTOMER_ID"], 80),
        table("SF", "Snowflake", "S", b + "USAGE", [("USAGE_ID", N), ("CUSTOMER_ID", N), ("MINUTES", {"type": "double"})], ["USAGE_ID"], 900),
        table("PG", "PostgreSQL", "p", "shopa_refunds", [("refund_id", N), ("customer_id", N), ("refund_usd", {"type": "double"})], ["refund_id"], 300),
    ]
    g = {"tables": {md.tkey(t): t for t in ts}, "fks": [
        {"child": f"SF/S/{a}ORDERS", "child_cols": ["CUSTOMER_ID"], "parent": f"SF/S/{a}CUSTOMERS", "parent_cols": ["CUSTOMER_ID"]},
        {"child": f"SF/S/{a}ORDERS", "child_cols": ["ORDER_DAY"], "parent": f"SF/S/{a}CALENDAR", "parent_cols": ["CALENDAR_DATE"]}]}
    return g, a, b


def link(inf, frm, to):
    return next((l for l in inf["links"] if l["from"].endswith(frm) and l["to"].endswith(to)), None)


class InferTests(unittest.TestCase):
    def test_a_declared_key_joins_differently_named_columns(self):
        g, a, _ = graph()
        inf = md.infer(g)
        l = link(inf, a + "CALENDAR", a + "ORDERS")
        self.assertEqual(l["columns"], ["CALENDAR_DATE", "ORDER_DAY"])
        self.assertIn("declared", l["evidence"])

    def test_a_shared_name_across_unrelated_families_is_weak_until_the_data_agrees(self):
        g, a, b = graph()
        weak = link(md.infer(g), a + "CUSTOMERS", "shopa_refunds")
        self.assertIsNotNone(weak)
        self.assertLessEqual(weak["confidence"], md.UNRELATED_NAME)
        self.assertNotIn("declared", weak["evidence"])                 # a declared key elsewhere never lends its evidence
        g["measured"] = {f"SF/S/{a}CUSTOMERS|PG/p/shopa_refunds": 1.0, f"SF/S/{a}CUSTOMERS|SF/S/{b}CUSTOMERS": 0.0}
        inf = md.infer(g)
        self.assertIn("measured", link(inf, a + "CUSTOMERS", "shopa_refunds")["evidence"])
        self.assertIsNone(link(inf, a + "CUSTOMERS", b + "CUSTOMERS"))       # different customers: not a link

    def test_each_family_keeps_its_own_home(self):
        g, a, b = graph()
        inf = md.infer(g)
        self.assertIsNotNone(link(inf, b + "CUSTOMERS", b + "USAGE"))        # OtherCo usage points at OtherCo customers
        self.assertIsNone(link(inf, a + "CUSTOMERS", b + "USAGE"))

    def test_curation_wins(self):
        g, a, _ = graph()
        k = [f"SF/S/{a}CUSTOMERS", "PG/p/shopa_refunds"]
        self.assertEqual(link(md.infer(g, curation={"confirmed_links": [k]}), a + "CUSTOMERS", "shopa_refunds")["confidence"], 1.0)
        self.assertIsNone(link(md.infer(g, curation={"rejected_links": [k]}), a + "CUSTOMERS", "shopa_refunds"))


class RecommendTests(unittest.TestCase):
    def test_stars_checked_and_cross_store_when_the_data_agrees(self):
        g, a, b = graph()
        g["measured"] = {f"SF/S/{a}CUSTOMERS|PG/p/shopa_refunds": 1.0, f"SF/S/{a}CUSTOMERS|SF/S/{b}CUSTOMERS": 0.0}
        recs = md.recommend(md.infer(g), {"cross_store": "prefer"})
        orders = next(r for r in recs if r["fact"] == a + "ORDERS" and r["kind"] == "star")
        self.assertEqual(set(orders["tables"]), {a + "ORDERS", a + "CUSTOMERS", a + "CALENDAR"})    # no other facts pulled in
        refunds = next(r for r in recs if r["fact"] == "shopa_refunds" and r["kind"] == "star")
        self.assertEqual(refunds["stores"], ["PostgreSQL", "Snowflake"])
        customer = next(x for x in refunds["spec"]["attributes"] if any(f["column"] == "customer_id" for f in x["forms"]))
        self.assertEqual({f["column"] for f in customer["forms"]}, {"CUSTOMER_ID", "customer_id"})   # one attribute across stores
        self.assertTrue(all(r["checked"] for r in recs), [(r["name"], r["problems"]) for r in recs if not r["checked"]])

    def test_already_modeled_tables_rank_lower_and_avoid_keeps_one_store(self):
        g, a, _ = graph()
        g["measured"] = {f"SF/S/{a}CUSTOMERS|PG/p/shopa_refunds": 1.0}
        inf = md.infer(g)
        fresh = next(r for r in md.recommend(inf) if r["fact"] == a + "ORDERS")
        modeled = next(r for r in md.recommend(inf, {"modeled_tables": [f"SF/S/{a}ORDERS", f"SF/S/{a}CUSTOMERS"]}) if r["fact"] == a + "ORDERS")
        self.assertLess(modeled["score"], fresh["score"])
        self.assertTrue(all(len(r["stores"]) == 1 for r in md.recommend(inf, {"cross_store": "avoid"})))


class PlannerLoopTests(unittest.TestCase):
    def test_two_tables_carrying_each_others_keys_relate_one_way(self):
        cat = {"tables": [table("SF", "Snowflake", "S", "STORES", [("STORE_ID", N), ("LOCATION_ID", N)], ["STORE_ID"]),
                          table("SF", "Snowflake", "S", "LOCATIONS", [("LOCATION_ID", N), ("STORE_ID", N), ("CITY", T)], ["LOCATION_ID"]),
                          table("SF", "Snowflake", "S", "SALES", [("SALE_ID", N), ("STORE_ID", N), ("AMOUNT", {"type": "double"})], ["SALE_ID"])]}
        p = mp.from_spec(mp.spec_from_tables(cat, {}, "Loop"), cat, {})
        pairs = {(r["parent"], r["child"]) for r in p["relationships"]}
        self.assertFalse(any((c, p_) in pairs for p_, c in pairs))
        self.assertNotIn("relationship_cycle", {f["code"] for f in mp.check(p)})


if __name__ == "__main__":
    unittest.main()


class StarSchemaByRoleNames(unittest.TestCase):
    """A real scan's metadata (anonymized): a manufacturing star named by role (DIM_DATE, DIM_MACHINE, DIM_PLANT, three
    FACT_ tables), no declared keys, the facts' PLANT_ID matching DIM_PLANT.SOURCE_PLANT_ID. The drafted designs must
    build: conformed keys homed on their dimensions, dimension numbers as attributes, plant details kept."""

    @classmethod
    def setUpClass(cls):
        import json
        cls.graph = json.load(open(os.path.join(HERE, "fixtures", "discover_star_schema.json")))
        cls.inf = md.infer(cls.graph)
        cls.recs = md.recommend(cls.inf)

    def entity(self, name):
        return next(e for e in self.inf["entities"] if e["name"] == name)

    def test_role_named_tables_are_one_family(self):
        fams = {md._family_key(t["table"], t["schema"], t["datasource_id"]) for t in self.graph["tables"].values()}
        self.assertEqual(len(fams), 1)

    def test_conformed_keys_are_homed_on_their_dimensions(self):
        for name, home in (("Date", "DIM_DATE"), ("Machine", "DIM_MACHINE"), ("Plant", "DIM_PLANT")):
            self.assertTrue(self.entity(name)["home"].endswith("/" + home), name)
        plant = {k.split("/")[-1]: c for k, c in self.entity("Plant")["members"].items()}
        self.assertEqual(plant["DIM_PLANT"], "SOURCE_PLANT_ID")
        self.assertEqual(plant["FACT_PRODUCTION_RUNS"], "PLANT_ID")
        self.assertIn("Plant Key", [e["name"] for e in self.inf["entities"]])     # the surrogate says what it is

    def test_a_combined_model_and_one_per_fact_all_pass_the_check(self):
        names = [r["name"] for r in self.recs]
        self.assertEqual(names[0], "Downtime Events, Production Runs and Recycling Intake")
        self.assertIn("Production Runs by Date and Machine", names)
        self.assertTrue(all(r["checked"] for r in self.recs), [r["problems"] for r in self.recs])

    def test_dimension_numbers_describe_and_rates_average(self):
        spec = self.recs[0]["spec"]
        metrics = {m["name"]: m for m in spec["metrics"]}
        attrs = {a["name"] for a in spec["attributes"]}
        for col in ("Calendar Month", "Calendar Year", "Is Weekend"):
            self.assertIn(col, attrs); self.assertNotIn(col, metrics)
        self.assertEqual(metrics["Contamination Pct"]["function"], "avg")
        self.assertEqual(metrics["Units Produced"]["function"], "sum")
        self.assertTrue(all("format" not in m for m in spec["metrics"]))      # the builder formats from name and type
        self.assertTrue({"Plant Name", "Machine Name", "Machine Type"} <= attrs)

    def test_each_table_gets_its_conformed_key(self):
        plan = mp.from_spec(self.recs[0]["spec"], {"tables": list(self.graph["tables"].values())}, {})
        keys = plan["keys"]
        self.assertEqual(keys["DIM_PLANT"], "Plant"); self.assertEqual(keys["DIM_MACHINE"], "Machine"); self.assertEqual(keys["DIM_DATE"], "Date")
        self.assertFalse(mp.errors(mp.check(plan)))


class WarehousePatterns(unittest.TestCase):
    """Patterns met scanning real warehouses, each reduced to a few invented tables."""

    def recs(self, tables, **opts):
        g = {"tables": {f"DS/S/{t['table']}": t for t in tables}, "fks": [], "scopes": []}
        return md.recommend(md.infer(g), opts)

    def test_surrogate_keys_named_sk_join_and_views_of_tables_are_left_out(self):
        fact = table("DS", "Snowflake", "S", "FACT_SHIPMENTS", [("SHIPMENT_SK", N), ("CARRIER_SK", N), ("REVENUE_USD", N)], rows=5000)
        view = table("DS", "Snowflake", "S", "FACT_SHIPMENTS_V", [("SHIPMENT_SK", N), ("CARRIER_SK", N), ("REVENUE_USD", N)], rows=None)
        dim = table("DS", "Snowflake", "S", "DIM_CARRIER", [("CARRIER_SK", N), ("CARRIER_NAME", T), ("FLEET_SIZE", N)], rows=90)
        recs = self.recs([fact, view, dim])
        self.assertTrue(recs and all("FACT_SHIPMENTS_V" not in r["tables"] for r in recs))
        carrier = next(a for a in recs[0]["spec"]["attributes"] if a["name"] == "Carrier")
        self.assertEqual({f["table"] for f in carrier["forms"]}, {"FACT_SHIPMENTS", "DIM_CARRIER"})
        self.assertIn("Fleet Size", [a["name"] for a in recs[0]["spec"]["attributes"]])     # a dimension's number describes it

    def test_alternate_keys_of_one_dimension_are_one_attribute(self):
        dim = table("DS", "Snowflake", "S", "DIM_STORE", [("STORE_KEY", N), ("STORE_NUMBER", N), ("CITY", T)], rows=500)
        fact = table("DS", "Snowflake", "S", "FACT_SALES", [("STORE_KEY", N), ("STORE_NUMBER", N), ("NET_SALES", N)], rows=90000)
        spec = self.recs([dim, fact])[0]["spec"]
        stores = [a for a in spec["attributes"] if a["name"].startswith("Store")]
        self.assertEqual(len(stores), 1)
        forms = {(f["name"], f["column"]) for f in stores[0]["forms"]}
        self.assertIn(("ID", "STORE_NUMBER"), forms); self.assertIn(("Key", "STORE_KEY"), forms)
        plan = mp.from_spec(spec, {"tables": [dim, fact]}, {})
        self.assertEqual(plan["keys"]["DIM_STORE"], stores[0]["name"])

    def test_a_star_joins_on_shared_columns_without_key_suffixes(self):
        dim = table("DS", "Snowflake", "S", "DIM_LOAN", [("LOAN", T), ("GRADE", T)], rows=100)
        dates = table("DS", "Snowflake", "S", "DIM_DATE", [("SNAPSHOT_DATE", D), ("YEAR", N), ("MONTH_NUM", N)], rows=36)
        fact = table("DS", "Snowflake", "S", "FACT_LOAN_HISTORY", [("LOAN", T), ("SNAPSHOT_DATE", D), ("CURRENT_BALANCE", N)], rows=5000)
        recs = self.recs([dim, dates, fact])
        self.assertTrue(recs)
        self.assertEqual(set(recs[0]["tables"]), {"DIM_LOAN", "DIM_DATE", "FACT_LOAN_HISTORY"})
        self.assertTrue(recs[0]["checked"], recs[0]["problems"])

    def test_dimensions_mappings_and_lookups_are_not_facts(self):
        dim = table("DS", "Snowflake", "S", "DIM_LANE", [("LANE_ID", N), ("DISTANCE_MILES", N)], rows=400)
        mapping = table("DS", "Snowflake", "S", "DATE_VIEW_MAPPING", [("LANE_ID", N), ("DAY_NUMBER", N)], rows=400)
        fact = table("DS", "Snowflake", "S", "FACT_LOADS", [("LANE_ID", N), ("REVENUE", N)], rows=9000)
        self.assertEqual([r["fact"] for r in self.recs([dim, mapping, fact])], ["FACT_LOADS"])

    def test_a_key_without_its_own_table_lives_on_a_dimension_not_a_fact(self):
        cust = table("DS", "Snowflake", "S", "FSI_CUSTOMER", [("CUSTOMER_ID", N), ("DUNS_NUMBER", N), ("SEGMENT", T)], rows=900)
        acct = table("DS", "Snowflake", "S", "FSI_ACCOUNTS", [("ACCOUNT_ID", N), ("CUSTOMER_ID", N), ("DUNS_NUMBER", N), ("BALANCE_USD", N)], rows=1400)
        loans = table("DS", "Snowflake", "S", "FSI_LOANS", [("LOAN_ID", N), ("CUSTOMER_ID", N), ("DUNS_NUMBER", N), ("AMOUNT_USD", N)], rows=700)
        g = {"tables": {f"DS/S/{t['table']}": t for t in (cust, acct, loans)}, "fks": [], "scopes": []}
        duns = next(e for e in md.infer(g)["entities"] if e["name"] == "Duns")
        self.assertEqual(duns["home"], "DS/S/FSI_CUSTOMER")
        self.assertTrue(all(r["checked"] for r in md.recommend(md.infer(g))))

    def test_a_measured_unique_key_decides_the_home(self):
        a = table("DS", "Snowflake", "S", "PROVIDER_STATUS", [("PROVIDER_ID", N), ("STATUS", T)], rows=48000)
        b = table("DS", "Snowflake", "S", "PROVIDER_NAMES", [("PROVIDER_ID", N), ("CITY", T)], rows=41000)
        f = table("DS", "Snowflake", "S", "REFERRALS", [("PROVIDER_ID", N), ("REFERRAL_COUNT", N)], rows=6000)
        g = {"tables": {f"DS/S/{t['table']}": t for t in (a, b, f)}, "fks": [], "scopes": [],
             "profile": {"DS/S/PROVIDER_STATUS": {"measured": True, "rows": 48000, "distinct": {"PROVIDER_ID": 41000}, "nulls": {}},
                         "DS/S/PROVIDER_NAMES": {"measured": True, "rows": 41000, "distinct": {"PROVIDER_ID": 41000}, "nulls": {}}}}
        provider = next(e for e in md.infer(g)["entities"] if e["name"] == "Provider")
        self.assertEqual(provider["home"], "DS/S/PROVIDER_NAMES")
