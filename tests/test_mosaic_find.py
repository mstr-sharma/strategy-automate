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


def run_catalogs(catalogs, query, scopes=None, **kwargs):
    """Synthetic metadata-only warehouses. No user-table reads or live clients exist in this fixture."""
    calls = []
    def datasource(m, ds, cache=None):
        if ds not in catalogs:
            raise RuntimeError("not found")
        return {"id": ds, "name": ds, "dbms": "Snowflake"}
    def run_sql(m, ds, sql):
        calls.append((ds, sql))
        schema = re.search(r"TABLE_SCHEMA='([^']+)'", sql)
        rows = [{"s": s, "t": name, "n": count, "tc": note, "cols": "|".join(cols), "cc": ""}
                for s, tables in catalogs[ds].items() for name, cols, note, count in tables
                if schema is None or s == schema.group(1)]
        page = re.search(r"LIMIT (\d+) OFFSET (\d+)", sql)
        if page:
            size, off = map(int, page.groups())
            rows = rows[off:off + size]
        return rows
    live = types.SimpleNamespace(datasource=datasource, run_sql=run_sql)
    matrix = types.SimpleNamespace(list_schemas=lambda m, ds: list(catalogs[ds]),
                                   list_tables=lambda m, ds, schema: [t[0] for t in catalogs[ds][schema]])
    client = types.SimpleNamespace(get=lambda path: types.SimpleNamespace(json=lambda: {"datasources": [{"id": ds} for ds in catalogs]}))
    with mock.patch.dict(sys.modules, {"mosaic_live": live, "mosaic_matrix": matrix}):
        return mf.find(client, query, scopes, **kwargs), calls


class RecallTests(unittest.TestCase):
    def test_exact_short_identifier_survives_ranking_and_empty_catalog_estimates(self):
        found, _ = run_catalogs({"A": {"S": [("T001", ["ENTITY_ID"], "", 0),
                                              ("FACT_ENTITY_EVENTS", ["EVENT_ID", "ENTITY_ID"], "", 100)]}}, "build a model from T001")
        self.assertEqual(found["picked"][0]["table"], "T001")
        self.assertEqual(found["picked"][0]["selection"], "explicit_name")

    def test_prefix_keeps_all_requested_tables_and_reports_cap(self):
        tables = [(f"DEMOCO{i}Orders", ["ORDER_ID", "AMOUNT"], "", 10) for i in range(6)]
        found, _ = run_catalogs({"A": {"S": tables}}, "democo", max_tables=3)
        self.assertEqual(len(found["picked"]), 3)
        self.assertTrue(all(row["selection"] == "explicit_name" for row in found["picked"]))
        self.assertEqual({row["reason"] for row in found["omitted"]}, {"table_limit"})
        self.assertEqual(len(found["omitted"]), 3)

    def test_quoted_qualified_name_is_not_rebound_to_other_schema(self):
        tables = [("ORDERS", ["ORDER_ID", "AMOUNT"], "", 10)]
        found, _ = run_catalogs({"A": {"ARCHIVE": tables, "CURRENT": tables}}, "[ARCHIVE].[ORDERS]")
        exact = [r for r in found["picked"] if r["selection"] == "explicit_name"]
        self.assertEqual([(r["schema"], r["table"]) for r in exact], [("ARCHIVE", "ORDERS")])
        self.assertNotIn("CURRENT", [r["schema"] for r in found["picked"]])

    def test_table_pattern_is_a_seed_not_a_filter_on_its_related_metadata(self):
        found, _ = run("", scopes=[{"datasource": "SF", "schema": "MFG", "tables": ["FACT_DOWNTIME*"]}])
        by_name = {r["table"]: r for r in found["picked"]}
        self.assertEqual(by_name["FACT_DOWNTIME_EVENTS"]["selection"], "scope_pattern")
        self.assertIn("DIM_MACHINE", by_name)
        self.assertIn("DIM_PLANT", by_name)
        self.assertNotIn("ORDERS", by_name)

    def test_patterns_without_schema_search_all_selected_source_namespaces(self):
        found, _ = run("", scopes=[{"datasource": "SF", "tables": ["MFG.FACT_DOWNTIME*"]}])
        self.assertIn("FACT_DOWNTIME_EVENTS", [r["table"] for r in found["picked"]])
        self.assertEqual(found["omitted"], [])

    def test_schema_case_is_resolved_before_case_sensitive_catalog_sql(self):
        found, src = run("", scopes=[{"datasource": "SF", "schema": "mfg"}],
                         anchors=[{"datasource": "SF", "schema": "mfg", "table": "fact_downtime_events"}])
        self.assertEqual(found["picked"][0]["role"], "anchor")
        self.assertIn("MFG", found["picked"][0]["schema"])
        self.assertTrue(any("TABLE_SCHEMA='MFG'" in query for query in src.sql))

    def test_explicit_anchor_survives_another_selected_pattern(self):
        found, _ = run("", scopes=[{"datasource": "SF", "schema": "MFG", "tables": ["FACT_SCRAP"]}],
                       anchors=[{"datasource": "SF", "schema": "MFG", "table": "FACT_DOWNTIME_EVENTS"}])
        self.assertEqual(found["picked"][0]["table"], "FACT_DOWNTIME_EVENTS")
        self.assertIn("FACT_SCRAP", [r["table"] for r in found["picked"]])

    def test_explicit_names_can_override_heuristic_scratch_exclusion(self):
        found, _ = run_catalogs({"A": {"S": [("OLD_ORDERS", ["ORDER_ID", "AMOUNT"], "", 10)]}}, "OLD_ORDERS")
        self.assertEqual([r["table"] for r in found["picked"]], ["OLD_ORDERS"])

    def test_cross_store_dimension_and_snowflake_parent_are_candidates(self):
        catalogs = {"A": {"OPERATIONS": [("FACT_ORDERS", ["ORDER_ID", "CUSTOMER_ID", "AMOUNT"], "", 100)]},
                    "B": {"REFERENCE": [("CUSTOMERS", ["customerId", "REGION_ID", "NAME"], "", 20),
                                          ("REGIONS", ["REGION_ID", "REGION_NAME"], "", 4)]}}
        found, calls = run_catalogs(catalogs, "FACT_ORDERS")
        by_name = {r["table"]: r for r in found["picked"]}
        self.assertEqual(set(by_name), {"FACT_ORDERS", "CUSTOMERS", "REGIONS"})
        self.assertEqual(by_name["REGIONS"]["relationship"]["depth"], 2)
        self.assertFalse(by_name["CUSTOMERS"]["relationship"]["verified"])
        self.assertEqual(by_name["CUSTOMERS"]["datasource_id"], "B")
        for _, sql in calls:
            self.assertTrue(all(name.upper().startswith("INFORMATION_SCHEMA.") for name in re.findall(r"(?:FROM|JOIN)\s+([A-Za-z_.]+)", sql)))

    def test_scoped_search_does_not_escape_source_or_schema_boundaries(self):
        catalogs = {"A": {"S": [("FACT_ORDERS", ["CUSTOMER_ID", "AMOUNT"], "", 10)],
                           "HIDDEN": [("DIM_CUSTOMER", ["CUSTOMER_ID", "NAME"], "", 2)]},
                    "B": {"S": [("DIM_CUSTOMER", ["CUSTOMER_ID", "NAME"], "", 2)]}}
        found, calls = run_catalogs(catalogs, "FACT_ORDERS", scopes=[{"datasource": "A", "schema": "S"}])
        self.assertEqual({(r["datasource_id"], r["schema"]) for r in found["picked"]}, {("A", "S")})
        self.assertEqual({ds for ds, _ in calls}, {"A"})

    def test_missing_selection_is_distinct_from_unread_metadata(self):
        scopes = [{"datasource": "SF", "schema": "MFG", "tables": ["UNKNOWN_TABLE"]}]
        missing, _ = run("", scopes=scopes)
        unread, _ = run("", scopes=scopes, budget=-1)
        self.assertEqual(missing["omitted"][0]["reason"], "not_found")
        self.assertEqual(unread["omitted"][0]["reason"], "not_read")

    def test_blank_description_can_browse_an_explicit_area(self):
        found, _ = run("", scopes=[{"datasource": "SF", "schema": "MFG"}])
        self.assertTrue(found["picked"])
        self.assertTrue(all(r["schema"] == "MFG" for r in found["picked"]))

    def test_repeated_scopes_are_deduplicated_but_all_requested_names_survive(self):
        found, src = run("", scopes=[{"datasource": "SF", "schema": "MFG", "tables": ["FACT_DOWNTIME_EVENTS"]},
                                    {"datasource": "SF", "schema": "MFG", "tables": ["FACT_SCRAP"]}])
        self.assertEqual(len(src.sql), 1)
        names = [r["table"] for r in found["picked"]]
        self.assertEqual(len(names), len(set(names)))
        self.assertIn("FACT_SCRAP", names)
        self.assertIn("FACT_DOWNTIME_EVENTS", names)


class CatalogCoverageTests(unittest.TestCase):
    def test_later_page_failure_reports_partial_data(self):
        class LaterFailure(FakeSource):
            def run_sql(self, m, ds, sql):
                if "OFFSET 4" in sql:
                    raise RuntimeError("catalog temporarily unavailable")
                return super().run_sql(m, ds, sql)
        with mock.patch.object(mf, "PAGE", 4):
            found, _ = run("downtime", source=LaterFailure())
        self.assertTrue(found["picked"])
        self.assertEqual(found["partial"][0]["reason"], "catalog_page_failed")
        self.assertIsNone(found["partial"][0]["schema"])

    def test_successful_empty_catalog_asks_strategys_table_list(self):
        # catalog views can come back empty where the table list does not (privilege-filtered views, name case)
        live = types.SimpleNamespace(run_sql=lambda *args: [])
        matrix = types.SimpleNamespace(list_tables=mock.Mock(return_value=[]))
        tables, how = mf.schema_tables(None, live, matrix, {"id": "A", "name": "A", "dbms": "Snowflake"}, "EMPTY")
        self.assertEqual(tables, [])
        self.assertEqual(how, "catalog API")
        matrix.list_tables.assert_called_once()

    def test_fallback_column_budget_prioritizes_requested_name_after_first_forty(self):
        import build_mosaic as bm
        names = [f"A_TABLE_{i:03}" for i in range(100)] + ["Z_TARGET"]
        calls = []
        def describe(m, ds, schema, name, required=False):
            calls.append(name)
            return {"columns": [{"name": "ENTITY_ID"}]}
        matrix = types.SimpleNamespace(list_tables=lambda *args: names)
        partial = []
        with mock.patch.object(bm, "fetch_table_metadata", side_effect=describe):
            tables, how = mf.schema_tables(None, None, matrix, {"id": "A", "name": "A", "dbms": "Unknown connector"}, "S",
                                          query="Z_TARGET", partial=partial)
        self.assertEqual(calls[0], "Z_TARGET")
        self.assertEqual(len(calls), 40)
        self.assertEqual(len(tables), 101)
        self.assertEqual(how, "catalog API")
        self.assertEqual(partial[0]["reason"], "column_metadata_limit")


class VocabularyTests(unittest.TestCase):
    def test_configured_phrase_alias_matches_whole_metadata_phrase(self):
        tables = [("ANNUAL_CONTRACT_VALUE", ["ENTITY_ID", "AMOUNT"], "", 1),
                  ("ANNUAL_LEAVE", ["ENTITY_ID", "DAYS"], "", 1)]
        options = {"builtin_synonyms": False, "aliases": [["ACV", "annual contract value"]]}
        found, _ = run_catalogs({"A": {"S": tables}}, "acv", search_options=options)
        matches = [r for r in found["picked"] if r["selection"] == "metadata_match"]
        self.assertEqual([r["table"] for r in matches], ["ANNUAL_CONTRACT_VALUE"])
        self.assertTrue(any("configured alias" in why for why in matches[0]["why"]))
        self.assertIn({"kind": "alias", "from": "ACV", "to": "annual contract value"}, found["expansions"])

    def test_domain_activates_by_name_not_by_one_of_its_members(self):
        options = {"builtin_synonyms": False, "domains": [{"name": "commerce", "terms": ["orders", "products"]},
                                                          {"name": "finance", "terms": ["orders", "balance"]}]}
        _, commerce = mf._vocabulary("commerce", options)
        self.assertEqual({e["to"] for e in commerce}, {"orders", "products"})
        _, member = mf._vocabulary("orders", options)
        self.assertEqual(member, [])
        tables = [("FACT_ORDERS", ["ORDER_ID", "AMOUNT"], "", 10), ("DIM_PRODUCT", ["PRODUCT_ID", "NAME"], "", 5)]
        found, _ = run_catalogs({"A": {"S": tables}}, "commerce", search_options=options)
        self.assertEqual({r["table"] for r in found["picked"]}, {"FACT_ORDERS", "DIM_PRODUCT"})

    def test_vocabulary_is_request_local_and_disabling_builtin_synonyms_is_honored(self):
        tables = [("FACT_REVENUE", ["EVENT_ID", "AMOUNT"], "", 10)]
        on, _ = run_catalogs({"A": {"S": tables}}, "sales")
        off, _ = run_catalogs({"A": {"S": tables}}, "sales", search_options={"builtin_synonyms": False})
        on_again, _ = run_catalogs({"A": {"S": tables}}, "sales")
        self.assertTrue(on["picked"])
        self.assertEqual(off["picked"], [])
        self.assertEqual(on["picked"], on_again["picked"])

    def test_alias_expansion_does_not_recurse_or_cross_word_boundaries(self):
        options = {"aliases": [["ACV", "annual contract value"], ["annual contract value", "unrelated"]], "builtin_synonyms": False}
        _, expanded = mf._vocabulary("acv", options)
        self.assertEqual([e["to"] for e in expanded], ["annual contract value"])
        self.assertEqual(mf._vocabulary("extractacvvalue", options)[1], [])


class BoundedMetadataTests(unittest.TestCase):
    def test_slow_first_source_does_not_hide_a_fast_second_source(self):
        import threading
        import time
        release = threading.Event()
        def query(m, ds, sql):
            if ds == "A":
                release.wait(2)
            return [{"s": "S", "t": "DEMOCO_ORDERS", "n": 10, "tc": "", "cols": "ORDER_ID|AMOUNT", "cc": ""}]
        live = types.SimpleNamespace(datasource=lambda m, ds, cache=None: {"id": ds, "name": ds, "dbms": "Snowflake"}, run_sql=query)
        matrix = types.SimpleNamespace(list_schemas=lambda *args: ["S"])
        began = time.monotonic()
        try:
            with mock.patch.dict(sys.modules, {"mosaic_live": live, "mosaic_matrix": matrix}):
                found = mf.find(None, "democo", scopes=[{"datasource": "A"}, {"datasource": "B"}], budget=0.3, per_source=0.05)
            self.assertLess(time.monotonic() - began, 0.5)
            self.assertIn("B", {r["datasource_id"] for r in found["picked"]})
            self.assertIn("time_budget", {p["reason"] for p in found["partial"]})
        finally:
            release.set()

    def test_fallback_uses_seed_keys_to_prioritize_related_column_metadata(self):
        import build_mosaic as bm
        names = [f"A_TABLE_{i:03}" for i in range(100)] + ["Z_TARGET", "Z_DIM_ENTITY"]
        calls = []
        def describe(m, ds, schema, name, required=False):
            calls.append(name)
            return {"columns": [{"name": "ENTITY_ID"}, {"name": "NAME"}]}
        matrix = types.SimpleNamespace(list_tables=lambda *args: names)
        with mock.patch.object(bm, "fetch_table_metadata", side_effect=describe):
            tables, _ = mf.schema_tables(None, None, matrix, {"id": "A", "name": "A", "dbms": "Unknown connector"}, "S", query="Z_TARGET")
        self.assertEqual(calls[:2], ["Z_TARGET", "Z_DIM_ENTITY"])
        self.assertEqual(len(calls), 40)
        self.assertTrue(next(t for t in tables if t["table"] == "Z_DIM_ENTITY")["columns"])

    def test_vocabulary_limit_is_explicit(self):
        limits = []
        groups = [["start"] + [f"candidate{i}_{j}" for j in range(12)] for i in range(40)]
        _, expansions = mf._vocabulary("start", {"aliases": groups}, limits=limits)
        self.assertEqual(len(expansions), 256)
        self.assertTrue(limits)


class SelectionBudgetTests(unittest.TestCase):
    def test_prefix_budget_is_shared_across_selected_sources_and_schemas(self):
        tables = [(f"DEMOCO_ORDERS_{i}", ["ORDER_ID", "AMOUNT"], "", 10) for i in range(20)]
        found, _ = run_catalogs({"A": {"ONE": tables, "TWO": tables}, "B": {"ONE": tables}}, "democo", max_tables=6)
        places = [(r["datasource_id"], r["schema"]) for r in found["picked"]]
        self.assertEqual(places.count(("A", "ONE")), 2)
        self.assertEqual(places.count(("A", "TWO")), 2)
        self.assertEqual(places.count(("B", "ONE")), 2)
        self.assertEqual(len(found["omitted"]), 54)

    def test_specific_selected_name_precedes_a_broad_pattern_at_the_cap(self):
        tables = [(f"A_ORDERS_{i}", ["ORDER_ID", "AMOUNT"], "", 10) for i in range(20)] + [("Z_ENTITY", ["ENTITY_ID", "NAME"], "", 2)]
        found, _ = run_catalogs({"A": {"ONE": tables}}, "", scopes=[{"datasource": "A", "schema": "ONE", "tables": ["A_*", "Z_ENTITY"]}], max_tables=1)
        self.assertEqual([r["table"] for r in found["picked"]], ["Z_ENTITY"])
