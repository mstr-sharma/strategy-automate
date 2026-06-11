"""schema_object_translator.py
Translates classic Strategy schema object definitions (attributes, facts, metrics)
into Mosaic-compatible REST payloads. Stateless functions only; callers own the
network session. See memory/reference_mosaic_schema_object_import.md for the
design rationale and the "DataType preconditions" section of
memory/reference_mosaic_publish_path.md for datatype normalization rules
applied here.
"""
from __future__ import annotations

from typing import Any


SYSTEM_ID_FORM = "45C11FA478E745FEA08D781CEA190FE5"  # universal Strategy ID-form constant

UNSUPPORTED_TOKEN_TYPES = {"apply_simple", "custom_expression", "raw_sql"}
SAFE_TOKEN_TYPES = {"column_reference", "operator", "constant", "function"}

_MIN_INT_SENTINEL = -2147483648

_LOGICAL_TABLE_SUBTYPES = {"logical_table", "warehouse_partition_table", 3840}
_FACT_SUBTYPES = {"fact", 13}
_METRIC_SUBTYPES = {"metric", 4}


def normalize_datatype(dt: Any) -> dict:
    """Apply the warehouse → Mosaic publishable-datatype mapping."""
    if isinstance(dt, str):
        dt = {"type": dt}
    if not isinstance(dt, dict):
        return {"type": "utf8_char", "precision": 32000, "scale": 0}

    src_type = str(dt.get("type", "")).lower()
    precision = dt.get("precision")
    scale = dt.get("scale")

    string_types = {"variable_length_string", "fixed_length_string",
                    "varchar", "char", "text", "string"}
    if src_type in string_types:
        return {"type": "utf8_char", "precision": 32000, "scale": 0}

    if src_type == "integer":
        if precision == 4 and scale == _MIN_INT_SENTINEL:
            return {"type": "integer", "precision": 4, "scale": 0}
        return dict(dt)

    if src_type == "binary":
        return {"type": "integer", "precision": 2, "scale": 0}

    if src_type == "unsigned":
        return {"type": "integer", "precision": 2, "scale": 0}

    if src_type == "decimal" and scale == 0:
        return {"type": "int64", "precision": 8, "scale": 0}

    return dict(dt)


def extract_table_ids_from_expression(expr_tree: Any) -> set[str]:
    """Walk any JSON expression tree and collect logical-table object IDs."""
    found: set[str] = set()
    if not expr_tree:
        return found

    def _walk(node: Any) -> None:
        if isinstance(node, dict):
            sub = node.get("subType")
            ntype = node.get("type")
            if sub in _LOGICAL_TABLE_SUBTYPES or ntype in _LOGICAL_TABLE_SUBTYPES:
                obj_id = node.get("objectId")
                if obj_id:
                    found.add(obj_id)
            tables = node.get("tables")
            if isinstance(tables, list):
                for t in tables:
                    if isinstance(t, dict):
                        oid = t.get("objectId")
                        if oid:
                            found.add(oid)
                        _walk(t)
            for k, v in node.items():
                if k == "tables":
                    continue
                _walk(v)
        elif isinstance(node, list):
            for item in node:
                _walk(item)

    _walk(expr_tree)
    return found


def extract_table_ids_from_attribute(attr_def: dict) -> set[str]:
    """Extract every physical table object ID referenced by an attribute."""
    found: set[str] = set()
    if not attr_def:
        return found
    for form in (attr_def.get("forms") or []):
        for expr in (form.get("expressions") or []):
            for tbl in (expr.get("tables") or []):
                oid = (tbl or {}).get("objectId")
                if oid:
                    found.add(oid)
            found |= extract_table_ids_from_expression(expr.get("expression"))
    lookup = attr_def.get("attributeLookupTable")
    if isinstance(lookup, dict) and lookup.get("objectId"):
        found.add(lookup["objectId"])
    return found


def extract_table_ids_from_fact(fact_def: dict) -> set[str]:
    """Extract every physical table object ID referenced by a fact."""
    found: set[str] = set()
    if not fact_def:
        return found
    for expr in (fact_def.get("expressions") or []):
        for tbl in (expr.get("tables") or []):
            oid = (tbl or {}).get("objectId")
            if oid:
                found.add(oid)
        found |= extract_table_ids_from_expression(expr.get("expression"))
    return found


def _walk_object_refs(node: Any, subtypes: set, out: set[str]) -> None:
    if isinstance(node, dict):
        if node.get("type") == "object_reference":
            sub = node.get("subType")
            if sub in subtypes:
                oid = node.get("objectId")
                if oid:
                    out.add(oid)
        for v in node.values():
            _walk_object_refs(v, subtypes, out)
    elif isinstance(node, list):
        for item in node:
            _walk_object_refs(item, subtypes, out)


def extract_fact_ids_from_metric(metric_def: dict) -> set[str]:
    """Direct fact references in a metric expression tree."""
    out: set[str] = set()
    if not metric_def:
        return out
    expr = metric_def.get("expression")
    _walk_object_refs(expr, _FACT_SUBTYPES, out)
    return out


def extract_metric_refs_from_metric(metric_def: dict) -> set[str]:
    """Nested metric references in a metric expression tree."""
    out: set[str] = set()
    if not metric_def:
        return out
    expr = metric_def.get("expression")
    _walk_object_refs(expr, _METRIC_SUBTYPES, out)
    return out


def classify_metric(metric_def: dict) -> str:
    """Classify a classic metric for routing to the right Mosaic endpoint shape."""
    if not metric_def:
        return "unknown"
    if metric_def.get("conditionality"):
        return "conditional"
    dimty = metric_def.get("dimty") or {}
    if dimty.get("dimensions"):
        return "level"
    expr = metric_def.get("expression") or {}
    root_type = expr.get("type")
    if root_type == "object_reference":
        sub = expr.get("subType")
        if sub in _FACT_SUBTYPES:
            return "fact_metric"
    if root_type in {"operator", "function"}:
        nested_metrics: set[str] = set()
        _walk_object_refs(expr, _METRIC_SUBTYPES, nested_metrics)
        return "compound"
    if root_type:
        return "compound"
    return "unknown"


def _form_name(form: dict) -> str:
    info = form.get("information") or {}
    return info.get("name") or form.get("name") or "?"


def translate_attribute(
    attr_def: dict,
    logical_table_map: dict[str, str],
) -> tuple[dict, list[str]]:
    """Translate a classic attribute definition into a Mosaic POST body."""
    warnings: list[str] = []
    if not attr_def:
        return {"information": {"name": "?"}, "forms": []}, ["empty attribute definition"]

    info = attr_def.get("information") or {}
    name = info.get("name") or attr_def.get("name") or "?"

    out_forms: list[dict] = []
    for form in (attr_def.get("forms") or []):
        fname = _form_name(form)
        new_form: dict = {}
        for key in ("information", "category", "displayFormat", "alias", "isMultilingual"):
            if key in form:
                new_form[key] = form[key]
        if "information" not in new_form and form.get("name"):
            new_form["information"] = {"name": form["name"]}

        new_exprs: list[dict] = []
        for expr in (form.get("expressions") or []):
            mapped_tables: list[dict] = []
            unmapped = False
            for tbl in (expr.get("tables") or []):
                tid = (tbl or {}).get("objectId")
                mapped = logical_table_map.get(tid) if tid else None
                if not mapped:
                    warnings.append(
                        f"form '{fname}' references table {tid} not found in "
                        "logical_table_map — skipped"
                    )
                    unmapped = True
                    break
                mapped_tables.append({
                    "objectId": mapped,
                    "subType": "logical_table",
                    "name": tbl.get("name") or "",
                })
            if unmapped:
                continue
            new_expr = dict(expr)
            new_expr["tables"] = mapped_tables
            for col in (new_expr.get("columns") or []):
                if isinstance(col, dict) and "dataType" in col:
                    col["dataType"] = normalize_datatype(col["dataType"])
            new_exprs.append(new_expr)

        if not new_exprs and (form.get("expressions") or []):
            warnings.append(
                f"form '{fname}' has no mappable expressions — will need "
                "manual expression binding post-create"
            )
        new_form["expressions"] = new_exprs
        out_forms.append(new_form)

    payload: dict = {"information": {"name": name}, "forms": out_forms}

    src_keyform = (attr_def.get("keyForm") or {}).get("id")
    if src_keyform == SYSTEM_ID_FORM:
        payload["keyForm"] = {"id": SYSTEM_ID_FORM}
    elif src_keyform:
        src_forms = attr_def.get("forms") or []
        idx = next((i for i, f in enumerate(src_forms)
                    if (f.get("id") == src_keyform
                        or (f.get("information") or {}).get("objectId") == src_keyform)),
                   None)
        if idx is not None and idx < len(out_forms):
            new_id = (out_forms[idx].get("information") or {}).get("objectId") or src_keyform
            payload["keyForm"] = {"id": new_id}
        else:
            payload["keyForm"] = {"id": SYSTEM_ID_FORM}
    else:
        payload["keyForm"] = {"id": SYSTEM_ID_FORM}

    lookup = attr_def.get("attributeLookupTable")
    if isinstance(lookup, dict):
        lid = lookup.get("objectId")
        mapped_lid = logical_table_map.get(lid) if lid else None
        if mapped_lid:
            payload["attributeLookupTable"] = {
                "objectId": mapped_lid,
                "subType": "logical_table",
                "name": lookup.get("name") or "",
            }

    return payload, warnings


def translate_fact_to_factmetric(
    fact_def: dict,
    logical_table_map: dict[str, str],
) -> tuple[dict, list[str]]:
    """Translate a classic fact into a Mosaic factMetric POST body."""
    warnings: list[str] = []
    if not fact_def:
        return ({"information": {"name": "?"},
                 "fact": {"dataType": "number", "expressions": [], "extensions": [], "entryLevel": []},
                 "function": "sum",
                 "functionProperties": [],
                 "dimty": {},
                 "format": {"header": [], "values": []}}, ["empty fact definition"])

    info = fact_def.get("information") or {}
    name = info.get("name") or fact_def.get("name") or "?"

    new_exprs: list[dict] = []
    for expr in (fact_def.get("expressions") or []):
        mapped_tables: list[dict] = []
        unmapped = False
        for tbl in (expr.get("tables") or []):
            tid = (tbl or {}).get("objectId")
            mapped = logical_table_map.get(tid) if tid else None
            if not mapped:
                warnings.append(
                    f"fact '{name}' expression references table {tid} not in "
                    "logical_table_map — expression skipped"
                )
                unmapped = True
                break
            mapped_tables.append({
                "objectId": mapped,
                "subType": "logical_table",
                "name": tbl.get("name") or "",
            })
        if unmapped:
            continue

        for tok in (expr.get("expression", {}).get("tokens") or []):
            ttype = (tok or {}).get("type")
            if ttype in UNSUPPORTED_TOKEN_TYPES:
                warnings.append(
                    f"fact '{name}' expression contains unsupported token type "
                    f"'{ttype}' — manual review required"
                )

        new_expr = dict(expr)
        new_expr["tables"] = mapped_tables
        new_exprs.append(new_expr)

    return ({
        "information": {"name": name},
        "fact": {
            "dataType": "number",
            "expressions": new_exprs,
            "extensions": [],
            "entryLevel": [],
        },
        "function": "sum",
        "functionProperties": [],
        "dimty": {},
        "format": {"header": [], "values": []},
    }, warnings)


def _rewrite_object_refs(
    node: Any,
    fact_id_to_mosaic_id: dict[str, str],
    metric_id_to_mosaic_id: dict[str, str],
    warnings: list[str],
    metric_name: str,
) -> Any:
    if isinstance(node, dict):
        if node.get("type") == "object_reference":
            sub = node.get("subType")
            old_id = node.get("objectId")
            if sub in _FACT_SUBTYPES and old_id:
                new_id = fact_id_to_mosaic_id.get(old_id)
                if new_id:
                    new_node = dict(node)
                    new_node["objectId"] = new_id
                    return new_node
                warnings.append(
                    f"metric '{metric_name}' references unmapped fact {old_id} — "
                    "left as classic ID (will fail at commit)"
                )
            elif sub in _METRIC_SUBTYPES and old_id:
                new_id = metric_id_to_mosaic_id.get(old_id)
                if new_id:
                    new_node = dict(node)
                    new_node["objectId"] = new_id
                    return new_node
                warnings.append(
                    f"metric '{metric_name}' references unmapped nested metric "
                    f"{old_id} — left as classic ID"
                )
        return {k: _rewrite_object_refs(v, fact_id_to_mosaic_id,
                                        metric_id_to_mosaic_id, warnings, metric_name)
                for k, v in node.items()}
    if isinstance(node, list):
        return [_rewrite_object_refs(item, fact_id_to_mosaic_id,
                                     metric_id_to_mosaic_id, warnings, metric_name)
                for item in node]
    return node


def translate_metric(
    metric_def: dict,
    fact_id_to_mosaic_id: dict[str, str],
    metric_id_to_mosaic_id: dict[str, str],
    attr_id_to_mosaic_id: dict[str, str] | None = None,
) -> tuple[dict, list[str]]:
    """Translate a classic metric definition into the right Mosaic payload shape."""
    warnings: list[str] = []
    if not metric_def:
        return {"information": {"name": "?"}}, ["empty metric definition"]

    info = metric_def.get("information") or {}
    name = info.get("name") or metric_def.get("name") or "?"
    mtype = classify_metric(metric_def)

    rewritten_expr = _rewrite_object_refs(
        metric_def.get("expression"),
        fact_id_to_mosaic_id,
        metric_id_to_mosaic_id,
        warnings,
        name,
    )

    if mtype == "fact_metric":
        payload = {
            "information": {"name": name},
            "fact": {
                "dataType": "number",
                "expressions": [{"expression": rewritten_expr, "tables": []}],
                "extensions": [],
                "entryLevel": [],
            },
            "function": "sum",
            "functionProperties": [],
            "dimty": {},
            "format": {"header": [], "values": []},
        }
        return payload, warnings

    if mtype == "compound":
        return ({
            "information": {"name": name},
            "expression": rewritten_expr,
            "format": {"header": [], "values": []},
        }, warnings)

    if mtype == "conditional":
        cond = metric_def.get("conditionality") or {}
        flt = (cond.get("filter") or {}).get("objectId")
        if flt:
            warnings.append(
                f"metric '{name}' has conditional filter {flt} — classic project "
                "filter ID will not resolve in Mosaic; recreate filter post-build"
            )
        return ({
            "information": {"name": name},
            "expression": rewritten_expr,
            "conditionality": cond,
            "format": {"header": [], "values": []},
        }, warnings)

    if mtype == "level":
        dimty = dict(metric_def.get("dimty") or {})
        if attr_id_to_mosaic_id:
            new_dims = []
            for dim in dimty.get("dimensions") or []:
                if isinstance(dim, dict):
                    aid = dim.get("objectId")
                    mapped = attr_id_to_mosaic_id.get(aid) if aid else None
                    new_dim = dict(dim)
                    if mapped:
                        new_dim["objectId"] = mapped
                    else:
                        warnings.append(
                            f"metric '{name}' dimty references attribute {aid} "
                            "not in translated set — left as classic ID"
                        )
                    new_dims.append(new_dim)
                else:
                    new_dims.append(dim)
            dimty["dimensions"] = new_dims
        return ({
            "information": {"name": name},
            "expression": rewritten_expr,
            "dimty": dimty,
            "format": {"header": [], "values": []},
        }, warnings)

    warnings.append(
        f"metric '{name}' type unknown — included verbatim, manual review required"
    )
    return ({
        "information": {"name": name},
        "expression": metric_def.get("expression"),
        "format": {"header": [], "values": []},
    }, warnings)


def build_metric_translation_order(metric_defs: dict[str, dict]) -> list[str]:
    """Return metric IDs in dependency order (a metric appears after its deps)."""
    if not metric_defs:
        return []

    deps: dict[str, set[str]] = {}
    for mid, mdef in metric_defs.items():
        refs = extract_metric_refs_from_metric(mdef)
        deps[mid] = {r for r in refs if r in metric_defs}

    order: list[str] = []
    visited: dict[str, int] = {}  # 0=unseen, 1=in-progress, 2=done

    def _visit(node: str, stack: list[str]) -> None:
        state = visited.get(node, 0)
        if state == 2:
            return
        if state == 1:
            cycle = stack[stack.index(node):] + [node]
            raise ValueError(f"metric dependency cycle: {' -> '.join(cycle)}")
        visited[node] = 1
        stack.append(node)
        for dep in deps.get(node, set()):
            _visit(dep, stack)
        stack.pop()
        visited[node] = 2
        order.append(node)

    for mid in metric_defs:
        _visit(mid, [])
    return order
