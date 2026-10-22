import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _hermetic  # noqa: E402,F401  (scrub MSTR_*/proxy env, private secret store)

# Finding the tables that fit a description: metadata only (catalog views, comments, row counts, usage, references),
# never a query on a table; a whole source in pages of 1,000 tables; the best matches plus the tables they join to.
import os  # noqa: E402
import re  # noqa: E402
import sys  # noqa: E402
import types  # noqa: E402
import unittest  # noqa: E402
from unittest import mock  # noqa: E402

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "skills", "build-mosaic-model", "scripts"))
import mosaic_find as mf  # noqa: E402

TABLES = {
    "MFG": [("FACT_DOWNTIME_EVENTS", ["EVENT_ID", "MACHINE_CODE", "PLANT_ID", "DURATION_MINS"], "", 15000),
            ("DIM_MACHINE", ["MACHINE_CODE", "MACHINE_NAME", "PLANT_ID"], "", 70),
            ("DIM_PLANT", ["PLANT_ID", "PLANT_NAME", "REGION"], "Factories and mills", 6),
            ("FACT_SCRAP", ["SCRAP_ID", "PLANT_ID", "SCRAP_KG"], "", 0)],
    "RETAIL": [("ORDERS", ["ORDER_ID", "CUSTOMER_ID", "AMOUNT"], "", 5000), ("CUSTOMERS", ["CUSTOMER_ID", "SEGMENT"], "", 200)],
}


class FakeSource:
    def __init__(self):
        self.sql: list[str] = []

    def run_sql(self, m, ds, sql):
        self.sql.append(sql)
        schema = re.search(r"TABLE_SCHEMA='([^']+)'", sql)
        rows = [{"s": s, "t": t, "n": n, "tc": tc, "cols": "|".join(cols), "cc": ""} for s, ts in TABLES.items() for t, cols, tc, n in ts
                if not schema or s == schema.group(1)]
        page = re.search(r"LIMIT (\d+) OFFSET (\d+)", sql)
        if page:
            size, off = int(page.group(1)), int(page.group(2))
            rows = rows[off: off + size]
        return rows


def run(query, scopes=None, source=None, **kw):
    src = source or FakeSource()
    live = types.SimpleNamespace(run_sql=src.run_sql, datasource=lambda m, ds, cache=None: {"id": "SF", "name": "Warehouse", "dbms": "Snowflake"})
    matrix = types.SimpleNamespace(list_schemas=lambda m, ds: list(TABLES), list_tables=lambda m, ds, s: [t[0] for t in TABLES[s]])
    m = types.SimpleNamespace(get=lambda path: types.SimpleNamespace(json=lambda: {"datasources": [{"id": "SF"}]}))
    with mock.patch.dict(sys.modules, {"mosaic_live": live, "mosaic_matrix": matrix}):
        return mf.find(m, query, scopes, **kw), src


class FindTests(unittest.TestCase):
    def test_the_best_tables_and_the_tables_they_join_to(self):
        found, _ = run("downtime by machine and plant")
        picked = {(p["table"], p["role"]) for p in found["picked"]}
        self.assertIn(("FACT_DOWNTIME_EVENTS", "match"), picked)
        self.assertIn(("DIM_MACHINE", "match"), picked)
        self.assertNotIn("ORDERS", {p["table"] for p in found["picked"]})
        join = next(p for p in found["picked"] if p["table"] == "FACT_SCRAP")
        self.assertEqual(join["role"], "join")                       # shares PLANT_ID with a match
        self.assertIn("shares", join["why"][0])

    def test_only_catalog_views_are_queried(self):
        _, src = run("downtime by machine")
        self.assertTrue(src.sql)
        for sql in src.sql:
            froms = re.findall(r"(?:FROM|JOIN)\s+([A-Za-z_\.]+)", sql)
            self.assertTrue(all(f.upper().startswith("INFORMATION_SCHEMA.") for f in froms), sql)

    def test_a_whole_source_is_read_in_pages(self):
        with mock.patch.object(mf, "PAGE", 4):
            found, src = run("downtime", scopes=[{"datasource": "SF"}])
        self.assertEqual(len(src.sql), 2)                            # 6 tables, 4 per page: a short second page ends it
        self.assertEqual([re.search(r"OFFSET (\d+)", x).group(1) for x in src.sql], ["0", "4"])
        self.assertEqual(sorted(found["read"]), ["Warehouse/MFG", "Warehouse/RETAIL"])

    def test_comments_usage_references_and_empty_tables_move_the_score(self):
        want = mf.terms("factory output")
        plant = {"table": "DIM_PLANT", "columns": [{"name": "PLANT_ID", "comment": ""}], "comment": "Factories and mills", "rows": 6}
        base, _ = mf.score_table(plant, want, {}, set())
        used, why = mf.score_table(plant, want, {"dim_plant": 3}, {"dim_plant"})
        self.assertGreater(used, base)
        self.assertTrue(any("references name it" in w for w in why) and any("3 existing models use it" in w for w in why))
        empty, why = mf.score_table({**plant, "rows": 0}, want, {}, set())
        self.assertLess(empty, base)

    def test_one_word_of_a_name_counts_once(self):
        """"plant" and "production" mean the same thing here: PLANT_ID must not score for both"""
        t = {"table": "DIM_SITE", "columns": [{"name": "PLANT_ID", "comment": ""}], "comment": "", "rows": 1}
        one, _ = mf.score_table(t, mf.terms("plant"), {}, set())
        both, _ = mf.score_table(t, mf.terms("plant production"), {}, set())
        self.assertEqual(one, both)

    def test_a_search_out_of_time_says_what_it_left(self):
        found, _ = run("downtime", scopes=[{"datasource": "SF", "schema": "MFG"}, {"datasource": "SF", "schema": "RETAIL"}], budget=-1)
        self.assertEqual(found["read"], [])
        self.assertEqual(len(found["left"]), 2)

    def test_nothing_matches_nothing_picked(self):
        found, _ = run("weather on mars")
        self.assertEqual(found["picked"], [])


if __name__ == "__main__":
    unittest.main()


class AnchorTests(unittest.TestCase):
    def test_anchors_are_kept_and_their_key_partners_found_in_any_schema(self):
        found, _ = run("", scopes=[{"datasource": "SF"}], anchors=[{"datasource": "SF", "schema": "MFG", "table": "FACT_DOWNTIME_EVENTS"}])
        roles = {p["table"]: p["role"] for p in found["picked"]}
        self.assertEqual(roles["FACT_DOWNTIME_EVENTS"], "anchor")
        self.assertEqual(roles.get("DIM_MACHINE"), "join")                  # shares MACHINE_CODE
        self.assertEqual(roles.get("DIM_PLANT"), "join")                    # shares PLANT_ID
        self.assertNotIn("ORDERS", roles)                                   # shares no key
        self.assertTrue(found["terms"])                                     # words from the anchor when nothing was described


class PartnerTests(unittest.TestCase):
    def test_rare_keys_in_the_same_schema_beat_a_generic_key_elsewhere(self):
        """seen live: EVENT_ID pulled event tables from unrelated schemas ahead of the machine and plant dimensions"""
        row = lambda schema, table, cols: {"datasource_id": "SF", "schema": schema, "table": table, "columns": cols, "why": [], "score": 0}  # noqa: E731
        anchor = row("MFG", "FACT_DOWNTIME_EVENTS", ["EVENT_ID", "MACHINE_CODE", "PLANT_ID", "REASON_CODE"])
        found = [anchor, row("MFG", "DIM_MACHINE", ["MACHINE_CODE", "PLANT_ID"]), row("MFG", "DIM_PLANT", ["PLANT_KEY", "SOURCE_PLANT_ID"]),
                 row("CARDS", "DIM_DECLINE_REASON", ["REASON_CODE"]), row("DBT", "MY_MODEL", ["ID", "CODE"])] + \
                [row(f"OTHER{i}", f"FACT_THING_EVENTS_{i}", ["EVENT_ID", "THING_ID"]) for i in range(30)]
        picked = mf.partners([anchor], found, 4)
        self.assertEqual([p["table"] for p in picked[:2]], ["DIM_MACHINE", "DIM_PLANT"])
        self.assertFalse([p for p in picked if p["table"].startswith("FACT_THING")])
        self.assertNotIn("DIM_DECLINE_REASON", [p["table"] for p in picked])        # one shared name in another schema
        self.assertNotIn("MY_MODEL", [p["table"] for p in picked])                  # a bare ID is not a form of EVENT_ID


class DatasetTests(unittest.TestCase):
    def row(self, schema, table, cols, n=6):
        return {"datasource_id": "SF", "datasource": "SF", "dbms": "Snowflake", "schema": schema, "table": table, "score": 0, "why": [],
                "columns": cols, "_t": {"table": table, "columns": [{"name": c, "comment": ""} for c in cols], "comment": "", "rows": 10}, "_n": n}

    def test_rare_words_count_more_and_whole_datasets_are_picked(self):
        """seen live: "customer churn and product sales" picked lone wide tables in five schemas; a rare word ("churn")
        must lead, and a dataset with its join partners beats a lone table"""
        found = [self.row("INS", "FACT_POLICY", ["POLICY_ID", "CUSTOMER_ID", "CANCELLATION_REASON"]),
                 self.row("INS", "DIM_CUSTOMER", ["CUSTOMER_ID", "SEGMENT"]),
                 self.row("INS", "SNOWPARK_TEMP_TABLE_X1", ["POLICY_ID", "CUSTOMER_ID"]),
                 self.row("INS", "FACT_LOAD", ["ETL_BATCH_ID", "ROWS"]),
                 self.row("WIDE", "HOLD_TABLE", ["CUSTOMER_ID", "PRODUCT_ID", "SALES_AMT", "CANCELED_FLAG"] + [f"C{i}" for i in range(150)], 1)] + \
                [self.row(f"S{i}", f"CUSTOMER_{i}", ["CUSTOMER_ID", "PRODUCT_ID"], 1) for i in range(40)]
        picked, _ = mf.pick_datasets(found, mf.terms("customer churn and product sales"), {}, set())
        names = [p["table"] for p in picked]
        self.assertEqual(names[:2], ["FACT_POLICY", "DIM_CUSTOMER"])
        self.assertNotIn("SNOWPARK_TEMP_TABLE_X1", names)
        self.assertNotIn("HOLD_TABLE", names)
        self.assertFalse(mf._keyish("ETL_BATCH_ID"))
