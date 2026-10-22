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
        self.assertIn("joins", join["why"][0])

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
