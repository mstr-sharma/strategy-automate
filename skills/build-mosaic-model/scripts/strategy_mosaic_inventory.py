#!/usr/bin/env python3
"""Inventory Mosaic data models in a Strategy project.

Read-only field study helper for the modern (Mosaic) semantic layer:
models, physical tables, attributes, fact metrics, custom metrics, hierarchy,
security filters, links/external-data-models, translations. Designed as the
Mosaic counterpart to strategy_semantic_inventory.py so we can diff classic
vs modern object shapes and build the legacy <-> Mosaic bridge reference.

Writes raw inventory to /tmp by default; do not commit raw tenant payloads.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from typing import Any

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _client import (  # noqa: E402
    Auth, InventoryClient, add_auth_args, client_from_args, collect_named_values,
    collect_texts, dedupe_by_id, dump_inventory, expression_kind, items_from_payload,
    now_id, oid, oname, read_parallel, response_json, walk,
)


DATA_MODEL_TYPE = 3
DATA_MODEL_SUBTYPE = 779

# Sub-resources pulled per Mosaic data model. Each entry: (key, path_suffix, optional_params)
# NOTE: /links requires X-MSTR-MS-Changeset even for GET on some Strategy tenants, so it's excluded.
SUBRESOURCES: list[tuple[str, str, dict[str, str]]] = [
    ("model", "", {}),
    ("tables", "/tables", {}),
    ("attributes", "/attributes", {"showExpressionAs": "tree"}),
    ("factMetrics", "/factMetrics", {"showExpressionAs": "tree"}),
    ("metrics", "/metrics", {"showExpressionAs": "tree"}),
    ("hierarchy", "/hierarchy", {}),
    ("securityFilters", "/securityFilters", {"showFilterTokens": "true"}),
    ("externalDataModels", "/externalDataModels", {}),
    ("folders", "/folders", {}),
]


class Client(InventoryClient):
    """Mosaic inventory client — adds the data-model search."""

    def search_data_models(self, limit: int) -> list[dict[str, Any]]:
        """Search all Mosaic data models (type=3, subType=779) in the project."""
        rows = self.search_results(obj_type=DATA_MODEL_TYPE, limit=limit, timeout=60)
        return dedupe_by_id(
            [r for r in rows if int(r.get("subtype") or r.get("subType") or 0) == DATA_MODEL_SUBTYPE])


def read_subresource(auth: Auth, model_id: str, path_suffix: str, params: dict[str, str]) -> dict[str, Any]:
    url = f"{auth.base}/api/model/dataModels/{model_id}{path_suffix}"
    try:
        resp = requests.get(url, headers=auth.headers, cookies=auth.cookies, params=params, timeout=60)
        payload = response_json(resp)
        return {
            "ok": resp.ok,
            "status": resp.status_code,
            "body": payload if resp.ok else None,
            "error": None if resp.ok else str(payload)[:500],
        }
    except Exception as exc:
        return {"ok": False, "status": None, "body": None, "error": str(exc)[:500]}


def read_model(auth: Auth, item: dict[str, Any]) -> dict[str, Any]:
    model_id = oid(item) or ""
    if not model_id:
        return {"ok": False, "error": "missing model id", "subresources": {}}
    result: dict[str, Any] = {"ok": True, "id": model_id, "subresources": {}}
    for key, suffix, params in SUBRESOURCES:
        result["subresources"][key] = read_subresource(auth, model_id, suffix, params)

    # Second-pass table detail: /tables list returns stubs; per-table body carries
    # physicalTable.type/namespace/tableName/databaseInstance/columns etc.
    tables_resp = result["subresources"].get("tables") or {}
    if tables_resp.get("ok"):
        stubs = items_from_payload(tables_resp.get("body"))
        details: list[dict[str, Any]] = []
        for stub in stubs:
            tid = oid(stub)
            if not tid:
                details.append(stub)
                continue
            detail = read_subresource(auth, model_id, f"/tables/{tid}", {})
            if detail.get("ok") and isinstance(detail.get("body"), dict):
                details.append(detail["body"])
            else:
                details.append(stub)
        result["subresources"]["tables"]["tableDetails"] = details
    return result


def summarize_attribute(body: dict[str, Any]) -> dict[str, Any]:
    forms = body.get("forms") or []
    tables_refs = [t.get("name") or t.get("objectId") for t in (body.get("tables") or []) if isinstance(t, dict)]
    return {
        "id": oid(body),
        "name": oname(body),
        "subType": (body.get("information") or {}).get("subType"),
        "formCount": len(forms),
        "forms": [
            {
                "id": f.get("id"),
                "name": f.get("name"),
                "category": f.get("category") or f.get("formCategory"),
                "type": f.get("type") or f.get("formType"),
                "displayFormat": f.get("displayFormat"),
                "expressionTexts": collect_texts(f, 3),
            }
            for f in forms[:12]
            if isinstance(f, dict)
        ],
        "keyForm": body.get("keyForm"),
        "displays": body.get("displays"),
        "attributeLookupTable": (body.get("attributeLookupTable") or {}).get("name") if isinstance(body.get("attributeLookupTable"), dict) else body.get("attributeLookupTable"),
        "relationshipCount": len(body.get("relationships") or []),
        "tables": tables_refs[:20],
        "isSmart": bool(body.get("smartAttribute") or body.get("isSmartAttribute")),
        "sortBy": body.get("sortBy"),
        "relationships": [
            {
                "parent": (r.get("parent") or {}).get("name") if isinstance(r.get("parent"), dict) else None,
                "child": (r.get("child") or {}).get("name") if isinstance(r.get("child"), dict) else None,
                "type": r.get("relationshipType") or r.get("type"),
                "table": (r.get("relationshipTable") or {}).get("name") if isinstance(r.get("relationshipTable"), dict) else None,
            }
            for r in (body.get("relationships") or [])[:15]
            if isinstance(r, dict)
        ],
    }


def summarize_metric(body: dict[str, Any], family: str) -> dict[str, Any]:
    expr = body.get("expression") or {}
    info = body.get("information") or {}
    return {
        "id": oid(body),
        "name": oname(body),
        "family": family,
        "subType": info.get("subType"),
        "expressionText": expr.get("text") if isinstance(expr, dict) else None,
        "expressionKind": expression_kind(body),
        "functions": collect_named_values(body, "function", 10),
        "operators": collect_named_values(body, "operator", 10),
        "hasConditionality": "conditionality" in body,
        "hasDimensionality": any(k in body for k in ("dimty", "dimensionality", "levels")),
        "hasTransformation": "transformation" in body,
        "isCompound": bool(body.get("isCompound") or expr.get("isCompound")),
        "isSmart": bool(body.get("smartMetric") or body.get("isSmartMetric")),
        "subtotals": [s.get("name") for s in (body.get("subtotals") or []) if isinstance(s, dict)][:10],
        "thresholds": len(body.get("thresholds") or []),
        "nestedMetricRefs": list({
            str(n.get("name") or n.get("objectId"))
            for n in walk(body)
            if isinstance(n, dict) and str(n.get("subType") or "").lower().find("metric") >= 0
        })[:8],
    }


def summarize_table(body: dict[str, Any]) -> dict[str, Any]:
    phys = body.get("physicalTable") or {}
    columns = phys.get("columns") or body.get("columns") or []
    return {
        "id": oid(body),
        "name": oname(body),
        "physicalType": phys.get("type") or body.get("tableType"),
        "namespace": phys.get("namespace"),
        "tableName": phys.get("tableName"),
        "databaseInstanceId": (phys.get("databaseInstance") or {}).get("objectId") if isinstance(phys.get("databaseInstance"), dict) else None,
        "columnCount": len(columns) if isinstance(columns, list) else 0,
        "hasPrePostStatement": any(k in phys for k in ("preStatement", "postStatement")),
        "sqlStatement": (phys.get("sqlStatement") or "")[:240],
    }


def summarize_hierarchy(body: dict[str, Any]) -> dict[str, Any]:
    rels = body.get("relationships") or []
    rel_types = Counter(str(r.get("relationshipType") or r.get("type") or "") for r in rels if isinstance(r, dict))
    return {
        "relationshipCount": len(rels),
        "relationshipTypes": dict(rel_types.most_common(10)),
        "attributeCount": len(body.get("attributes") or []),
        "isolatedAttributeCount": len(body.get("isolatedAttributes") or []),
        "sampleRelationships": [
            {
                "parent": (r.get("parent") or {}).get("name") if isinstance(r.get("parent"), dict) else None,
                "child": (r.get("child") or {}).get("name") if isinstance(r.get("child"), dict) else None,
                "type": r.get("relationshipType") or r.get("type"),
                "table": (r.get("relationshipTable") or {}).get("name") if isinstance(r.get("relationshipTable"), dict) else None,
            }
            for r in rels[:20]
            if isinstance(r, dict)
        ],
    }


def summarize_security_filter(body: dict[str, Any]) -> dict[str, Any]:
    qual = body.get("qualification") or {}
    return {
        "id": oid(body),
        "name": oname(body),
        "qualificationType": qual.get("type") if isinstance(qual, dict) else None,
        "qualificationText": (qual.get("text") if isinstance(qual, dict) else "") or (collect_texts(qual, 1) or [""])[0],
        "memberCount": len(body.get("members") or []),
        "attributeRefs": collect_named_values(qual, "name", 8) if isinstance(qual, dict) else [],
    }


def summarize_model(item: dict[str, Any], definition: dict[str, Any]) -> dict[str, Any]:
    sub = definition.get("subresources") or {}
    model_body = (sub.get("model") or {}).get("body") or {}
    info = model_body.get("information") or {}

    attributes = items_from_payload((sub.get("attributes") or {}).get("body"))
    fact_metrics = items_from_payload((sub.get("factMetrics") or {}).get("body"))
    metrics = items_from_payload((sub.get("metrics") or {}).get("body"))
    # Prefer second-pass table bodies (with physicalTable details) when available.
    tables_block = sub.get("tables") or {}
    tables = tables_block.get("tableDetails") or items_from_payload(tables_block.get("body"))
    security_filters = items_from_payload((sub.get("securityFilters") or {}).get("body"))
    links = items_from_payload((sub.get("links") or {}).get("body"))
    external_models = items_from_payload((sub.get("externalDataModels") or {}).get("body"))
    folders = items_from_payload((sub.get("folders") or {}).get("body"))
    hierarchy_body = (sub.get("hierarchy") or {}).get("body") or {}

    attr_summaries = [summarize_attribute(a) for a in attributes if isinstance(a, dict)]
    fm_summaries = [summarize_metric(m, "factMetric") for m in fact_metrics if isinstance(m, dict)]
    custom_summaries = [summarize_metric(m, "metric") for m in metrics if isinstance(m, dict)]
    table_summaries = [summarize_table(t) for t in tables if isinstance(t, dict)]
    sf_summaries = [summarize_security_filter(sf) for sf in security_filters if isinstance(sf, dict)]
    hierarchy_summary = summarize_hierarchy(hierarchy_body)

    metric_family_counts = Counter()
    for m in fm_summaries + custom_summaries:
        if m.get("hasConditionality"):
            metric_family_counts["conditional"] += 1
        if m.get("hasDimensionality"):
            metric_family_counts["level"] += 1
        if m.get("hasTransformation"):
            metric_family_counts["transformation"] += 1
        if m.get("isCompound"):
            metric_family_counts["compound"] += 1
        if m.get("isSmart"):
            metric_family_counts["smart"] += 1

    return {
        "id": oid(item) or oid(model_body),
        "name": info.get("name") or oname(item),
        "subType": info.get("subType") or DATA_MODEL_SUBTYPE,
        "destinationFolderId": info.get("destinationFolderId") or model_body.get("destinationFolderId"),
        "schemaFolderId": model_body.get("schemaFolderId"),
        "dataServeMode": model_body.get("dataServeMode"),
        "dateCreated": info.get("dateCreated"),
        "dateModified": info.get("dateModified"),
        "owner": (info.get("owner") or {}).get("name") if isinstance(info.get("owner"), dict) else None,
        "counts": {
            "attributes": len(attr_summaries),
            "factMetrics": len(fm_summaries),
            "customMetrics": len(custom_summaries),
            "tables": len(table_summaries),
            "securityFilters": len(sf_summaries),
            "links": len(links),
            "externalDataModels": len(external_models),
            "folders": len(folders),
            "hierarchyRelationships": hierarchy_summary.get("relationshipCount"),
        },
        "metricFamilyCounts": dict(metric_family_counts),
        "subresourceStatuses": {k: {"status": v.get("status"), "ok": v.get("ok"), "error": v.get("error")} for k, v in sub.items()},
        "attributes": attr_summaries,
        "factMetrics": fm_summaries,
        "customMetrics": custom_summaries,
        "tables": table_summaries,
        "securityFilters": sf_summaries,
        "hierarchy": hierarchy_summary,
        "links": [{"id": oid(l), "name": oname(l), "subType": (l.get("information") or {}).get("subType")} for l in links if isinstance(l, dict)][:20],
        "externalDataModels": [{"id": oid(e), "name": oname(e)} for e in external_models if isinstance(e, dict)][:20],
    }


def portfolio_analysis(models: list[dict[str, Any]]) -> dict[str, Any]:
    serve_modes = Counter(m.get("dataServeMode") or "" for m in models)
    table_types = Counter()
    attr_form_types = Counter()
    metric_family = Counter()
    rel_types = Counter()
    table_dbs = Counter()
    sec_filter_qual_types = Counter()
    totals = Counter()
    for m in models:
        counts = m.get("counts") or {}
        for k, v in counts.items():
            if isinstance(v, int):
                totals[k] += v
        for t in m.get("tables") or []:
            table_types[t.get("physicalType") or ""] += 1
            if t.get("databaseInstanceId"):
                table_dbs[t.get("databaseInstanceId")] += 1
        for a in m.get("attributes") or []:
            for f in a.get("forms") or []:
                attr_form_types[f.get("type") or f.get("category") or ""] += 1
        for mt in (m.get("factMetrics") or []) + (m.get("customMetrics") or []):
            for flag in ("hasConditionality", "hasDimensionality", "hasTransformation", "isCompound", "isSmart"):
                if mt.get(flag):
                    metric_family[flag] += 1
        for sample in (m.get("hierarchy") or {}).get("sampleRelationships") or []:
            rel_types[sample.get("type") or ""] += 1
        for sf in m.get("securityFilters") or []:
            sec_filter_qual_types[sf.get("qualificationType") or ""] += 1
    return {
        "modelCount": len(models),
        "totals": dict(totals),
        "dataServeModes": dict(serve_modes.most_common()),
        "physicalTableTypes": dict(table_types.most_common(10)),
        "attributeFormTypes": dict(attr_form_types.most_common(15)),
        "metricFamilyFlagCounts": dict(metric_family.most_common()),
        "hierarchyRelationshipTypes": dict(rel_types.most_common(10)),
        "securityFilterQualificationTypes": dict(sec_filter_qual_types.most_common(10)),
        "topDatabaseInstances": dict(table_dbs.most_common(10)),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    add_auth_args(parser)
    parser.add_argument("--search-limit", type=int, default=200)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--max-models", type=int, default=0, help="0 = all visible data models")
    parser.add_argument("--model-name", default="", help="Optional substring filter on model names (case-insensitive)")
    parser.add_argument("--include-definition-bodies", action="store_true", help="Keep raw subresource bodies in output JSON. Large.")
    parser.add_argument("--out", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    client = client_from_args(args, Client)
    started = now_id()
    try:
        client.login()
        auth = client.auth()
        print(f"Logged in. project_id={client.project_id}", file=sys.stderr)

        print(f"Searching data models (type={DATA_MODEL_TYPE}, subType={DATA_MODEL_SUBTYPE})...", file=sys.stderr)
        items = client.search_data_models(args.search_limit)
        if args.model_name:
            needle = args.model_name.lower()
            items = [i for i in items if needle in (oname(i) or "").lower()]
        if args.max_models > 0:
            items = items[: args.max_models]
        print(f"Found {len(items)} data models. Reading subresources with {args.workers} workers...", file=sys.stderr)

        definitions = read_parallel(
            items, lambda item: read_model(auth, item), args.workers, progress_every=10)

        models = [summarize_model(item, definitions.get(oid(item) or "", {})) for item in items]
        inventory: dict[str, Any] = {
            "runId": started,
            "base": args.base,
            "projectName": args.project_name,
            "projectId": client.project_id,
            "dataModelCount": len(models),
            "portfolio": portfolio_analysis(models),
            "models": models,
        }
        if args.include_definition_bodies:
            inventory["definitionBodies"] = definitions

        path = dump_inventory(inventory, args.out, "strategy-mosaic-inventory", started)

        print(json.dumps({
            "ok": True,
            "runId": started,
            "projectId": client.project_id,
            "out": path,
            "modelCount": len(models),
            "portfolioTotals": inventory["portfolio"]["totals"],
            "dataServeModes": inventory["portfolio"]["dataServeModes"],
            "metricFamilyFlagCounts": inventory["portfolio"]["metricFamilyFlagCounts"],
        }, indent=2))
        return 0
    finally:
        client.logout()


if __name__ == "__main__":
    raise SystemExit(main())
