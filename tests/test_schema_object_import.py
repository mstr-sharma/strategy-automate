"""Unit tests for schema_object_translator.py — stdlib-only, no pytest."""
import os
import sys
import unittest


ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(ROOT, "skills", "build-mosaic-model", "scripts"))

import schema_object_translator as sot  # noqa: E402


MIN_INT = -2147483648
SYS_ID_FORM = sot.SYSTEM_ID_FORM


class TestNormalizeDatatype(unittest.TestCase):
    def test_variable_length_string_normalized(self):
        out = sot.normalize_datatype(
            {"type": "variable_length_string", "precision": -1, "scale": MIN_INT}
        )
        self.assertEqual(out, {"type": "utf8_char", "precision": 32000, "scale": 0})

    def test_integer_passthrough(self):
        out = sot.normalize_datatype({"type": "integer", "precision": 4, "scale": 0})
        self.assertEqual(out, {"type": "integer", "precision": 4, "scale": 0})

    def test_string_input_wrapped(self):
        out = sot.normalize_datatype("varchar")
        self.assertEqual(out, {"type": "utf8_char", "precision": 32000, "scale": 0})

    def test_decimal_scale_zero(self):
        out = sot.normalize_datatype({"type": "decimal", "precision": 15, "scale": 0})
        self.assertEqual(out, {"type": "int64", "precision": 8, "scale": 0})

    def test_unknown_type_passthrough(self):
        src = {"type": "timestamp", "precision": 26, "scale": 6}
        out = sot.normalize_datatype(src)
        self.assertEqual(out, src)

    def test_none_returns_default(self):
        out = sot.normalize_datatype(None)
        self.assertEqual(out, {"type": "utf8_char", "precision": 32000, "scale": 0})


class TestExtractTableIds(unittest.TestCase):
    def test_attribute_single_form(self):
        attr = {
            "forms": [{
                "information": {"name": "ID"},
                "expressions": [{
                    "tables": [{"objectId": "T1", "subType": "logical_table"}],
                    "expression": {},
                }],
            }],
        }
        self.assertEqual(sot.extract_table_ids_from_attribute(attr), {"T1"})

    def test_attribute_multi_form(self):
        attr = {
            "forms": [
                {"information": {"name": "ID"},
                 "expressions": [{"tables": [{"objectId": "T1"}]}]},
                {"information": {"name": "DESC"},
                 "expressions": [{"tables": [{"objectId": "T2"}]}]},
            ]
        }
        self.assertEqual(sot.extract_table_ids_from_attribute(attr), {"T1", "T2"})

    def test_attribute_lookup_table(self):
        attr = {
            "forms": [{"expressions": [{"tables": [{"objectId": "T1"}]}]}],
            "attributeLookupTable": {"objectId": "T_LOOKUP"},
        }
        self.assertEqual(
            sot.extract_table_ids_from_attribute(attr), {"T1", "T_LOOKUP"}
        )

    def test_fact_expressions(self):
        fact = {
            "expressions": [
                {"tables": [{"objectId": "TF1"}]},
                {"tables": [{"objectId": "TF2"}]},
            ]
        }
        self.assertEqual(sot.extract_table_ids_from_fact(fact), {"TF1", "TF2"})

    def test_empty_attribute(self):
        self.assertEqual(sot.extract_table_ids_from_attribute({}), set())
        self.assertEqual(sot.extract_table_ids_from_attribute(None), set())

    def test_expression_tree_with_logical_table_node(self):
        tree = {
            "type": "operator",
            "children": [
                {"type": "logical_table", "objectId": "TX"},
                {"type": "column_reference", "value": "FOO"},
            ],
        }
        self.assertEqual(sot.extract_table_ids_from_expression(tree), {"TX"})


class TestExtractFactIdsFromMetric(unittest.TestCase):
    def test_simple_metric_fact_ref(self):
        metric = {
            "expression": {
                "type": "object_reference",
                "subType": "fact",
                "objectId": "F1",
            }
        }
        self.assertEqual(sot.extract_fact_ids_from_metric(metric), {"F1"})

    def test_compound_metric_no_direct_fact(self):
        metric = {
            "expression": {
                "type": "operator",
                "children": [
                    {"type": "object_reference", "subType": "metric", "objectId": "M2"},
                    {"type": "object_reference", "subType": "metric", "objectId": "M3"},
                ],
            }
        }
        self.assertEqual(sot.extract_fact_ids_from_metric(metric), set())


class TestBuildMetricTranslationOrder(unittest.TestCase):
    def _metric_with_refs(self, refs: list[str]) -> dict:
        children = [
            {"type": "object_reference", "subType": "metric", "objectId": r}
            for r in refs
        ]
        return {"expression": {"type": "operator", "children": children}}

    def test_single_metric_no_deps(self):
        defs = {"M1": self._metric_with_refs([])}
        self.assertEqual(sot.build_metric_translation_order(defs), ["M1"])

    def test_two_metrics_a_depends_b(self):
        defs = {
            "A": self._metric_with_refs(["B"]),
            "B": self._metric_with_refs([]),
        }
        order = sot.build_metric_translation_order(defs)
        self.assertEqual(order.index("B") < order.index("A"), True)

    def test_three_metrics_chain(self):
        defs = {
            "A": self._metric_with_refs(["B"]),
            "B": self._metric_with_refs(["C"]),
            "C": self._metric_with_refs([]),
        }
        order = sot.build_metric_translation_order(defs)
        self.assertLess(order.index("C"), order.index("B"))
        self.assertLess(order.index("B"), order.index("A"))

    def test_cycle_raises(self):
        defs = {
            "A": self._metric_with_refs(["B"]),
            "B": self._metric_with_refs(["A"]),
        }
        with self.assertRaises(ValueError):
            sot.build_metric_translation_order(defs)


class TestTranslateAttribute(unittest.TestCase):
    def test_basic_attribute_translated(self):
        attr = {
            "information": {"name": "Customer"},
            "forms": [{
                "information": {"name": "ID"},
                "expressions": [{
                    "tables": [{"objectId": "T_CLASSIC", "name": "CUST"}],
                    "expression": {"tokens": [{"type": "column_reference", "value": "CUST_ID"}]},
                }],
            }],
            "keyForm": {"id": SYS_ID_FORM},
        }
        payload, warns = sot.translate_attribute(attr, {"T_CLASSIC": "T_MOSAIC"})
        self.assertEqual(payload["information"]["name"], "Customer")
        self.assertEqual(len(payload["forms"]), 1)
        form = payload["forms"][0]
        self.assertEqual(len(form["expressions"]), 1)
        self.assertEqual(form["expressions"][0]["tables"][0]["objectId"], "T_MOSAIC")
        self.assertEqual(payload["keyForm"]["id"], SYS_ID_FORM)
        self.assertEqual(warns, [])

    def test_missing_table_produces_warning(self):
        attr = {
            "information": {"name": "Customer"},
            "forms": [{
                "information": {"name": "ID"},
                "expressions": [{"tables": [{"objectId": "T_MISSING"}]}],
            }],
        }
        payload, warns = sot.translate_attribute(attr, {})
        self.assertTrue(any("T_MISSING" in w for w in warns))
        self.assertEqual(payload["forms"][0]["expressions"], [])

    def test_multilingual_form_not_duplicated(self):
        attr = {
            "information": {"name": "Country"},
            "forms": [{
                "information": {"name": "Name"},
                "isMultilingual": True,
                "expressions": [{
                    "tables": [{"objectId": "T1"}],
                    "expression": {},
                }],
            }],
        }
        payload, _ = sot.translate_attribute(attr, {"T1": "M1"})
        self.assertEqual(len(payload["forms"]), 1)
        self.assertTrue(payload["forms"][0].get("isMultilingual"))


class TestTranslateFactToFactmetric(unittest.TestCase):
    def test_basic_fact_metric_payload(self):
        fact = {
            "information": {"name": "Revenue"},
            "expressions": [{
                "tables": [{"objectId": "T_CLASSIC"}],
                "expression": {"tokens": [{"type": "column_reference", "value": "AMT"}]},
            }],
        }
        payload, warns = sot.translate_fact_to_factmetric(fact, {"T_CLASSIC": "T_MOSAIC"})
        self.assertEqual(payload["information"]["name"], "Revenue")
        self.assertEqual(payload["fact"]["dataType"], "number")
        self.assertEqual(payload["function"], "sum")
        self.assertEqual(len(payload["fact"]["expressions"]), 1)
        self.assertEqual(
            payload["fact"]["expressions"][0]["tables"][0]["objectId"], "T_MOSAIC"
        )
        self.assertEqual(warns, [])

    def test_apply_simple_produces_warning(self):
        fact = {
            "information": {"name": "Custom"},
            "expressions": [{
                "tables": [{"objectId": "T1"}],
                "expression": {"tokens": [{"type": "apply_simple", "value": "ApplySimple(...)"}]},
            }],
        }
        payload, warns = sot.translate_fact_to_factmetric(fact, {"T1": "M1"})
        self.assertTrue(any("apply_simple" in w for w in warns))
        self.assertEqual(len(payload["fact"]["expressions"]), 1)

    def test_table_not_in_map_produces_warning(self):
        fact = {
            "information": {"name": "X"},
            "expressions": [{"tables": [{"objectId": "T_MISSING"}]}],
        }
        payload, warns = sot.translate_fact_to_factmetric(fact, {})
        self.assertTrue(any("T_MISSING" in w for w in warns))
        self.assertEqual(payload["fact"]["expressions"], [])


class TestClassifyMetric(unittest.TestCase):
    def test_classify_fact_metric(self):
        m = {"expression": {"type": "object_reference", "subType": "fact", "objectId": "F1"}}
        self.assertEqual(sot.classify_metric(m), "fact_metric")

    def test_classify_compound(self):
        m = {"expression": {"type": "operator", "operator": "+",
                            "children": [{"type": "object_reference",
                                          "subType": "metric", "objectId": "M1"}]}}
        self.assertEqual(sot.classify_metric(m), "compound")

    def test_classify_conditional(self):
        m = {"expression": {"type": "operator"},
             "conditionality": {"filter": {"objectId": "FLT1"}}}
        self.assertEqual(sot.classify_metric(m), "conditional")

    def test_classify_level(self):
        m = {"expression": {"type": "operator"},
             "dimty": {"dimensions": [{"objectId": "A1"}]}}
        self.assertEqual(sot.classify_metric(m), "level")


if __name__ == "__main__":
    unittest.main()
