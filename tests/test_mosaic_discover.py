import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _hermetic  # noqa: E402,F401  (scrub MSTR_*/proxy env, private secret store)

# The model recommender's pure steps (infer, recommend) on an invented catalog: a Snowflake retail dataset with declared
# keys, an unrelated Snowflake dataset that reuses CUSTOMER_ID, and a Postgres table that really belongs to the first.
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
        self.assertEqual({f["column"] for f in customer["forms"] if f["category"] == "ID"}, {"CUSTOMER_ID", "customer_id"})   # one attribute across stores
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
        self.assertTrue({"Machine Type", "Country"} <= attrs)
        named = {a["name"]: f["column"] for a in spec["attributes"] for f in a["forms"] if f["category"] == "DESC"}
        self.assertEqual(named.get("Machine"), "MACHINE_NAME"); self.assertEqual(named.get("Plant"), "PLANT_NAME")   # names are name forms
        forms = {a["name"]: {f["column"] for f in a["forms"]} for a in spec["attributes"]}
        self.assertNotIn("Plant Key", forms); self.assertNotIn("Machine Key", forms)         # surrogates are forms of their key
        self.assertIn("PLANT_KEY", forms["Plant"]); self.assertIn("MACHINE_KEY", forms["Machine"])
        self.assertTrue(spec["description"].startswith("Downtime Events, Production Runs and Recycling Intake, by "))

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


class PartialExtensionFacts(unittest.TestCase):
    """Found in a live proof: a fact unique on a shared dimension's key but covering only some of it (4,000 certified
    sales over 10,000 vehicles) must not be keyed by it, or other facts break down by its attributes and lose rows."""

    def test_a_fact_covering_part_of_a_dimension_is_not_keyed_by_it(self):
        V, C, W = (table("DS", "Snowflake", "S", n, cols) for n, cols in (
            ("DIM_VEHICLE", [("VEHICLE_ID", N), ("MODEL", T)]),
            ("FCT_CPO_SALES", [("VEHICLE_ID", N), ("CPO_SALE_DATE", D), ("CPO_GROSS_PROFIT", N)]),
            ("FCT_WARRANTY_CLAIM", [("CLAIM_ID", N), ("VEHICLE_ID", N), ("DAYS_TO_PAY", N)])))
        spec = mp.spec_from_tables({"tables": [V, C, W]}, {}, "x", entities=[{"name": "Vehicle", "home": "DIM_VEHICLE",
            "members": [("DIM_VEHICLE", "VEHICLE_ID"), ("FCT_CPO_SALES", "VEHICLE_ID"), ("FCT_WARRANTY_CLAIM", "VEHICLE_ID")]}])
        prof = {"DIM_VEHICLE": {"measured": True, "rows": 10000, "distinct": {"VEHICLE_ID": 10000}, "nulls": {}},
                "FCT_CPO_SALES": {"measured": True, "rows": 4000, "distinct": {"VEHICLE_ID": 4000, "CPO_SALE_DATE": 705}, "nulls": {}},
                "FCT_WARRANTY_CLAIM": {"measured": True, "rows": 20000, "distinct": {"CLAIM_ID": 20000, "VEHICLE_ID": 9000}, "nulls": {}}}
        plan = mp.from_spec(spec, {"tables": [V, C, W]}, prof)
        self.assertNotIn("FCT_CPO_SALES", plan["keys"])
        self.assertFalse(any(r["table"] == "FCT_CPO_SALES" for r in plan["relationships"]))
        # covering every vehicle, it is a one-to-one extension and keeps the key
        prof["FCT_CPO_SALES"]["distinct"]["VEHICLE_ID"] = prof["FCT_CPO_SALES"]["rows"] = 10000
        self.assertEqual(mp.from_spec(spec, {"tables": [V, C, W]}, prof)["keys"].get("FCT_CPO_SALES"), "Vehicle")


class ReferenceTests(unittest.TestCase):
    """the person's references (ERDs, dictionaries, catalog and MDM exports, documents) inform the recommendations"""

    def refs(self, a):
        return [{"name": "orders.dbml", "kind": "erd", "relationships": [
                    {"parent": "shopa_refunds_lookup.id", "child": "nowhere.id"},                         # tables not scanned: ignored
                    {"parent": f"{a}CUSTOMERS.customer_id", "child": "shopa_refunds.customer_id"}]},       # case differs from the columns
                {"name": "catalog.json", "kind": "data", "text": f"{a}CALENDAR is the fiscal calendar.",
                 "dictionary": {"attributes": {f"{a}CUSTOMERS.CUSTOMER_ID": {"name": "Shopper", "description": "A registered shopper"}},
                                "metrics": {f"{a}ORDERS.AMOUNT": {"name": "Order Value", "description": "Net order value in USD"}}}}]

    def test_a_reference_relationship_is_a_declared_key_across_stores(self):
        g, a, _ = graph()
        ref = md.apply_references(g, self.refs(a))
        added = [f for f in ref["fks"] if f.get("name") == "reference: orders.dbml"]
        self.assertEqual(added, [{"child": "PG/p/shopa_refunds", "child_cols": ["customer_id"], "parent": f"SF/S/{a}CUSTOMERS",
                                  "parent_cols": ["CUSTOMER_ID"], "name": "reference: orders.dbml"}])
        l = link(md.infer(ref), a + "CUSTOMERS", "shopa_refunds")
        self.assertIn("declared", l["evidence"])
        self.assertEqual(len(g["fks"]), 2)                                  # the scanned graph itself is not changed

    def test_tables_named_in_references_are_marked_and_their_recommendations_say_so(self):
        g, a, _ = graph()
        ref = md.apply_references(g, self.refs(a))
        self.assertEqual(ref["referenced"][f"SF/S/{a}CALENDAR"], ["catalog.json"])                  # named in the text
        self.assertEqual(ref["referenced"][f"SF/S/{a}CUSTOMERS"], ["orders.dbml", "catalog.json"])
        opts = {"referenced": ref["referenced"], "dictionary": ref["dictionary"]}
        plain = {r["name"]: r for r in md.recommend(md.infer(ref), {})}
        recs = md.recommend(md.infer(ref), opts)
        rec = next(r for r in recs if any(t.endswith("ORDERS") for t in r["tables"]))
        self.assertIn("described in your references", rec["reasons"][-1])
        self.assertGreater(rec["score"], plain[rec["name"]]["score"])
        self.assertEqual(rec["references"], ["catalog.json", "orders.dbml"])

    def test_dictionaries_name_and_describe_the_draft(self):
        g, a, _ = graph()
        ref = md.apply_references(g, self.refs(a))
        recs = md.recommend(md.infer(ref), {"referenced": ref["referenced"], "dictionary": ref["dictionary"]})
        spec = next(r for r in recs if any(t.endswith("ORDERS") for t in r["tables"]))["spec"]
        metric = next(m for m in spec["metrics"] if m["column"] == "AMOUNT")
        self.assertEqual((metric["name"], metric["description"]), ("Order Value", "Net order value in USD"))
        shopper = next(x for x in spec["attributes"] if any(f["column"] == "CUSTOMER_ID" for f in x["forms"]))
        self.assertEqual((shopper["name"], shopper["description"]), ("Shopper", "A registered shopper"))

    def test_an_ambiguous_table_name_is_not_guessed(self):
        g, a, _ = graph()
        twin = dict(g["tables"][f"SF/S/{a}CUSTOMERS"], schema="S2")
        g["tables"][md.tkey(twin)] = twin
        ref = md.apply_references(g, self.refs(a))
        self.assertFalse([f for f in ref["fks"] if f.get("name")])
        self.assertNotIn(f"SF/S/{a}CUSTOMERS", ref["referenced"])


class TimestampTests(unittest.TestCase):
    def test_a_fact_timestamp_is_a_time_attribute(self):
        """Strategy's catalog types timestamps as time_stamp; they were left out, so a downtime model's only date was the
        machine's commissioned date (seen live 2026-10-22)"""
        ts = [table("SF", "Snowflake", "M", "DIM_MACHINE", [("MACHINE_CODE", T), ("COMMISSIONED_DATE", D), ("MACHINE_TYPE", T)], ["MACHINE_CODE"], 70),
              table("SF", "Snowflake", "M", "FACT_DOWNTIME_EVENTS", [("EVENT_ID", N), ("MACHINE_CODE", T), ("EVENT_START", {"type": "time_stamp"}),
                                                                     ("DURATION_MINS", {"type": "int64"})], ["EVENT_ID"], 15000)]
        g = {"tables": {md.tkey(t): t for t in ts}, "fks": []}
        rec = md.recommend(md.infer(g), {})[0]
        start = next(a for a in rec["spec"]["attributes"] if any(f["column"] == "EVENT_START" for f in a["forms"]))
        self.assertTrue(start.get("time", True))
        self.assertEqual(start["name"], "Event Start")


class AggregationNameTests(unittest.TestCase):
    def test_averages_are_read_from_whole_words(self):
        """"ratio" inside DURATION_MINS made downtime minutes an average (seen live 2026-10-22)"""
        for name, avg in [("DURATION_MINS", False), ("DURATION", False), ("RATEPLAN_ID", False), ("CONVERSION_RATE", True),
                          ("AVG_PRICE", True), ("MARGIN_PCT", True), ("yield", True)]:
            self.assertIs(bool(mp.AVERAGED.search(name)), avg, name)

    def test_downtime_minutes_add_up(self):
        ts = [table("SF", "Snowflake", "M", "DIM_MACHINE", [("MACHINE_CODE", T), ("MACHINE_TYPE", T)], ["MACHINE_CODE"], 70),
              table("SF", "Snowflake", "M", "FACT_DOWNTIME_EVENTS", [("EVENT_ID", N), ("MACHINE_CODE", T), ("DURATION_MINS", {"type": "int64"}),
                                                                     ("ConversionRate", {"type": "double"})], ["EVENT_ID"], 100)]
        g = {"tables": {md.tkey(t): t for t in ts}, "fks": []}
        spec = md.recommend(md.infer(g), {})[0]["spec"]
        fn = {m["column"]: m["function"] for m in spec["metrics"]}
        self.assertEqual(fn, {"DURATION_MINS": "sum", "ConversionRate": "avg"})


class SearchedSubsetTests(unittest.TestCase):
    def test_tables_picked_from_a_large_schema_are_not_one_small_dataset(self):
        """seen live: 7 tables picked by a search from a 129-table schema were read as one small dataset, so a shared
        ACCOUNT_ID joined unrelated datasets and every breakdown across them came back empty"""
        ts = [table("SF", "Snowflake", "PUBLIC", "ATTTZ", [("ACCOUNT_ID", T), ("APR", {"type": "double"}), ("AUTOPAY_ENABLED", N)], [], 500),
              table("SF", "Snowflake", "PUBLIC", "SAAS_DIM_ACCOUNT", [("ACCOUNT_ID", T), ("SEGMENT", T)], [], 300),
              table("SF", "Snowflake", "PUBLIC", "SAAS_FACT_SUBSCRIPTIONS", [("SUB_ID", N), ("ACCOUNT_ID", T), ("MRR", {"type": "double"})], [], 900)]
        g = {"tables": {md.tkey(t): t for t in ts}, "fks": [], "schema_sizes": {"SF/PUBLIC": 129}}
        inf = md.infer(g)
        self.assertIsNone(next((l for l in inf["links"] if {l["from"], l["to"]} == {"SF/PUBLIC/ATTTZ", "SF/PUBLIC/SAAS_DIM_ACCOUNT"}
                                and l["confidence"] >= 0.5), None))
        small = md.infer({**g, "schema_sizes": {"SF/PUBLIC": 3}})        # the same three tables as a whole small schema: one dataset
        self.assertTrue(any(l["confidence"] >= 0.5 for l in small["links"]))

    def test_rates_average_and_flags_are_attributes(self):
        self.assertTrue(mp.AVERAGED.search("APR"))
        self.assertTrue(mp.DESCRIPTIVE_NUMBER.search("AUTOPAY_ENABLED"))


class TechnicalKeyTests(unittest.TestCase):
    def test_load_bookkeeping_is_never_a_join_key(self):
        """seen live: "Company by Etl Batch" joined two tables on ETL_BATCH_ID"""
        ts = [table("SF", "Snowflake", "INS", "DIM_COMPANY", [("COMPANY_ID", N), ("ETL_BATCH_ID", N), ("NAME", T)], ["COMPANY_ID"], 50),
              table("SF", "Snowflake", "INS", "FACT_COVERAGE", [("COVERAGE_ID", N), ("COMPANY_ID", N), ("ETL_BATCH_ID", N), ("PREMIUM", {"type": "double"})], ["COVERAGE_ID"], 900)]
        inf = md.infer({"tables": {md.tkey(t): t for t in ts}, "fks": []})
        self.assertFalse([l for l in inf["links"] if "ETL_BATCH_ID" in l["columns"]])
        self.assertTrue([l for l in inf["links"] if "COMPANY_ID" in l["columns"]])


class StructuralEvidenceTests(unittest.TestCase):
    """joins judged from metadata the databases keep: types, statistics, who owns a key, history tables, flat tables"""

    def g(self, *ts, **extra):
        return {"tables": {md.tkey(t): t for t in ts}, "fks": [], **extra}

    def link(self, inf, a, b):
        return next((l for l in inf["links"] if {l["from"].split("/")[-1], l["to"].split("/")[-1]} == {a, b}), None)

    def test_a_number_never_joins_a_date_and_mismatched_text_keys_do_not_join(self):
        ts = [table("PG", "PostgreSQL", "s", "DIM_STORE", [("STORE_CODE", {"type": "utf8_char", "precision": 5}), ("NAME", T)], ["STORE_CODE"]),
              table("PG", "PostgreSQL", "s", "FACT_SALES", [("SALE_ID", N), ("STORE_CODE", {"type": "utf8_char", "precision": 36}), ("AMOUNT", {"type": "double"})], ["SALE_ID"])]
        self.assertIsNone(self.link(md.infer(self.g(*ts)), "DIM_STORE", "FACT_SALES"))
        ts[1]["columns"][1]["dataType"] = {"type": "utf8_char", "precision": 5}
        self.assertIsNotNone(self.link(md.infer(self.g(*ts)), "DIM_STORE", "FACT_SALES"))

    def test_statistics_prove_a_key_or_end_a_link(self):
        ts = [table("PG", "PostgreSQL", "s", "ACCOUNTS", [("ACCOUNT_ID", N), ("REGION", T)], [], 100),
              table("PG", "PostgreSQL", "s", "PAYMENTS", [("PAYMENT_ID", N), ("ACCOUNT_ID", N), ("AMOUNT", {"type": "double"})], ["PAYMENT_ID"], 1000)]
        st = lambda lo, hi, rows, d: {"rows": rows, "distinct": d, "nulls": 0, "values": [], "low": lo, "high": hi}  # noqa: E731
        agree = {"PG/s/ACCOUNTS": {"ACCOUNT_ID": st("1", "100", 100, 100)}, "PG/s/PAYMENTS": {"ACCOUNT_ID": st("3", "98", 1000, 90)}}
        l = self.link(md.infer(self.g(*ts, stats=agree)), "ACCOUNTS", "PAYMENTS")
        self.assertIn("statistics", l["evidence"])
        apart = {"PG/s/ACCOUNTS": {"ACCOUNT_ID": st("1", "100", 100, 100)}, "PG/s/PAYMENTS": {"ACCOUNT_ID": st("5000", "9000", 1000, 90)}}
        self.assertIsNone(self.link(md.infer(self.g(*ts, stats=apart)), "ACCOUNTS", "PAYMENTS"))

    def test_two_tables_sharing_a_key_neither_owns_do_not_join(self):
        ts = [table("SF", "Snowflake", "S", "FACT_ORDERS", [("ORDER_ID", N), ("ACCOUNT_ID", N), ("AMOUNT", {"type": "double"})], ["ORDER_ID"]),
              table("SF", "Snowflake", "S", "FACT_TICKETS", [("TICKET_ID", N), ("ACCOUNT_ID", N), ("MINUTES", {"type": "double"})], ["TICKET_ID"])]
        l = self.link(md.infer(self.g(*ts)), "FACT_ORDERS", "FACT_TICKETS")
        self.assertTrue(l is None or l["confidence"] < 0.5)

    def test_a_history_dimension_is_joined_on_its_surrogate_key_only(self):
        dim = table("SF", "Snowflake", "S", "DIM_CUSTOMER", [("CUSTOMER_SK", N), ("CUSTOMER_ID", N), ("NAME", T), ("VALID_FROM", D), ("VALID_TO", D), ("IS_CURRENT", N)], ["CUSTOMER_SK"])
        fact = table("SF", "Snowflake", "S", "FACT_ORDERS", [("ORDER_ID", N), ("CUSTOMER_ID", N), ("AMOUNT", {"type": "double"})], ["ORDER_ID"])
        l = self.link(md.infer(self.g(dim, fact)), "DIM_CUSTOMER", "FACT_ORDERS")
        self.assertTrue(l is None or l["confidence"] < 0.5)
        fact["columns"].append({"name": "CUSTOMER_SK", "dataType": N})
        self.assertGreaterEqual(self.link(md.infer(self.g(dim, fact)), "DIM_CUSTOMER", "FACT_ORDERS")["confidence"], 0.5)

    def test_part_of_a_composite_key_is_not_a_unique_key(self):
        lines = table("PG", "PostgreSQL", "s", "ORDER_LINES", [("ORDER_ID", N), ("LINE_NO", N), ("QTY", N)], ["ORDER_ID", "LINE_NO"])
        orders = table("PG", "PostgreSQL", "s", "ORDERS", [("ORDER_ID", N), ("ORDER_DATE", D), ("CHANNEL", T)], ["ORDER_ID"])
        inf = md.infer(self.g(lines, orders))
        order = next(e for e in inf["entities"] if e["name"] == "Order")
        self.assertTrue(order["home"].endswith("/ORDERS"))

    def test_a_wide_flat_table_is_a_model_on_its_own(self):
        flat = table("SF", "Snowflake", "S", "SALES_EXTRACT", [("REGION", T), ("STORE", T), ("PRODUCT", T), ("ORDER_DATE", D), ("CHANNEL", T), ("SEGMENT", T),
                                                               ("SALES_AMOUNT", {"type": "double"}), ("QUANTITY", N)], [], 5000)
        recs = md.recommend(md.infer(self.g(flat)), {})
        self.assertEqual([r["kind"] for r in recs], ["flat"])
        self.assertTrue(any("wide table" in x for x in recs[0]["reasons"]))

    def test_each_recommendation_says_how_its_joins_are_known(self):
        g, a, _ = graph()
        recs = md.recommend(md.infer(g), {})
        rec = next(r for r in recs if any(t.endswith("ORDERS") for t in r["tables"]))
        self.assertEqual(sum(rec["joins"].values()), rec["joins"]["declared"] + rec["joins"]["data"] + rec["joins"]["statistics"] + rec["joins"]["name"])
        self.assertGreaterEqual(rec["joins"]["declared"], 1)


class MetadataOnlyRecommendationTests(unittest.TestCase):
    """Adversarial metadata, no source-table queries: preserve recall without inventing join/rollup guarantees."""

    def graph(self, *tables, **extra):
        return {"tables": {md.tkey(t): t for t in tables}, "fks": [], **extra}

    def dim(self, ds="A", schema="s", name="DIM_CUSTOMER"):
        return table(ds, "PostgreSQL", schema, name, [("CUSTOMER_ID", N), ("CUSTOMER_NAME", T)], ["CUSTOMER_ID"])

    def fact(self, ds="A", schema="s", name="FACT_ORDERS"):
        return table(ds, "PostgreSQL", schema, name, [("ORDER_ID", N), ("CUSTOMER_ID", N), ("AMOUNT", N)], ["ORDER_ID"], 1000)

    def test_catalog_rows_form_one_ordered_composite_fk_with_parent_schema(self):
        from types import SimpleNamespace
        rows = [{"t": "FACT_LINES", "c": "ITEM_ID", "k": "FOREIGN KEY", "pt": "DIM_ITEMS", "pc": "ITEM_ID", "ps": "lookup", "n": "item_fk", "o": 2},
                {"t": "FACT_LINES", "c": "TENANT_ID", "k": "FOREIGN KEY", "pt": "DIM_ITEMS", "pc": "TENANT_ID", "ps": "lookup", "n": "item_fk", "o": 1}]
        _, fks = md._declared_keys(None, SimpleNamespace(run_sql=lambda *args: rows), {"id": "A", "dbms": "PostgreSQL"}, "sales", {"FACT_LINES"})
        self.assertEqual(len(fks), 1)
        self.assertEqual(fks[0]["child_cols"], ["TENANT_ID", "ITEM_ID"])
        self.assertEqual(fks[0]["parent_cols"], ["TENANT_ID", "ITEM_ID"])
        self.assertEqual(fks[0]["parent_schema"], "lookup")

    def test_ambiguous_catalog_cross_product_is_not_independent_single_keys(self):
        from types import SimpleNamespace
        rows = [{"t": "F", "c": c, "k": "FOREIGN KEY", "pt": "D", "pc": pc, "n": "compound"}
                for c in ("TENANT_ID", "ITEM_ID") for pc in ("TENANT_ID", "ITEM_ID")]
        _, fks = md._declared_keys(None, SimpleNamespace(run_sql=lambda *args: rows), {"id": "A", "dbms": "PostgreSQL"}, "s", {"F", "D"})
        self.assertEqual(len(fks), 1)
        self.assertTrue(fks[0]["ambiguous_columns"])

    def test_composite_join_remains_visible_without_unsafe_component_conformance(self):
        dim = table("A", "PostgreSQL", "s", "DIM_ITEM", [("TENANT_ID", N), ("ITEM_ID", N), ("NAME", T)], ["TENANT_ID", "ITEM_ID"])
        fact = table("A", "PostgreSQL", "s", "FACT_LINES", [("LINE_ID", N), ("TENANT_ID", N), ("ITEM_ID", N), ("AMOUNT", N)], ["LINE_ID"])
        g = self.graph(dim, fact, fks=[{"parent": md.tkey(dim), "child": md.tkey(fact), "parent_cols": ["TENANT_ID", "ITEM_ID"], "child_cols": ["TENANT_ID", "ITEM_ID"]}])
        inf = md.infer(g)
        self.assertEqual(len(inf["links"]), 1)
        self.assertEqual(inf["links"][0]["column_pairs"], [["TENANT_ID", "TENANT_ID"], ["ITEM_ID", "ITEM_ID"]])
        rec = md.recommend(inf)[0]
        self.assertEqual(set(rec["tables"]), {"DIM_ITEM", "FACT_LINES"})
        self.assertFalse(rec["checked"])
        self.assertTrue(any("composite" in p for p in rec["problems"]))
        self.assertFalse(any(len({f["table"] for f in a["forms"] if f["category"] == "ID"}) > 1 for a in rec["spec"]["attributes"]))

    def test_partial_composite_parent_key_never_becomes_unique_from_its_name(self):
        dim = self.dim()
        dim["columns"].append({"name": "REGION_ID", "dataType": N})
        dim["pk"] = ["CUSTOMER_ID", "REGION_ID"]
        inf = md.infer(self.graph(dim, self.fact()))
        self.assertTrue(all(l["confidence"] < 0.5 for l in inf["links"]))

    def test_two_foreign_key_roles_are_retained_and_require_aliases(self):
        dim = table("A", "PostgreSQL", "s", "DIM_DATE", [("DATE_ID", N), ("CALENDAR_DATE", D)], ["DATE_ID"])
        fact = table("A", "PostgreSQL", "s", "FACT_ORDERS", [("ORDER_ID", N), ("ORDER_DATE_ID", N), ("SHIP_DATE_ID", N), ("AMOUNT", N)], ["ORDER_ID"])
        fks = [{"parent": md.tkey(dim), "child": md.tkey(fact), "parent_cols": ["DATE_ID"], "child_cols": [c]} for c in ("ORDER_DATE_ID", "SHIP_DATE_ID")]
        inf = md.infer(self.graph(dim, fact, fks=fks))
        self.assertEqual({tuple(l["columns"]) for l in inf["links"] if l.get("role_playing")}, {("DATE_ID", "ORDER_DATE_ID"), ("DATE_ID", "SHIP_DATE_ID")})
        rec = md.recommend(inf)[0]
        self.assertFalse(rec["checked"])
        self.assertTrue(any("aliases" in p for p in rec["problems"]))
        self.assertTrue({"Order Date", "Ship Date"} <= {a["name"] for a in rec["spec"]["attributes"]})

    def test_related_or_partitioned_tables_are_not_treated_as_copies(self):
        base = self.fact()
        siblings = [dict(base, table=n) for n in ("FACT_ORDERS_RETURNS", "FACT_ORDERS_2026", "FACT_ORDERS2", "FACT_ORDERS_NEW")]
        g = self.graph(base, *siblings)
        self.assertEqual(md.view_copies(g["tables"]), set())

    def test_explicit_selected_view_is_not_dropped(self):
        dim, fact = self.dim(), self.fact()
        view = dict(fact, table="FACT_ORDERS_V")
        g = self.graph(dim, fact, view, selected_tables=[md.tkey(view)])
        inf = md.infer(g)
        self.assertIn(md.tkey(view), inf["tables"])
        self.assertTrue(any("FACT_ORDERS_V" in r["tables"] for r in md.recommend(inf)))

    def test_strict_draft_does_not_recreate_rejected_name_join(self):
        dim, fact = self.dim(), self.fact()
        for t in (dim, fact):
            t["columns"].append({"name": "REGION_ID", "dataType": N})
        spec = mp.spec_from_tables({"tables": [dim, fact]}, entities=[{"name": "Region", "home": dim["table"],
                                  "members": [(dim["table"], "REGION_ID"), (fact["table"], "REGION_ID")]}], strict_entities=True)
        customer = [a for a in spec["attributes"] if any(f["column"] == "CUSTOMER_ID" for f in a["forms"])]
        self.assertEqual(len(customer), 2)
        self.assertTrue(all(len({f["table"] for f in a["forms"]}) == 1 for a in customer))

    def test_one_unambiguous_named_dimension_proposes_metadata_cross_store_model(self):
        g = self.graph(self.dim("A"), self.fact("B"))
        inf = md.infer(g)
        self.assertTrue(any("metadata_conformance" in l["evidence"] for l in inf["links"]))
        rec = md.recommend(inf, {"cross_store": "prefer"})[0]
        self.assertTrue(rec["cross_store"])
        self.assertEqual(rec["stores"], ["PostgreSQL"])
        self.assertEqual(rec["semantic_status"], "needs_review")
        self.assertTrue(any("parent uniqueness" in w for w in rec["spec"]["notes"]))
        self.assertFalse(any("without moving" in r for r in rec["reasons"]))
        att = next(a for a in rec["spec"]["attributes"] if a["name"] == "Customer")
        self.assertEqual({f["table"] for f in att["forms"] if f["category"] == "ID"}, {"DIM_CUSTOMER", "FACT_ORDERS"})

    def test_two_independent_dimension_homes_do_not_guess_cross_store_conformance(self):
        g = self.graph(self.dim("A"), self.dim("B", name="DIM_OTHER_CUSTOMER"), self.fact("C"))
        self.assertFalse(any("metadata_conformance" in l["evidence"] for l in md.infer(g)["links"]))

    def test_named_domains_do_not_conform_just_because_one_owns_the_key(self):
        g = self.graph(self.dim("A", name="CRM_DIM_CUSTOMER"), self.fact("B", name="SUPPORT_FACT_ORDERS"))
        self.assertTrue(all(l["confidence"] < 0.5 for l in md.infer(g)["links"]))

    def test_snowflake_path_keeps_all_parent_dimensions(self):
        country = table("A", "PostgreSQL", "s", "DIM_COUNTRY", [("COUNTRY_ID", N), ("COUNTRY_NAME", T)], ["COUNTRY_ID"])
        customer, fact = self.dim(), self.fact()
        customer["columns"].append({"name": "COUNTRY_ID", "dataType": N})
        rec = md.recommend(md.infer(self.graph(country, customer, fact)))[0]
        self.assertEqual(set(rec["tables"]), {"DIM_COUNTRY", "DIM_CUSTOMER", "FACT_ORDERS"})
        self.assertTrue(rec["checked"], rec["problems"])
        self.assertTrue(any(f["column"] == "COUNTRY_NAME" for a in rec["spec"]["attributes"] for f in a["forms"]))

    def test_identical_dimensions_preserve_each_star_and_all_combined_joins(self):
        first, second = self.fact(), self.fact(name="FACT_RETURNS")
        second["columns"][0]["name"] = "RETURN_ID"
        second["pk"] = ["RETURN_ID"]
        recs = md.recommend(md.infer(self.graph(self.dim(), first, second)))
        self.assertEqual(len([r for r in recs if r["kind"] == "star"]), 2)
        combined = next(r for r in recs if r["kind"] == "combined")
        customer = next(a for a in combined["spec"]["attributes"] if a["name"] == "Customer")
        self.assertEqual({f["table"] for f in customer["forms"] if f["category"] == "ID"}, {"DIM_CUSTOMER", "FACT_ORDERS", "FACT_RETURNS"})
        self.assertTrue(any("Multiple fact grains" in w for w in combined["semantic_warnings"]))

    def test_measured_nonunique_parent_cannot_be_promoted_by_confirmation(self):
        dim, fact = self.dim(), self.fact()
        g = self.graph(dim, fact, profile={md.tkey(dim): {"measured": True, "rows": 100, "distinct": {"CUSTOMER_ID": 20}, "nulls": {"CUSTOMER_ID": 0}}})
        inf = md.infer(g, curation={"confirmed_links": [[md.tkey(dim), md.tkey(fact)]]})
        self.assertTrue(all(l["confidence"] < 0.5 for l in inf["links"]))

    def test_history_business_key_is_not_rescued_by_overlapping_statistics(self):
        dim, fact = self.dim(), self.fact()
        dim["pk"] = ["CUSTOMER_SK"]
        dim["columns"] += [{"name": c, "dataType": dt} for c, dt in (("CUSTOMER_SK", N), ("VALID_FROM", D), ("VALID_TO", D))]
        stat = {"rows": 100, "distinct": 100, "nulls": 0, "values": ["1"], "low": "1", "high": "100"}
        g = self.graph(dim, fact, stats={md.tkey(t): {"CUSTOMER_ID": stat} for t in (dim, fact)})
        self.assertTrue(all(l["confidence"] < 0.5 for l in md.infer(g)["links"]))

    def test_rates_balances_and_unit_prices_have_explicit_aggregation_review(self):
        dim, fact = self.dim(), self.fact()
        fact["columns"] += [{"name": c, "dataType": N} for c in ("CONVERSION_RATE", "ACCOUNT_BALANCE", "UNIT_PRICE", "REVENUE_YTD")]
        rec = md.recommend(md.infer(self.graph(dim, fact)))[0]
        kinds = {m["column"]: m["additivity"] for m in rec["metric_semantics"]}
        self.assertEqual(kinds["AMOUNT"], "additive-candidate")
        self.assertEqual(kinds["CONVERSION_RATE"], "non-additive")
        self.assertEqual(kinds["ACCOUNT_BALANCE"], "semi-additive")
        self.assertEqual(kinds["REVENUE_YTD"], "semi-additive")
        metric = next(m for m in rec["spec"]["metrics"] if m["column"] == "UNIT_PRICE")
        self.assertEqual(metric["function"], "avg")
        self.assertTrue(any("weighted" in w for w in rec["spec"]["notes"]))
        self.assertTrue(any("must not sum across time" in w for w in rec["spec"]["notes"]))

    def test_dimension_prices_are_descriptors_not_fact_totals(self):
        dim, fact = self.dim(), self.fact()
        dim["columns"].append({"name": "ANNUAL_BUDGET", "dataType": N})
        rec = md.recommend(md.infer(self.graph(dim, fact)))[0]
        self.assertFalse(any(m["table"] == dim["table"] for m in rec["spec"]["metrics"]))
        self.assertTrue(any(f["column"] == "ANNUAL_BUDGET" for a in rec["spec"]["attributes"] for f in a["forms"]))

    def test_table_limit_reports_related_tables_it_dropped(self):
        dim, fact = self.dim(), self.fact()
        region = table("A", "PostgreSQL", "s", "DIM_REGION", [("REGION_ID", N), ("REGION_NAME", T)], ["REGION_ID"])
        dim["columns"].append({"name": "REGION_ID", "dataType": N})
        rec = md.recommend(md.infer(self.graph(dim, region, fact)), {"max_tables": 2})[0]
        self.assertEqual(rec["omitted_related_tables"], [{"table_key": md.tkey(region), "table": "DIM_REGION", "reason": "table_limit"}])

    def test_duplicate_source_table_names_fail_instead_of_silently_overwriting(self):
        dim, fact = self.dim(), self.fact()
        copy = dict(dim, datasource="B", datasource_id="B")
        with self.assertRaisesRegex(mp.PlanError, "aliases"):
            mp.from_spec(mp.spec_from_tables({"tables": [dim, copy, fact]}), {"tables": [dim, copy, fact]})

    def test_schema_qualified_references_resolve_duplicate_names(self):
        dim, other, fact = self.dim(schema="lookup"), self.dim(schema="archive"), self.fact(schema="sales")
        g = md.apply_references(self.graph(dim, other, fact), [{"name": "model contract", "relationships": [
            {"parent": "A.lookup.DIM_CUSTOMER.CUSTOMER_ID", "child": "A.sales.FACT_ORDERS.CUSTOMER_ID"}]}])
        self.assertEqual([(fk["parent"], fk["child"]) for fk in g["fks"]], [(md.tkey(dim), md.tkey(fact))])

    def test_scan_cli_defaults_to_metadata_only(self):
        import tempfile
        from unittest.mock import patch
        import mosaic_live
        with tempfile.TemporaryDirectory() as tmp:
            argv = ["mosaic_discover.py", "scan", "--source", "A:s:*", "--out", os.path.join(tmp, "graph.json")]
            with patch.object(sys, "argv", argv), patch.object(mosaic_live, "sign_in_from_env", return_value=object()), \
                    patch.object(md, "scan", return_value={"tables": {}, "fks": []}), patch.object(md, "catalog_stats"), \
                    patch.object(md, "measure_keys", side_effect=AssertionError("must not read table rows")), \
                    patch.object(md, "confirm", side_effect=AssertionError("must not read table rows")):
                self.assertEqual(md.main(), 0)

    def test_scan_retains_other_sources_and_reports_partial_metadata_without_exception_payloads(self):
        from unittest.mock import patch
        import mosaic_live
        import mosaic_matrix
        info = {"id": "A", "name": "Warehouse", "dbms": "PostgreSQL"}
        scopes = [{"datasource": "A", "schema": "offline", "patterns": ["*"]},
                  {"datasource": "A", "schema": "s", "patterns": ["*"]}]
        def listing(m, ds, schema):
            if schema == "offline":
                raise RuntimeError("private error payload must not be retained")
            return ["DIM_CUSTOMER", "FACT_ORDERS"]
        def metadata(m, ds, schema, name):
            if name == "FACT_ORDERS":
                raise RuntimeError("private error payload must not be retained")
            return {"description": "Customer lookup", "columns": [{"name": "CUSTOMER_ID", "dataType": N, "description": "Governed customer key"}]}
        def sql(m, ds, text):
            self.assertNotIn('FROM "s".', text)       # only catalog SQL, never a source-table SELECT
            return []
        with patch.object(mosaic_live, "datasource", return_value=info), patch.object(mosaic_matrix, "list_tables", side_effect=listing), \
                patch.object(mosaic_live.bm, "fetch_table_metadata", side_effect=metadata), patch.object(mosaic_live, "run_sql", side_effect=sql):
            g = md.scan(object(), scopes)
        self.assertEqual(list(g["tables"]), ["A/s/DIM_CUSTOMER"])
        self.assertEqual(g["tables"]["A/s/DIM_CUSTOMER"]["columns"][0]["description"], "Governed customer key")
        self.assertEqual(g["coverage"][0]["tables"], "unavailable")
        self.assertEqual(g["coverage"][1]["columns"], "partial")
        self.assertEqual(g["coverage"][1]["catalog_tables"], 1)
        self.assertEqual({e["stage"] for e in g["errors"]}, {"tables", "columns"})
        self.assertNotIn("private error payload", str(g))

    def test_exactly_requested_backup_name_survives_generic_noise_exclusion(self):
        from unittest.mock import patch
        import mosaic_live
        import mosaic_matrix
        requested = self.fact(name="FACT_ORDERS_BACKUP")
        info = {"id": "A", "name": "Warehouse", "dbms": "PostgreSQL"}
        with patch.object(mosaic_live, "datasource", return_value=info), patch.object(mosaic_matrix, "list_tables", return_value=[requested["table"]]), \
                patch.object(mosaic_live, "run_sql", return_value=[]), patch.object(mosaic_live, "catalog", return_value={"tables": [requested]}) as cat:
            g = md.scan(object(), [{"datasource": "A", "schema": "s", "patterns": [requested["table"]]}])
        self.assertEqual(g["selected_tables"], [md.tkey(requested)])
        self.assertEqual(cat.call_args[0][1][0]["table"], requested["table"])

    def test_catalog_comments_identify_aggregation_risk_without_changing_metric_contract(self):
        dim, fact = self.dim(), self.fact()
        fact["columns"][2]["description"] = "Closing account balance at the end of each month"
        rec = md.recommend(md.infer(self.graph(dim, fact)))[0]
        self.assertEqual(rec["metric_semantics"][0]["additivity"], "semi-additive")
        self.assertTrue(any("end-of-period" in n for n in rec["spec"]["notes"]))

    def test_find_cli_reads_vocabulary_file_at_the_real_boundary(self):
        import json
        import tempfile
        from unittest.mock import patch
        import mosaic_live
        import mosaic_find
        vocabulary = {"aliases": [["customer", "cust"]], "domains": [{"name": "commerce", "terms": ["order", "invoice"]}]}
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "vocabulary.json")
            with open(path, "w") as handle:
                json.dump(vocabulary, handle)
            argv = ["mosaic_discover.py", "find", "--query", "customer orders", "--search-options", path, "--out", os.path.join(tmp, "found.json")]
            with patch.object(sys, "argv", argv), patch.object(mosaic_live, "sign_in_from_env", return_value=object()), \
                    patch.object(mosaic_find, "find", return_value={"picked": [], "candidates": 0, "read": [], "left": []}) as find:
                self.assertEqual(md.main(), 0)
            self.assertEqual(find.call_args.kwargs["search_options"], vocabulary)

    def test_scan_cli_structured_scopes_preserve_identifier_delimiters(self):
        import json
        import tempfile
        from unittest.mock import patch
        import mosaic_live
        scopes = [{"datasource": "Warehouse:East", "schema": "archive:2026", "tables": ["orders,archive"]}]
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "sources.json")
            with open(path, "w") as handle:
                json.dump(scopes, handle)
            argv = ["mosaic_discover.py", "scan", "--sources-json", path, "--out", os.path.join(tmp, "graph.json")]
            with patch.object(sys, "argv", argv), patch.object(mosaic_live, "sign_in_from_env", return_value=object()), \
                    patch.object(md, "scan", return_value={"tables": {}, "fks": []}) as scan, patch.object(md, "catalog_stats"), \
                    patch.object(md, "measure_keys", side_effect=AssertionError("must not query source rows")):
                self.assertEqual(md.main(), 0)
            self.assertEqual(scan.call_args[0][1], [{**scopes[0], "patterns": ["orders,archive"]}])

    def test_find_cli_structured_scopes_and_anchors_preserve_identifier_delimiters(self):
        import json
        import tempfile
        from unittest.mock import patch
        import mosaic_live
        import mosaic_find
        scopes = [{"datasource": "Warehouse:East", "schema": "archive:2026", "tables": ["orders,archive"]}]
        anchors = [{"datasource": "Warehouse:East", "schema": "archive:2026", "table": "orders,archive"}]
        with tempfile.TemporaryDirectory() as tmp:
            paths = [os.path.join(tmp, name) for name in ("sources.json", "anchors.json")]
            for path, content in zip(paths, (scopes, anchors)):
                with open(path, "w") as handle:
                    json.dump(content, handle)
            argv = ["mosaic_discover.py", "find", "--sources-json", paths[0], "--anchors-json", paths[1], "--out", os.path.join(tmp, "found.json")]
            with patch.object(sys, "argv", argv), patch.object(mosaic_live, "sign_in_from_env", return_value=object()), \
                    patch.object(mosaic_find, "find", return_value={"picked": [], "candidates": 0, "read": [], "left": []}) as find:
                self.assertEqual(md.main(), 0)
            self.assertEqual(find.call_args[0][2], scopes)
            self.assertEqual(find.call_args.kwargs["anchors"], anchors)


    def test_scan_real_identifiers_take_precedence_over_glob_syntax(self):
        from unittest.mock import patch
        import mosaic_live
        import mosaic_matrix
        names = ["FACT[1]", "FACT1", "FACT*", "FACT?", "FACT2"]
        info = {"id": "A", "name": "Warehouse", "dbms": "PostgreSQL"}
        for requested in ("FACT[1]", "FACT*", "FACT?"):
            with self.subTest(requested=requested), patch.object(mosaic_live, "datasource", return_value=info), \
                    patch.object(mosaic_matrix, "list_tables", return_value=names), patch.object(mosaic_live, "run_sql", return_value=[]), \
                    patch.object(mosaic_live, "catalog", return_value={"tables": []}) as catalog:
                g = md.scan(object(), [{"datasource": "A", "schema": "s", "patterns": [requested]}])
            self.assertEqual([t["table"] for t in catalog.call_args[0][1]], [requested])
            self.assertEqual(g["selected_tables"], ["A/s/" + requested])
