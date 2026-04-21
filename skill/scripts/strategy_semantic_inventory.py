#!/usr/bin/env python3
"""Inventory classic Strategy semantic objects in a project.

Read-only field study helper for legacy/project semantic-layer learning:
attributes, facts, metrics, filters, prompts, and user hierarchies. Also
summarizes the system hierarchy relationship graph. Writes raw inventory to
/tmp by default so the repo stores compact lessons, not bulky response payloads.
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import sys
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import requests


DEFAULT_BASE = "https://<env-id>.customer.cloud.microstrategy.com/MicroStrategyLibrary"
DEFAULT_USER = "arpan"
DEFAULT_PROJECT_NAME = "MicroStrategy Tutorial"

FAMILIES = {
    "attributes": {"type": 12, "path": "/api/model/attributes/{id}", "singular": "attribute"},
    "facts": {"type": 13, "path": "/api/model/facts/{id}", "singular": "fact"},
    "metrics": {"type": 4, "path": "/api/model/metrics/{id}", "singular": "metric"},
    "filters": {"type": 1, "path": "/api/model/filters/{id}", "singular": "filter"},
    "prompts": {"type": 10, "path": "/api/model/prompts/{id}", "singular": "prompt"},
    "hierarchies": {"path": "/api/model/hierarchies/{id}", "singular": "hierarchy"},
}


def now_id() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def response_json(resp: requests.Response) -> Any:
    if not resp.text:
        return {}
    try:
        return resp.json()
    except Exception:
        return {"_text": resp.text[:500]}


def items_from_payload(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("result", "results", "objects", "items", "data"):
        value = payload.get(key)
        if isinstance(value, list):
            return [x for x in value if isinstance(x, dict)]
    return []


def oid(obj: dict[str, Any]) -> str | None:
    return obj.get("id") or obj.get("objectId") or obj.get("object_id")


def oname(obj: dict[str, Any]) -> str:
    info = obj.get("information")
    if isinstance(info, dict) and info.get("name"):
        return str(info["name"])
    return str(obj.get("name") or obj.get("display") or obj.get("title") or "")


def subtype(obj: dict[str, Any]) -> str:
    info = obj.get("information")
    if isinstance(info, dict) and info.get("subType"):
        return str(info["subType"])
    return str(obj.get("subtype") or obj.get("subType") or "")


def ancestors_path(obj: dict[str, Any]) -> str:
    ancestors = obj.get("ancestors")
    if not isinstance(ancestors, list):
        return ""
    names = [str(a.get("name") or "") for a in reversed(ancestors) if isinstance(a, dict) and a.get("name")]
    return " / ".join(names)


def walk(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def collect_texts(value: Any, limit: int = 8) -> list[str]:
    texts: list[str] = []
    for node in walk(value):
        text = node.get("text")
        if isinstance(text, str) and text and text not in texts:
            texts.append(text)
            if len(texts) >= limit:
                break
    return texts


def collect_table_refs(value: Any) -> list[dict[str, Any]]:
    refs: dict[str, dict[str, Any]] = {}
    for node in walk(value):
        object_id = node.get("objectId") or node.get("id")
        name = node.get("name") or node.get("tableName")
        st = str(node.get("subType") or node.get("subtype") or "").lower()
        if object_id and ("table" in st or "logical_table" in st):
            refs[str(object_id)] = {"id": str(object_id), "name": str(name or object_id), "subType": st}
    return sorted(refs.values(), key=lambda x: x.get("name") or "")


def collect_object_refs(value: Any) -> Counter:
    counts: Counter = Counter()
    for node in walk(value):
        st = str(node.get("subType") or node.get("subtype") or node.get("type") or "").lower()
        if st:
            counts[st] += 1
    return counts


def collect_named_values(value: Any, key: str, limit: int = 20) -> list[str]:
    values: list[str] = []
    for node in walk(value):
        item = node.get(key)
        if isinstance(item, str) and item and item not in values:
            values.append(item)
            if len(values) >= limit:
                break
    return values


def collect_refs_by_subtype(value: Any, wanted: str, limit: int = 10) -> list[dict[str, str]]:
    refs: dict[str, dict[str, str]] = {}
    wanted = wanted.lower()
    for node in walk(value):
        sub_type = str(node.get("subType") or node.get("subtype") or "").lower()
        object_id = node.get("objectId") or node.get("id")
        if object_id and wanted in sub_type:
            refs[str(object_id)] = {
                "id": str(object_id),
                "name": str(node.get("name") or object_id),
                "subType": sub_type,
            }
    return list(refs.values())[:limit]


def expression_kind(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    expr = value.get("expression") or value.get("qualification") or value.get("definition") or value
    if isinstance(expr, dict):
        tree = expr.get("tree") or expr.get("predicateTree")
        if isinstance(tree, dict) and tree.get("type"):
            return str(tree["type"])
        if expr.get("text"):
            return "text"
    return ""


@dataclass
class Auth:
    base: str
    headers: dict[str, str]
    cookies: dict[str, str]
    project_id: str


class Client:
    def __init__(self, base: str, username: str, password: str, login_mode: int, project_name: str):
        self.base = base.rstrip("/")
        self.username = username
        self.password = password
        self.login_mode = login_mode
        self.project_name = project_name
        self.session = requests.Session()
        self.session.headers.update({"Accept": "application/json", "Content-Type": "application/json"})
        self.project_id = ""

    def login(self) -> None:
        resp = self.session.post(
            f"{self.base}/api/auth/login",
            json={"username": self.username, "password": self.password, "loginMode": self.login_mode},
            timeout=60,
        )
        if resp.status_code != 204:
            raise RuntimeError(f"login failed: {resp.status_code} {resp.text[:300]}")
        token = resp.headers.get("X-MSTR-AuthToken") or resp.headers.get("X-Mstr-Authtoken")
        if not token:
            raise RuntimeError("login succeeded but no X-MSTR-AuthToken header was returned")
        self.session.headers["X-MSTR-AuthToken"] = token
        projects = response_json(self.session.get(f"{self.base}/api/projects", timeout=60))
        for project in projects:
            if project.get("name") == self.project_name or project.get("id") == self.project_name:
                self.project_id = project["id"]
                self.session.headers["X-MSTR-ProjectID"] = self.project_id
                return
        raise RuntimeError(f"project not found: {self.project_name}")

    def logout(self) -> None:
        try:
            self.session.post(f"{self.base}/api/auth/logout", timeout=20)
        except Exception:
            pass

    def auth(self) -> Auth:
        return Auth(self.base, dict(self.session.headers), self.session.cookies.get_dict(), self.project_id)

    def search_all(self, obj_type: int, limit: int) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        offset = 0
        while True:
            resp = self.session.get(
                f"{self.base}/api/searches/results",
                params={"name": "", "type": obj_type, "pattern": 4, "limit": limit, "offset": offset, "getAncestors": "true"},
                timeout=60,
            )
            if not resp.ok:
                raise RuntimeError(f"search type {obj_type} failed: {resp.status_code} {resp.text[:300]}")
            rows = items_from_payload(response_json(resp))
            out.extend(rows)
            if len(rows) < limit:
                break
            offset += limit
        seen = set()
        deduped = []
        for item in out:
            object_id = oid(item)
            if not object_id or object_id in seen:
                continue
            seen.add(object_id)
            deduped.append(item)
        return deduped

    def list_hierarchies(self) -> list[dict[str, Any]]:
        resp = self.session.get(f"{self.base}/api/model/hierarchies", timeout=60)
        if not resp.ok:
            raise RuntimeError(f"hierarchy list failed: {resp.status_code} {resp.text[:300]}")
        payload = response_json(resp)
        if isinstance(payload, dict) and isinstance(payload.get("hierarchies"), list):
            return [x for x in payload["hierarchies"] if isinstance(x, dict)]
        return items_from_payload(payload)

    def system_hierarchy(self) -> dict[str, Any]:
        resp = self.session.get(f"{self.base}/api/model/systemHierarchy", timeout=60)
        payload = response_json(resp)
        return {
            "ok": resp.ok,
            "status": resp.status_code,
            "body": payload if resp.ok else None,
            "error": None if resp.ok else str(payload)[:500],
        }


def read_definition(auth: Auth, family: str, item: dict[str, Any]) -> dict[str, Any]:
    object_id = oid(item)
    if not object_id:
        return {"ok": False, "error": "missing object id"}
    path = FAMILIES[family]["path"].format(id=object_id)
    param_attempts = [{"showExpressionAs": "tree"}]
    if family == "filters":
        param_attempts[0]["showFilterTokens"] = "true"
    param_attempts.append({"showExpressionAs": "tokens"})
    param_attempts.append({})
    last_error = ""
    try:
        for params in param_attempts:
            resp = requests.get(f"{auth.base}{path}", headers=auth.headers, cookies=auth.cookies, params=params, timeout=45)
            payload = response_json(resp)
            if resp.ok:
                return {
                    "ok": True,
                    "status": resp.status_code,
                    "params": params,
                    "body": payload,
                    "error": None,
                }
            last_error = f"{resp.status_code} {str(payload)[:500]}"
            if resp.status_code not in (400, 404, 500):
                break
        return {"ok": False, "status": resp.status_code, "params": params, "body": None, "error": last_error}
    except Exception as exc:
        return {"ok": False, "status": None, "params": None, "body": None, "error": str(exc)[:500]}


def summarize_item(family: str, item: dict[str, Any], definition: dict[str, Any] | None) -> dict[str, Any]:
    body = definition.get("body") if definition else None
    info = body.get("information") if isinstance(body, dict) else {}
    table_refs = collect_table_refs(body) if body else []
    texts = collect_texts(body) if body else []
    obj_refs = collect_object_refs(body) if body else Counter()
    summary = {
        "id": oid(item),
        "name": (info or {}).get("name") or oname(item),
        "subtype": (info or {}).get("subType") or subtype(item),
        "ancestors": ancestors_path(item),
        "definitionStatus": definition.get("status") if definition else None,
        "definitionParams": definition.get("params") if definition else None,
        "definitionOk": bool(definition and definition.get("ok")),
        "definitionAttempted": definition is not None,
        "definitionError": definition.get("error") if definition and not definition.get("ok") else None,
        "tableRefs": table_refs[:20],
        "expressionKind": expression_kind(body) if body else "",
        "texts": texts[:5],
        "functionNames": collect_named_values(body, "function")[:10] if body else [],
        "operatorNames": collect_named_values(body, "operator")[:10] if body else [],
        "objectRefTypes": dict(obj_refs.most_common(10)),
    }
    if family == "attributes" and isinstance(body, dict):
        summary["formCount"] = len(body.get("forms") or [])
        summary["relationshipCount"] = len(body.get("relationships") or [])
        summary["childAttributeCount"] = len(body.get("childAttributes") or [])
        summary["forms"] = [
            {
                "id": f.get("id"),
                "name": f.get("name"),
                "category": f.get("category") or f.get("formCategory"),
                "type": f.get("type") or f.get("formType"),
                "displayFormat": f.get("displayFormat"),
                "texts": collect_texts(f, 3),
            }
            for f in (body.get("forms") or [])[:8]
            if isinstance(f, dict)
        ]
    if family == "facts" and isinstance(body, dict):
        summary["factExpressions"] = collect_texts(body.get("expressions") or body, 8)
        summary["extensionCount"] = len(body.get("extensions") or [])
        summary["entryLevelCount"] = len(body.get("entryLevel") or [])
    if family == "metrics" and isinstance(body, dict):
        expr = body.get("expression") or {}
        summary["metricExpression"] = expr.get("text") if isinstance(expr, dict) else ""
        summary["metricFunctions"] = collect_named_values(body, "function", 10)
        summary["nestedMetrics"] = collect_refs_by_subtype(body, "metric", 10)
        summary["hasConditionality"] = "conditionality" in body
        summary["hasDimensionality"] = "dimty" in body or "dimensionality" in body
        summary["hasTransformation"] = "transformation" in body
    if family == "filters" and isinstance(body, dict):
        qual = body.get("qualification") or {}
        summary["filterText"] = (qual.get("text") if isinstance(qual, dict) else "") or (texts[0] if texts else "")
        summary["qualificationTypes"] = collect_named_values(qual, "type", 12) if isinstance(qual, dict) else []
        summary["promptRefs"] = collect_refs_by_subtype(body, "prompt", 8)
    if family == "prompts" and isinstance(body, dict):
        summary["promptType"] = (info or {}).get("subType") or body.get("type") or subtype(item)
        summary["promptObjectRefs"] = dict(collect_object_refs(body).most_common(10))
    if family == "hierarchies" and isinstance(body, dict):
        summary["useAsDrillHierarchy"] = body.get("useAsDrillHierarchy")
        summary["attributeCount"] = len(body.get("attributes") or [])
        summary["relationshipCount"] = len(body.get("relationships") or [])
        summary["attributes"] = [
            {"id": a.get("objectId") or a.get("id"), "name": a.get("name"), "entryPoint": a.get("entryPoint")}
            for a in (body.get("attributes") or [])[:20]
            if isinstance(a, dict)
        ]
    return summary


def system_hierarchy_analysis(definition: dict[str, Any]) -> dict[str, Any]:
    body = definition.get("body") if definition else None
    if not isinstance(body, dict):
        return {
            "definitionStatus": definition.get("status") if definition else None,
            "definitionOk": False,
            "definitionError": definition.get("error") if definition else "not read",
        }
    relationships = body.get("relationships") or []
    isolated = body.get("isolatedAttributes") or []
    relationship_types = Counter()
    relationship_tables = Counter()
    parent_counts = Counter()
    child_counts = Counter()
    samples = []
    for rel in relationships:
        if not isinstance(rel, dict):
            continue
        relationship_types[rel.get("relationshipType") or ""] += 1
        table = rel.get("relationshipTable") or {}
        if isinstance(table, dict):
            relationship_tables[table.get("name") or table.get("objectId") or ""] += 1
        parent = rel.get("parent") or {}
        child = rel.get("child") or {}
        if isinstance(parent, dict):
            parent_counts[parent.get("name") or parent.get("objectId") or ""] += 1
        if isinstance(child, dict):
            child_counts[child.get("name") or child.get("objectId") or ""] += 1
        if len(samples) < 20:
            samples.append({
                "parent": parent.get("name") if isinstance(parent, dict) else None,
                "child": child.get("name") if isinstance(child, dict) else None,
                "type": rel.get("relationshipType"),
                "table": table.get("name") if isinstance(table, dict) else None,
            })
    return {
        "definitionStatus": definition.get("status"),
        "definitionOk": True,
        "relationshipCount": len(relationships),
        "isolatedAttributeCount": len(isolated),
        "relationshipTypes": dict(relationship_types.most_common(10)),
        "topRelationshipTables": dict(relationship_tables.most_common(15)),
        "topParents": dict(parent_counts.most_common(15)),
        "topChildren": dict(child_counts.most_common(15)),
        "samples": samples,
    }


def family_analysis(rows: list[dict[str, Any]]) -> dict[str, Any]:
    subtype_counts = Counter(str(r.get("subtype") or "") for r in rows)
    ancestor_counts = Counter((r.get("ancestors") or "").split(" / ")[0] if r.get("ancestors") else "" for r in rows)
    table_counts = Counter()
    expr_counts = Counter()
    function_counts = Counter()
    operator_counts = Counter()
    status_counts = Counter()
    error_counts = Counter()
    attempted = sum(1 for r in rows if r.get("definitionAttempted"))
    read_ok = sum(1 for r in rows if r.get("definitionOk"))
    samples = []
    for row in rows:
        expr_counts[row.get("expressionKind") or ""] += 1
        status_counts[str(row.get("definitionStatus"))] += 1
        if row.get("definitionError"):
            error_counts[str(row.get("definitionError"))[:160]] += 1
        for name in row.get("functionNames") or []:
            function_counts[name] += 1
        for name in row.get("operatorNames") or []:
            operator_counts[name] += 1
        for table in row.get("tableRefs") or []:
            table_counts[table.get("name") or table.get("id")] += 1
        if len(samples) < 12:
            samples.append({
                "name": row.get("name"),
                "id": row.get("id"),
                "subtype": row.get("subtype"),
                "tables": [t.get("name") for t in (row.get("tableRefs") or [])[:4]],
                "text": (row.get("metricExpression") or row.get("filterText") or (row.get("texts") or [""])[0])[:180],
            })
    return {
        "count": len(rows),
        "definitionReadAttempted": attempted,
        "definitionReadOk": read_ok,
        "definitionReadFailed": attempted - read_ok,
        "subtypes": dict(subtype_counts.most_common(15)),
        "ancestorRoots": dict(ancestor_counts.most_common(10)),
        "topReferencedTables": dict(table_counts.most_common(15)),
        "expressionKinds": dict(expr_counts.most_common(15)),
        "definitionStatuses": dict(status_counts.most_common(10)),
        "topDefinitionErrors": dict(error_counts.most_common(10)),
        "functionNames": dict(function_counts.most_common(20)),
        "operatorNames": dict(operator_counts.most_common(20)),
        "samples": samples,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default=os.environ.get("MSTR_BASE", DEFAULT_BASE))
    parser.add_argument("--user", default=os.environ.get("MSTR_USER", DEFAULT_USER))
    parser.add_argument("--password", default=os.environ.get("MSTR_PASSWORD", ""))
    parser.add_argument("--login-mode", type=int, default=int(os.environ.get("MSTR_LOGIN_MODE", "1")))
    parser.add_argument("--project-name", default=os.environ.get("MSTR_PROJECT_NAME", DEFAULT_PROJECT_NAME))
    parser.add_argument("--families", nargs="*", choices=sorted(FAMILIES), default=sorted(FAMILIES))
    parser.add_argument("--search-limit", type=int, default=200)
    parser.add_argument("--max-definitions-per-family", type=int, default=0, help="0 means read every visible definition.")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--include-definition-bodies", action="store_true", help="Write successful definition payloads to the output JSON. Use /tmp; do not commit bulky payloads.")
    parser.add_argument("--skip-system-hierarchy", action="store_true", help="Skip the one-call /api/model/systemHierarchy summary.")
    parser.add_argument("--out", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    password = args.password or getpass.getpass("Password: ")
    client = Client(args.base, args.user, password, args.login_mode, args.project_name)
    started = now_id()
    try:
        client.login()
        auth = client.auth()
        inventory: dict[str, Any] = {
            "runId": started,
            "base": args.base,
            "projectName": args.project_name,
            "projectId": client.project_id,
            "families": {},
            "analysis": {},
        }
        if args.include_definition_bodies:
            inventory["definitionBodies"] = {}

        for family in args.families:
            spec = FAMILIES[family]
            print(f"Searching {family}...", file=sys.stderr)
            if family == "hierarchies":
                items = client.list_hierarchies()
            else:
                items = client.search_all(spec["type"], args.search_limit)
            if args.max_definitions_per_family > 0:
                to_read = items[: args.max_definitions_per_family]
            else:
                to_read = items
            print(f"Reading {len(to_read)}/{len(items)} {family} definitions...", file=sys.stderr)
            definitions: dict[str, dict[str, Any]] = {}
            with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
                futures = {pool.submit(read_definition, auth, family, item): item for item in to_read}
                for future in as_completed(futures):
                    item = futures[future]
                    definitions[oid(item) or ""] = future.result()
            rows = [summarize_item(family, item, definitions.get(oid(item) or "")) for item in items]
            inventory["families"][family] = rows
            inventory["analysis"][family] = family_analysis(rows)
            if args.include_definition_bodies:
                inventory["definitionBodies"][family] = {
                    key: {"status": value.get("status"), "params": value.get("params"), "body": value.get("body"), "error": value.get("error")}
                    for key, value in definitions.items()
                    if value.get("ok")
                }

        if not args.skip_system_hierarchy:
            print("Reading system hierarchy...", file=sys.stderr)
            hierarchy = client.system_hierarchy()
            inventory["systemHierarchy"] = system_hierarchy_analysis(hierarchy)
            if args.include_definition_bodies and hierarchy.get("ok"):
                inventory["systemHierarchyBody"] = hierarchy.get("body")

        path = args.out or f"/tmp/strategy-tutorial-semantic-inventory-{started}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(inventory, f, indent=2)
        print(json.dumps({
            "ok": True,
            "runId": started,
            "projectId": client.project_id,
            "out": path,
            "counts": {k: v["count"] for k, v in inventory["analysis"].items()},
            "definitionReadOk": {k: v["definitionReadOk"] for k, v in inventory["analysis"].items()},
            "definitionReadFailed": {k: v["definitionReadFailed"] for k, v in inventory["analysis"].items()},
        }, indent=2))
        return 0
    finally:
        client.logout()


if __name__ == "__main__":
    raise SystemExit(main())
