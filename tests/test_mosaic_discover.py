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
        orders = next(r for r in recs if r["fact"] == a + "ORDERS")
        self.assertEqual(set(orders["tables"]), {a + "ORDERS", a + "CUSTOMERS", a + "CALENDAR"})    # no other facts pulled in
        refunds = next(r for r in recs if r["fact"] == "shopa_refunds")
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
