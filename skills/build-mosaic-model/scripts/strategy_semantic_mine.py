#!/usr/bin/env python3
"""Mine a classic Strategy semantic layer for Mosaic model candidates.

Read-only helper for two common discovery paths:
- top-down: reports/documents -> semantic objects -> tables
- reverse: table -> attributes/facts/metrics -> reports/documents

Credentials are runtime-only. Do not write secrets or exported business data.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _client import (  # noqa: E402
    BaseMSTR, add_auth_args, client_from_args, items_from_payload, response_json,
    normalize_id as oid,  # flat accessor — search rows expose `id`, never `information.objectId`
)


OBJECT_TYPES = {
    "filter": 1,
    "report": 3,
    "metric": 4,
    "template": 5,
    "prompt": 10,
    "attribute": 12,
    "fact": 13,
    "table": 15,
    "document": 55,
}

TYPE_NAMES = {v: k for k, v in OBJECT_TYPES.items()}
TYPE_ALIASES = {
    "filter": OBJECT_TYPES["filter"],
    "report": OBJECT_TYPES["report"],
    "report_definition": OBJECT_TYPES["report"],
    "report definition": OBJECT_TYPES["report"],
    "metric": OBJECT_TYPES["metric"],
    "prompt": OBJECT_TYPES["prompt"],
    "attribute": OBJECT_TYPES["attribute"],
    "fact": OBJECT_TYPES["fact"],
    "table": OBJECT_TYPES["table"],
    "document": OBJECT_TYPES["document"],
    "document_definition": OBJECT_TYPES["document"],
    "document definition": OBJECT_TYPES["document"],
}


def oname(obj: dict[str, Any]) -> str:
    # Stays local: _client.normalize_name also falls back to `username`, which this
    # script's flat accessor deliberately does not.
    return str(obj.get("name") or obj.get("display") or obj.get("title") or "")


def otype(obj: dict[str, Any]) -> int | None:
    raw = obj.get("type") or obj.get("objectType")
    if isinstance(raw, int):
        return raw
    if isinstance(raw, str) and raw.isdigit():
        return int(raw)
    if isinstance(raw, str):
        return TYPE_ALIASES.get(raw.replace("-", "_").replace(" ", "_").casefold()) or TYPE_ALIASES.get(raw.casefold())
    return None


def type_label(value: int | None) -> str:
    if value is None:
        return "unknown"
    return TYPE_NAMES.get(value, str(value))


def model_name(value: Any) -> str:
    if isinstance(value, dict):
        info = value.get("information")
        if isinstance(info, dict) and info.get("name"):
            return str(info["name"])
        if value.get("name"):
            return str(value["name"])
    return ""


def parse_seed(raw: str, default_type: int | None = None) -> dict[str, Any]:
    raw = raw.strip()
    if not raw:
        raise ValueError("empty seed")
    if ";" in raw:
        left, right = raw.split(";", 1)
        return {"id": left.strip(), "type": int(right.strip())}
    if re.fullmatch(r"[0-9A-Fa-f]{32}", raw):
        return {"id": raw.upper(), "type": default_type}
    return {"name": raw, "type": default_type}


class MSTR(BaseMSTR):
    """Mining client — BaseMSTR + legacy-semantic-specific search helpers."""

    def quick_search(self, name: str, obj_type: int | None = None, limit: int = 50) -> list[dict[str, Any]]:
        return self.search_results(name, obj_type, limit=limit, paginate=False)

    def quick_dependents(self, object_id: str, target_type: int | None = None, limit: int = 200) -> list[dict[str, Any]]:
        # Bespoke search-results call (usesObjectId lineage params, non-raising) —
        # deliberately NOT routed through BaseMSTR.search_results.
        params: dict[str, Any] = {
            "usesObjectId": object_id,
            "usesObjectProjectId": self.project_id,
            "limit": limit,
            "getAncestors": "true",
        }
        if target_type is not None:
            params["type"] = target_type
        resp = self.try_request("GET", "/api/searches/results", params=params)
        return items_from_payload(response_json(resp)) if resp is not None else []

    def metadata_search(self, params: dict[str, Any], limit: int = 200) -> list[dict[str, Any]]:
        q = {"limit": limit, **params}
        resp = self.try_request("POST", "/api/metadataSearches/results", params=q, json={})
        if resp is None:
            resp = self.try_request("GET", "/api/metadataSearches/results", params=q)
        if resp is None:
            return []
        payload = response_json(resp)
        rows = items_from_payload(payload)
        if rows:
            return rows
        search_id = payload.get("id") or payload.get("searchId") if isinstance(payload, dict) else None
        if not search_id:
            return []
        follow = self.try_request("GET", "/api/metadataSearches/results", params={"id": search_id, "limit": limit})
        return items_from_payload(response_json(follow)) if follow is not None else []

    def read_model_object(self, object_id: str, obj_type: int) -> dict[str, Any] | None:
        path_by_type = {
            OBJECT_TYPES["attribute"]: f"/api/model/attributes/{object_id}",
            OBJECT_TYPES["metric"]: f"/api/model/metrics/{object_id}",
            OBJECT_TYPES["fact"]: f"/api/model/facts/{object_id}",
            OBJECT_TYPES["filter"]: f"/api/model/filters/{object_id}",
            OBJECT_TYPES["table"]: f"/api/model/tables/{object_id}",
        }
        path = path_by_type.get(obj_type)
        if not path:
            return None
        resp = self.try_request("GET", path, params={"showExpressionAs": "tree"})
        return response_json(resp) if resp is not None else None


@dataclass
class MineState:
    seeds: list[dict[str, Any]] = field(default_factory=list)
    objects: dict[str, dict[str, Any]] = field(default_factory=dict)
    tables: dict[str, dict[str, Any]] = field(default_factory=dict)
    table_scores: Counter = field(default_factory=Counter)
    table_reasons: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))
    warnings: list[str] = field(default_factory=list)

    def add_object(self, obj: dict[str, Any], reason: str = "") -> None:
        object_id = oid(obj)
        if not object_id:
            return
        shaped = {
            "id": object_id,
            "name": oname(obj),
            "type": otype(obj),
            "typeName": type_label(otype(obj)),
            "subtype": obj.get("subtype") or obj.get("subType"),
            "ancestors": obj.get("ancestors"),
        }
        if reason:
            shaped.setdefault("reasons", []).append(reason)
        existing = self.objects.get(object_id)
        if existing:
            existing.setdefault("reasons", []).extend(shaped.get("reasons", []))
        else:
            self.objects[object_id] = shaped

    def add_table(self, obj: dict[str, Any], score: int, reason: str) -> None:
        object_id = oid(obj)
        if not object_id:
            return
        self.tables.setdefault(object_id, {
            "id": object_id,
            "name": oname(obj) or obj.get("tableName") or object_id,
            "type": otype(obj) or OBJECT_TYPES["table"],
            "typeName": "table",
            "subtype": obj.get("subtype") or obj.get("subType"),
        })
        self.table_scores[object_id] += score
        self.table_reasons[object_id].append(reason)


def resolve_seed(m: MSTR, seed: dict[str, Any], fallback_types: list[int]) -> dict[str, Any]:
    if seed.get("id"):
        out = {"id": seed["id"], "type": seed.get("type"), "name": seed.get("name") or seed["id"]}
        if out.get("type"):
            model = m.read_model_object(out["id"], out["type"])
            name = model_name(model)
            if name:
                out["name"] = name
        return out
    name = seed["name"]
    types = [seed["type"]] if seed.get("type") else fallback_types
    candidates = []
    for obj_type in types:
        candidates.extend(m.quick_search(name, obj_type=obj_type, limit=25))
    exact = [c for c in candidates if oname(c).casefold() == name.casefold()]
    chosen = exact[0] if exact else (candidates[0] if candidates else None)
    if not chosen:
        raise RuntimeError(f"could not resolve seed '{name}'")
    return {"id": oid(chosen), "type": otype(chosen), "name": oname(chosen), "raw": chosen}


def search_dependencies(m: MSTR, seed: dict[str, Any], target_types: list[int], recursive: bool = True) -> list[dict[str, Any]]:
    if not seed.get("id") or not seed.get("type"):
        return []
    out = []
    for target_type in target_types:
        rows = m.metadata_search({
            "usedByObject": f"{seed['id']};{seed['type']}",
            "usedByRecursive": str(recursive).lower(),
            "type": target_type,
        })
        out.extend(rows)
    return dedupe_objects(out)


def search_dependents(m: MSTR, seed: dict[str, Any], target_types: list[int], recursive: bool = True) -> list[dict[str, Any]]:
    if not seed.get("id") or not seed.get("type"):
        return []
    out = []
    for target_type in target_types:
        rows = m.metadata_search({
            "usesObject": f"{seed['id']};{seed['type']}",
            "usesRecursive": str(recursive).lower(),
            "type": target_type,
        })
        if not rows:
            rows = m.quick_dependents(seed["id"], target_type=target_type)
        out.extend(rows)
    return dedupe_objects(out)


def dedupe_objects(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    out = []
    for item in items:
        object_id = oid(item) or json.dumps(item, sort_keys=True)
        if object_id in seen:
            continue
        seen.add(object_id)
        out.append(item)
    return out


def semantic_refs_from_json(value: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            object_id = oid(node)
            object_type = otype(node)
            if object_id and object_type in {
                OBJECT_TYPES["attribute"],
                OBJECT_TYPES["metric"],
                OBJECT_TYPES["fact"],
                OBJECT_TYPES["filter"],
                OBJECT_TYPES["prompt"],
                OBJECT_TYPES["table"],
            }:
                found.append({
                    "id": object_id,
                    "name": oname(node) or object_id,
                    "type": object_type,
                    "subtype": node.get("subtype") or node.get("subType"),
                })
            for child in node.values():
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(value)
    return dedupe_objects(found)


def runtime_components_for_seed(m: MSTR, seed: dict[str, Any]) -> list[dict[str, Any]]:
    object_type = seed.get("type")
    object_id = seed.get("id")
    if not object_id:
        return []
    payloads: list[Any] = []
    if object_type == OBJECT_TYPES["report"]:
        resp = m.try_request("POST", f"/api/reports/{object_id}/instances", json={})
        if resp is not None:
            payloads.append(response_json(resp))
    elif object_type == OBJECT_TYPES["document"]:
        definition = m.try_request("GET", f"/api/documents/{object_id}/definition")
        if definition is not None:
            payloads.append(response_json(definition))
        instance = m.try_request("POST", f"/api/documents/{object_id}/instances", json={})
        if instance is not None:
            payloads.append(response_json(instance))

    out: list[dict[str, Any]] = []
    for payload in payloads:
        out.extend(semantic_refs_from_json(payload))
    return dedupe_objects(out)


def table_refs_from_json(value: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []

    def walk(node: Any, parent_key: str = "") -> None:
        if isinstance(node, dict):
            object_id = node.get("objectId") or node.get("id")
            name = node.get("name") or node.get("tableName")
            subtype = str(node.get("subType") or node.get("subtype") or "").lower()
            key_hint = parent_key.lower()
            if object_id and ("table" in subtype or "table" in key_hint):
                found.append({
                    "id": object_id,
                    "name": name or object_id,
                    "type": OBJECT_TYPES["table"],
                    "subtype": node.get("subType") or node.get("subtype"),
                })
            for key, child in node.items():
                walk(child, key)
        elif isinstance(node, list):
            for child in node:
                walk(child, parent_key)

    walk(value)
    return dedupe_objects(found)


def scan_project_semantics_for_table(m: MSTR, table_id: str, target_types: list[int], limit: int) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for target_type in target_types:
        candidates = m.quick_search("", obj_type=target_type, limit=limit)
        for obj in candidates:
            object_id = oid(obj)
            if not object_id:
                continue
            model = m.read_model_object(object_id, target_type)
            if not model:
                continue
            refs = table_refs_from_json(model)
            if any(oid(ref) == table_id for ref in refs) or table_id in json.dumps(model, separators=(",", ":")):
                matches.append(obj)
    return dedupe_objects(matches)


def mine_top_down(m: MSTR, seeds: list[dict[str, Any]], args: argparse.Namespace) -> MineState:
    state = MineState()
    semantic_types = [OBJECT_TYPES[k] for k in ("attribute", "metric", "fact", "filter", "prompt", "table")]
    for raw_seed in seeds:
        seed = resolve_seed(m, raw_seed, [OBJECT_TYPES["report"], OBJECT_TYPES["document"]])
        state.seeds.append(seed)
        components = search_dependencies(m, seed, semantic_types, recursive=not args.direct_only)
        if not components:
            components = runtime_components_for_seed(m, seed)
            if components:
                state.warnings.append(f"metadata component search was empty for {seed['name']}; used runtime definition fallback")
        for obj in components:
            state.add_object(obj, f"used by {seed['name']}")
            if otype(obj) == OBJECT_TYPES["table"]:
                state.add_table(obj, 5, f"direct component of {seed['name']}")
            else:
                collect_tables_for_object(m, obj, state, f"via {type_label(otype(obj))} {oname(obj)}")
    return state


def mine_reverse(m: MSTR, seeds: list[dict[str, Any]], args: argparse.Namespace) -> MineState:
    state = MineState()
    semantic_types = [OBJECT_TYPES[k] for k in ("attribute", "metric", "fact", "filter", "prompt")]
    content_types = [OBJECT_TYPES["report"], OBJECT_TYPES["document"]]
    for raw_seed in seeds:
        seed = resolve_seed(m, raw_seed, [OBJECT_TYPES["table"]])
        state.seeds.append(seed)
        state.add_table({"id": seed["id"], "name": seed.get("name"), "type": OBJECT_TYPES["table"]}, 10, "input seed table")
        semantic = search_dependents(m, seed, semantic_types, recursive=not args.direct_only)
        if not semantic:
            state.warnings.append(
                f"lineage search was empty for table {seed.get('name')}; scanning visible attribute/fact definitions up to --scan-limit={args.scan_limit}"
            )
            semantic = scan_project_semantics_for_table(
                m,
                seed["id"],
                [OBJECT_TYPES["attribute"], OBJECT_TYPES["fact"]],
                args.scan_limit,
            )
            if semantic:
                state.warnings.append(f"definition scan found semantic objects for table {seed.get('name')}")
            else:
                state.warnings.append(f"definition scan found no semantic objects for table {seed.get('name')}")
        for obj in semantic:
            state.add_object(obj, f"depends on table {seed.get('name')}")
            collect_tables_for_object(m, obj, state, f"validated through {type_label(otype(obj))} {oname(obj)}")
        content = []
        for obj in semantic:
            content.extend(search_dependents(m, {"id": oid(obj), "type": otype(obj)}, content_types, recursive=True))
        for obj in dedupe_objects(content):
            state.add_object(obj, "downstream report/document")
    return state


def collect_tables_for_object(m: MSTR, obj: dict[str, Any], state: MineState, reason: str) -> None:
    object_id = oid(obj)
    obj_type = otype(obj)
    if not object_id or not obj_type:
        return
    if obj_type == OBJECT_TYPES["table"]:
        state.add_table(obj, 5, reason)
        return
    direct_tables = search_dependencies(m, {"id": object_id, "type": obj_type}, [OBJECT_TYPES["table"]], recursive=True)
    for table in direct_tables:
        state.add_table(table, 4, reason)
    model = m.read_model_object(object_id, obj_type)
    if model:
        for table in table_refs_from_json(model):
            state.add_table(table, 3, f"{reason}; model definition")


def summarize(state: MineState, args: argparse.Namespace) -> dict[str, Any]:
    semantic_by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for obj in state.objects.values():
        semantic_by_type[obj["typeName"]].append(obj)

    table_rows = []
    for table_id, table in state.tables.items():
        score = state.table_scores[table_id]
        reasons = list(dict.fromkeys(state.table_reasons[table_id]))
        table_rows.append({**table, "score": score, "reasons": reasons[:8]})
    table_rows.sort(key=lambda row: (-row["score"], row["name"]))

    return {
        "ok": True,
        "projectId": args.project_id or None,
        "mode": args.mode,
        "seeds": state.seeds,
        "candidateTables": table_rows[: args.max_tables],
        "semanticObjects": {k: sorted(v, key=lambda x: x.get("name") or "") for k, v in sorted(semantic_by_type.items())},
        "mosaicSeedPlan": {
            "tableIds": [row["id"] for row in table_rows[: args.max_tables]],
            "tableNames": [row["name"] for row in table_rows[: args.max_tables]],
            "candidateMetrics": [o for o in semantic_by_type.get("metric", [])[: args.max_objects]],
            "candidateAttributes": [o for o in semantic_by_type.get("attribute", [])[: args.max_objects]],
            "candidateFacts": [o for o in semantic_by_type.get("fact", [])[: args.max_objects]],
            "notes": [
                "Use these tables as candidate input to build-mosaic-model after resolving datasource/schema names.",
                "Preserve legacy metric formulas by reading metric definitions before recreating derived metrics.",
                "Confirm relationship grain and bridge tables before publishing a new Mosaic model.",
            ],
        },
        "warnings": state.warnings,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    add_auth_args(parser, project_id=True)
    parser.add_argument("--mode", choices=("top-down", "reverse"), required=True)
    parser.add_argument("--seed", action="append", default=[], help="Name, ID, or ID;type. Top-down seeds are reports/documents; reverse seeds are tables.")
    parser.add_argument("--report", action="append", default=[], help="Top-down report name or ID.")
    parser.add_argument("--document", action="append", default=[], help="Top-down document name or ID.")
    parser.add_argument("--table", action="append", default=[], help="Reverse table name or ID.")
    parser.add_argument("--direct-only", action="store_true", help="Disable recursive lineage expansion when endpoint supports it.")
    parser.add_argument("--max-tables", type=int, default=30)
    parser.add_argument("--max-objects", type=int, default=50)
    parser.add_argument("--scan-limit", type=int, default=40, help="Maximum visible objects per semantic type for reverse definition scan fallback.")
    parser.add_argument("--out", help="Optional JSON output path.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    m = client_from_args(args, MSTR)
    try:
        m.login()
        if args.project_id:
            m.project_id = args.project_id
            m.session.headers["X-MSTR-ProjectID"] = args.project_id
        else:
            project = m.resolve_project()
            args.project_id = project["id"]

        seeds: list[dict[str, Any]] = []
        seeds.extend(parse_seed(x) for x in args.seed)
        seeds.extend(parse_seed(x, OBJECT_TYPES["report"]) for x in args.report)
        seeds.extend(parse_seed(x, OBJECT_TYPES["document"]) for x in args.document)
        seeds.extend(parse_seed(x, OBJECT_TYPES["table"]) for x in args.table)
        if not seeds:
            raise RuntimeError("provide at least one --seed, --report, --document, or --table")

        state = mine_top_down(m, seeds, args) if args.mode == "top-down" else mine_reverse(m, seeds, args)
        output = summarize(state, args)
        text = json.dumps(output, indent=2)
        if args.out:
            with open(args.out, "w", encoding="utf-8") as f:
                f.write(text + "\n")
        print(text)
        return 0
    finally:
        m.logout()


if __name__ == "__main__":
    raise SystemExit(main())
