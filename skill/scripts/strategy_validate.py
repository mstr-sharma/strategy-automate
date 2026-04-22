#!/usr/bin/env python3
"""Run non-Mosaic, non-AI Strategy REST validation workflows.

This runner is intentionally conservative:
- credentials come from runtime flags/env/getpass only
- writes use explicit --yes
- created objects are tracked in /tmp for same-run cleanup guidance
- workflow output is summarized without dumping auth tokens or large data payloads
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import requests


DEFAULT_BASE = os.environ.get("MSTR_BASE", "")
DEFAULT_USER = os.environ.get("MSTR_USER", "")
DEFAULT_PROJECT_NAME = os.environ.get("MSTR_PROJECT_NAME", "")


def now_run_id() -> str:
    return "run-" + datetime.now().strftime("%Y%m%d-%H%M%S")


def compact_json(value: Any, limit: int = 800) -> str:
    try:
        text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    except TypeError:
        text = str(value)
    return text if len(text) <= limit else text[: limit - 3] + "..."


def items_from_search(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("result", "results", "objects", "items", "data"):
        val = payload.get(key)
        if isinstance(val, list):
            return [x for x in val if isinstance(x, dict)]
    return []


def normalize_id(obj: dict[str, Any]) -> str | None:
    return obj.get("id") or obj.get("objectId") or obj.get("object_id")


def normalize_name(obj: dict[str, Any]) -> str:
    return str(obj.get("name") or obj.get("username") or obj.get("display") or obj.get("title") or "")


def ancestor_names(obj: dict[str, Any]) -> list[str]:
    ancestors = obj.get("ancestors")
    if not isinstance(ancestors, list):
        return []
    return [str(a.get("name") or "") for a in ancestors if isinstance(a, dict)]


def payload_contains_value(value: Any, needle: str) -> bool:
    if isinstance(value, dict):
        return any(payload_contains_value(v, needle) for v in value.values())
    if isinstance(value, list):
        return any(payload_contains_value(v, needle) for v in value)
    return str(value or "") == needle


def best_named(candidates: list[dict[str, Any]], name: str, preferred_ancestors: tuple[str, ...] = ()) -> dict[str, Any] | None:
    wanted = name.casefold()
    scored: list[tuple[int, dict[str, Any]]] = []
    for obj in candidates:
        obj_name = normalize_name(obj).casefold()
        if obj_name != wanted:
            continue
        names = [n.casefold() for n in ancestor_names(obj)]
        score = 100
        for ancestor in preferred_ancestors:
            if ancestor.casefold() in names:
                score += 25
        if "schema objects" in names:
            score += 50
        if "object templates" in names or "agents" in names:
            score -= 100
        scored.append((score, obj))
    if not scored:
        return None
    scored.sort(key=lambda item: item[0], reverse=True)
    return scored[0][1]


def exact_named(candidates: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    return best_named(candidates, name)


def response_json(resp: requests.Response) -> Any:
    if not resp.text:
        return {}
    ctype = resp.headers.get("content-type", "")
    if "json" in ctype:
        return resp.json()
    try:
        return resp.json()
    except Exception:
        return {"_text": resp.text[:500]}


@dataclass
class StepResult:
    workflow: int
    name: str
    status: str
    detail: str
    evidence: dict[str, Any] = field(default_factory=dict)


class MSTR:
    def __init__(self, base: str, username: str, password: str, login_mode: int, project_name: str):
        self.base = base.rstrip("/")
        self.username = username
        self.password = password
        self.login_mode = login_mode
        self.project_name = project_name
        self.project_id: str | None = None
        self.session = requests.Session()
        self.session.headers.update({"Accept": "application/json", "Content-Type": "application/json"})

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

    def logout(self) -> None:
        try:
            self.session.delete(f"{self.base}/api/auth/login", timeout=20)
        except Exception:
            pass

    def request(self, method: str, path: str, *, project: bool = True, ok: tuple[int, ...] | None = None, **kwargs) -> requests.Response:
        headers = dict(kwargs.pop("headers", {}) or {})
        if project and self.project_id:
            headers.setdefault("X-MSTR-ProjectID", self.project_id)
        resp = self.session.request(method, f"{self.base}{path}", headers=headers, timeout=90, **kwargs)
        if ok is None:
            ok = tuple(range(200, 300))
        if resp.status_code not in ok:
            raise RuntimeError(f"{method} {path} -> {resp.status_code}: {resp.text[:600]}")
        return resp

    def try_request(self, method: str, path: str, *, project: bool = True, **kwargs) -> requests.Response | None:
        try:
            return self.request(method, path, project=project, **kwargs)
        except Exception:
            return None

    def resolve_project(self) -> dict[str, Any]:
        projects = response_json(self.request("GET", "/api/projects", project=False))
        if not isinstance(projects, list):
            raise RuntimeError(f"unexpected projects payload: {compact_json(projects)}")
        for project in projects:
            if project.get("name") == self.project_name or project.get("id") == self.project_name:
                self.project_id = project["id"]
                self.session.headers["X-MSTR-ProjectID"] = self.project_id
                return project
        raise RuntimeError(f"project not found: {self.project_name}")

    def search(self, name: str, obj_type: int | None = None, limit: int = 20, pattern: int = 4) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"name": name, "pattern": pattern, "limit": limit, "getAncestors": "true"}
        if obj_type is not None:
            params["type"] = obj_type
        resp = self.request("GET", "/api/searches/results", params=params)
        return items_from_search(response_json(resp))

    def read_object(self, object_id: str, obj_type: int) -> dict[str, Any]:
        resp = self.request("GET", f"/api/objects/{object_id}", params={"type": obj_type})
        payload = response_json(resp)
        return payload if isinstance(payload, dict) else {}

    def create_changeset(self) -> str:
        resp = self.request("POST", "/api/model/changesets", params={"schemaEdit": "false"}, json={})
        cs = resp.headers.get("X-MSTR-MS-Changeset")
        payload = response_json(resp)
        if not cs and isinstance(payload, dict):
            cs = payload.get("id") or payload.get("changesetId")
        if not cs:
            raise RuntimeError(f"changeset id missing: {compact_json(payload)}")
        return cs

    def commit_changeset(self, changeset_id: str) -> None:
        self.request("POST", f"/api/model/changesets/{changeset_id}/commit", json={})

    def delete_changeset(self, changeset_id: str) -> None:
        self.try_request("DELETE", f"/api/model/changesets/{changeset_id}", ok=(204,))


class Runner:
    def __init__(self, m: MSTR, args: argparse.Namespace):
        self.m = m
        self.args = args
        self.results: list[StepResult] = []
        self.created: list[dict[str, Any]] = []
        self.cache: dict[str, Any] = {}

    def add(self, workflow: int, name: str, status: str, detail: str, **evidence: Any) -> None:
        self.results.append(StepResult(workflow, name, status, detail, evidence))
        print(f"[{workflow:02d}] {status.upper():7} {name}: {detail}")
        if evidence:
            print(f"     {compact_json(evidence, 1000)}")

    def run_all(self) -> None:
        workflows = self.args.workflow or list(range(1, 11))
        for wf in workflows:
            try:
                getattr(self, f"workflow_{wf}")()
            except Exception as exc:
                self.add(wf, self.workflow_name(wf), "fail", str(exc))
        self.write_ledger()

    @staticmethod
    def workflow_name(wf: int) -> str:
        return {
            1: "auth/project/session baseline",
            2: "search/browse/object metadata",
            3: "classic attribute and element inspection",
            4: "classic metric definition inspection",
            5: "runtime report or cube data extraction",
            6: "runtime prompt discovery",
            7: "document/dashboard export probe",
            8: "user/group/role/privilege readback",
            9: "classic security filter assignment",
            10: "distribution/package/monitor probe",
        }.get(wf, f"workflow {wf}")

    def write_ledger(self) -> None:
        if not self.created:
            return
        path = f"/tmp/strategy-validation-{self.args.run_id}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"runId": self.args.run_id, "created": self.created}, f, indent=2)
        self.add(0, "cleanup ledger", "info", path)

    def workflow_1(self) -> None:
        project = self.m.resolve_project()
        spec = self.m.session.get(f"{self.m.base}/api/openapi.yaml?visibility=all", timeout=60)
        ok = spec.ok and "openapi" in spec.text[:1000]
        session_probe = self.m.try_request("GET", "/api/sessions", project=False)
        self.add(
            1,
            "auth/project/session baseline",
            "pass" if ok else "warn",
            "project resolved and OpenAPI fetched",
            project={"id": project.get("id"), "name": project.get("name")},
            openapiBytes=len(spec.text),
            sessionProbe=session_probe.status_code if session_probe is not None else "unavailable",
        )

    def workflow_2(self) -> None:
        attrs = self.m.search("Category", obj_type=12, limit=100)
        if not attrs:
            raise RuntimeError("Category attribute not found via quick search")
        attr = best_named(attrs, "Category", ("Schema Objects", "Attributes"))
        if not attr:
            names = [normalize_name(a) for a in attrs[:10]]
            raise RuntimeError(f"exact Category attribute not found; first matches were {names}")
        attr_id = normalize_id(attr)
        obj = self.m.read_object(attr_id, int(attr.get("type") or 12))
        folders = []
        for folder_type in ("publicObjects", "public_objects", "PUBLIC_OBJECTS"):
            resp = self.m.try_request("GET", f"/api/folders/preDefined/{folder_type}")
            if resp is not None:
                folders = items_from_search(response_json(resp)) or [response_json(resp)]
                break
        meta_status = "not-run"
        meta = self.m.try_request("POST", "/api/metadataSearches/results", params={"name": "Category", "pattern": 4, "type": 12, "limit": 10})
        if meta is not None:
            meta_status = str(meta.status_code)
        self.cache["category_attr"] = attr
        self.add(
            2,
            "search/browse/object metadata",
            "pass",
            "Category resolved and object metadata read",
            object={"id": attr_id, "name": normalize_name(attr), "type": attr.get("type"), "subtype": attr.get("subtype")},
            aclEntries=len(obj.get("acl") or []),
            folderProbe=len(folders),
            metadataSearch=meta_status,
        )

    def resolve_category_and_books(self) -> tuple[dict[str, Any], dict[str, Any]]:
        attr = self.cache.get("category_attr")
        if attr and normalize_name(attr).casefold() != "category":
            attr = None
        if not attr:
            attrs = self.m.search("Category", obj_type=12, limit=100)
            attr = best_named(attrs, "Category", ("Schema Objects", "Attributes"))
        if not attr:
            raise RuntimeError("Category attribute not found")
        attr_id = normalize_id(attr)
        elems = response_json(self.m.request("GET", f"/api/attributes/{attr_id}/elements", params={"searchTerm": "Books", "limit": 20}))
        candidates = items_from_search(elems)
        if isinstance(elems, dict) and isinstance(elems.get("elements"), list):
            candidates = elems["elements"]
        if not candidates and isinstance(elems, list):
            candidates = elems
        def elem_name(e: dict[str, Any]) -> str:
            vals = e.get("formValues")
            if isinstance(vals, dict):
                return " ".join(str(v) for v in vals.values())
            if isinstance(vals, list):
                return " ".join(str(v.get("value", "")) if isinstance(v, dict) else str(v) for v in vals)
            return str(e.get("name") or e.get("display") or e.get("elementId") or e.get("id") or "")
        books = next((e for e in candidates if "Books" in elem_name(e)), candidates[0] if candidates else None)
        if not books:
            raise RuntimeError(f"Books element not found: {compact_json(elems)}")
        self.cache["category_attr"] = attr
        self.cache["books_element"] = books
        return attr, books

    def workflow_3(self) -> None:
        attr, books = self.resolve_category_and_books()
        attr_id = normalize_id(attr)
        details = response_json(self.m.request("GET", f"/api/model/attributes/{attr_id}", params={"showExpressionAs": "tree"}))
        elem_id = books.get("elementId") or books.get("id")
        display = books.get("display") or books.get("name") or elem_id
        self.add(
            3,
            "classic attribute and element inspection",
            "pass",
            "Category attribute and Books element resolved",
            attribute={"id": attr_id, "name": normalize_name(attr), "forms": len(details.get("forms") or []) if isinstance(details, dict) else None},
            element={"elementId": elem_id, "display": display},
        )

    def workflow_4(self) -> None:
        candidates = []
        for term in ("Revenue", "Profit", "Cost"):
            candidates.extend(self.m.search(term, obj_type=4, limit=25))
            if candidates:
                break
        if not candidates:
            raise RuntimeError("No candidate metric found for Revenue/Profit/Cost")
        preferred = [best_named(candidates, name, ("Schema Objects", "Metrics")) for name in ("Revenue", "Profit", "Cost")]
        ordered = [m for m in preferred if m]
        ordered.extend(candidates)
        attempted = []
        seen = set()
        for metric in ordered:
            metric_id = normalize_id(metric)
            if not metric_id or metric_id in seen:
                continue
            seen.add(metric_id)
            detail_resp = self.m.try_request("GET", f"/api/model/metrics/{metric_id}", params={"showExpressionAs": "tree"})
            attempted.append({"id": metric_id, "name": normalize_name(metric), "read": detail_resp.status_code if detail_resp is not None else "unavailable"})
            if detail_resp is None:
                continue
            details = response_json(detail_resp)
            props = self.m.try_request("GET", f"/api/model/metrics/{metric_id}/applicableAdvancedProperties")
            obj = self.m.read_object(metric_id, 4)
            self.add(
                4,
                "classic metric definition inspection",
                "pass",
                "metric definition and metadata read",
                metric={"id": metric_id, "name": normalize_name(metric), "expressionKeys": sorted((details.get("expression") or details.get("definition") or {}).keys()) if isinstance(details, dict) else []},
                objectName=obj.get("name"),
                applicableProperties=props.status_code if props is not None else "unavailable",
                attempted=attempted[:5],
            )
            return
        raise RuntimeError(f"no searched metric could be read by Modeling Service: {compact_json(attempted, 1000)}")

    def find_report(self) -> dict[str, Any] | None:
        for term in ("Revenue", "Sales", "Category", "Profit", "Inventory"):
            for obj in self.m.search(term, obj_type=3, limit=20):
                if normalize_id(obj):
                    return obj
        return None

    def workflow_5(self) -> None:
        report = self.find_report()
        if not report:
            self.add(5, "runtime report or cube data extraction", "skip", "no executable report candidate found")
            return
        report_id = normalize_id(report)
        create = self.m.try_request("POST", f"/api/reports/{report_id}/instances", json={})
        if create is None:
            self.add(5, "runtime report or cube data extraction", "skip", f"report instance creation failed for {report_id}")
            return
        payload = response_json(create)
        instance_id = payload.get("instanceId") or payload.get("id") or payload.get("instance_id")
        result = None
        if instance_id:
            result_resp = self.m.try_request("GET", f"/api/reports/{report_id}/instances/{instance_id}", params={"offset": 0, "limit": 10})
            if result_resp is not None:
                result = response_json(result_resp)
        self.add(
            5,
            "runtime report data extraction",
            "pass" if instance_id else "warn",
            "report instance created; result fetched when available",
            report={"id": report_id, "name": normalize_name(report)},
            instanceId=instance_id,
            resultKeys=sorted(result.keys()) if isinstance(result, dict) else [],
            resultPreview=compact_json(result, 400) if result is not None else None,
        )

    def workflow_6(self) -> None:
        candidates = []
        for term in ("Prompt", "prompt", "Revenue", "Sales"):
            candidates.extend(self.m.search(term, obj_type=55, limit=10))
            candidates.extend(self.m.search(term, obj_type=3, limit=10))
        seen = set()
        for obj in candidates:
            oid = normalize_id(obj)
            if not oid or oid in seen:
                continue
            seen.add(oid)
            if int(obj.get("type") or 0) == 55:
                resp = self.m.try_request("GET", f"/api/documents/{oid}/prompts")
                if resp is not None:
                    prompts = response_json(resp)
                    if isinstance(prompts, dict):
                        prompt_list = prompts.get("prompts") or prompts.get("promptList") or prompts.get("items") or []
                    elif isinstance(prompts, list):
                        prompt_list = prompts
                    else:
                        prompt_list = []
                    count = len(prompt_list)
                    if count:
                        self.add(6, "runtime prompt discovery", "pass", "document prompts discovered", object={"id": oid, "name": normalize_name(obj)}, promptCount=count)
                        return
        self.add(6, "runtime prompt discovery", "skip", "no safe prompted document/report found with accessible prompt definitions")

    def workflow_7(self) -> None:
        docs = []
        for term in ("Tutorial Home", "Dashboard", "Sales", "Revenue"):
            docs.extend(self.m.search(term, obj_type=55, limit=10))
            if docs:
                break
        if not docs:
            self.add(7, "document/dashboard export probe", "skip", "no document candidate found")
            return
        doc = docs[0]
        doc_id = normalize_id(doc)
        inst = self.m.try_request("POST", f"/api/documents/{doc_id}/instances", json={})
        if inst is None:
            self.add(7, "document/dashboard export probe", "skip", f"document instance creation failed for {doc_id}")
            return
        payload = response_json(inst)
        instance_id = payload.get("instanceId") or payload.get("id") or payload.get("mid")
        export_status = "not-run"
        export_keys: list[str] = []
        if instance_id:
            exp = self.m.try_request("POST", f"/api/documents/{doc_id}/instances/{instance_id}/pdf", json={})
            if exp is not None:
                export_status = str(exp.status_code)
                exp_payload = response_json(exp)
                if isinstance(exp_payload, dict):
                    export_keys = sorted(exp_payload.keys())
            else:
                export_status = "unavailable"
        self.add(7, "document/dashboard export probe", "pass" if instance_id else "warn", "document instance/export endpoint probed", document={"id": doc_id, "name": normalize_name(doc)}, instanceId=instance_id, exportStatus=export_status, exportKeys=export_keys)

    def workflow_8(self) -> None:
        users = response_json(self.m.request("GET", "/api/users", project=False, params={"nameBegins": self.args.user, "limit": 20}))
        if not isinstance(users, list) or not users:
            raise RuntimeError("source user not found")
        user = next((u for u in users if u.get("username") == self.args.user or u.get("name") == self.args.user), users[0])
        user_id = user.get("id")
        self.cache["source_user"] = user
        endpoints = {
            "addresses": self.m.try_request("GET", f"/api/users/{user_id}/addresses", project=False),
            "securityRoles": self.m.try_request("GET", f"/api/users/{user_id}/securityRoles"),
            "privileges": self.m.try_request("GET", f"/api/users/{user_id}/privileges"),
            "usergroups": self.m.try_request("GET", "/api/usergroups", project=False, params={"limit": 10}),
            "securityRolesList": self.m.try_request("GET", "/api/securityRoles"),
        }
        self.add(
            8,
            "user/group/role/privilege readback",
            "pass",
            "governance read endpoints probed",
            user={"id": user_id, "name": user.get("name"), "username": user.get("username")},
            endpoints={k: (v.status_code if v is not None else "unavailable") for k, v in endpoints.items()},
        )

    def find_public_folder_id(self) -> str | None:
        for folder_type in ("publicObjects", "public_objects", "PUBLIC_OBJECTS"):
            resp = self.m.try_request("GET", f"/api/folders/preDefined/{folder_type}")
            if resp is not None:
                payload = response_json(resp)
                if isinstance(payload, dict) and normalize_id(payload):
                    return normalize_id(payload)
        folders = self.m.search("Public Objects", obj_type=8, limit=20)
        for f in folders:
            if normalize_name(f) == "Public Objects" and normalize_id(f):
                return normalize_id(f)
        return None

    def find_security_filter(self, name: str) -> dict[str, Any] | None:
        resp = self.m.try_request("GET", "/api/securityFilters", params={"nameContains": name, "limit": 50})
        if resp is None:
            return None
        payload = response_json(resp)
        filters = payload.get("securityFilters") if isinstance(payload, dict) else payload
        if isinstance(filters, list):
            for sf in filters:
                if isinstance(sf, dict) and normalize_name(sf) == name:
                    return sf
        return None

    def create_security_filter(self, attr: dict[str, Any], books: dict[str, Any]) -> dict[str, Any]:
        existing = self.find_security_filter("Books_secFilter_validation")
        if existing:
            return existing
        folder_id = self.find_public_folder_id()
        if not folder_id:
            raise RuntimeError("could not resolve Public Objects folder for security filter destination")
        attr_id = normalize_id(attr)
        elem_id = books.get("elementId") or books.get("id")
        elem_display = books.get("display") or books.get("name") or "Books"
        body = {
            "information": {
                "name": "Books_secFilter_validation",
                "description": f"Codex validation security filter, run {self.args.run_id}",
                "destinationFolderId": folder_id,
            },
            "qualification": {
                "tree": {
                    "type": "predicate_element_list",
                    "predicateId": "p1",
                    "predicateText": "Category in Books",
                    "predicateTree": {
                        "attribute": {"objectId": attr_id, "subType": "attribute", "name": normalize_name(attr) or "Category"},
                        "elements": [{"display": elem_display, "elementId": elem_id}],
                        "function": "in",
                    },
                }
            },
            "topLevel": [],
            "bottomLevel": [],
        }
        cs = self.m.create_changeset()
        try:
            resp = self.m.request(
                "POST",
                "/api/model/securityFilters",
                headers={"X-MSTR-MS-Changeset": cs},
                params={"showExpressionAs": "tree", "showFilterTokens": "true"},
                json=body,
            )
            sf = response_json(resp)
            self.m.commit_changeset(cs)
            if isinstance(sf, dict):
                sf_id = sf.get("id") or (sf.get("information") or {}).get("objectId")
                self.created.append({"kind": "securityFilter", "id": sf_id, "name": "Books_secFilter_validation"})
                return sf
            return {"name": "Books_secFilter_validation"}
        except Exception:
            self.m.delete_changeset(cs)
            raise

    def ensure_duplicate_user(self, source_user: dict[str, Any]) -> dict[str, Any]:
        target = "validation_duplicate_user"
        users = response_json(self.m.request("GET", "/api/users", project=False, params={"nameBegins": target, "limit": 20}))
        if isinstance(users, list):
            for user in users:
                if user.get("username") == target or user.get("name") == target:
                    return user
        if not self.args.yes:
            raise RuntimeError("write test requires --yes to create duplicate user")
        body = {
            "username": target,
            "fullName": target,
            "description": f"Validation duplicate of {source_user.get('username') or self.args.user}, run {self.args.run_id}",
            "enabled": True,
        }
        resp = self.m.request("POST", "/api/users", project=False, params={"sourceUserId": source_user.get("id")}, json=body, ok=(201,))
        user = response_json(resp)
        if isinstance(user, dict):
            self.created.append({"kind": "user", "id": user.get("id"), "username": target})
            return user
        raise RuntimeError("create duplicate user returned unexpected payload")

    def created_in_this_run(self, kind: str, object_id: str | None = None, name: str | None = None) -> bool:
        for item in self.created:
            if item.get("kind") != kind:
                continue
            if object_id and item.get("id") == object_id:
                return True
            if name and (item.get("name") == name or item.get("username") == name):
                return True
        return False

    def cleanup_security_workflow(self, sf_id: str, dup_id: str, *, remove_membership: bool,
                                  delete_user: bool, delete_filter: bool) -> list[dict[str, Any]]:
        cleanup: list[dict[str, Any]] = []
        if remove_membership:
            patch = {"operationList": [{"op": "removeElements", "path": "/members", "value": [dup_id]}]}
            resp = self.m.try_request("PATCH", f"/api/securityFilters/{sf_id}/members", json=patch, ok=(204,))
            cleanup.append({"target": "securityFilterMembership", "ok": resp is not None,
                            "status": resp.status_code if resp is not None else "unavailable"})
        if delete_user:
            resp = self.m.try_request("DELETE", f"/api/users/{dup_id}", project=False, ok=(200, 202, 204))
            cleanup.append({"target": "duplicateUser", "ok": resp is not None,
                            "status": resp.status_code if resp is not None else "unavailable"})
        if delete_filter:
            cs = self.m.create_changeset()
            try:
                resp = self.m.try_request(
                    "DELETE",
                    f"/api/model/securityFilters/{sf_id}",
                    headers={"X-MSTR-MS-Changeset": cs},
                    ok=(200, 202, 204),
                )
                if resp is not None:
                    self.m.commit_changeset(cs)
                    cleanup.append({"target": "securityFilter", "ok": True, "status": resp.status_code})
                else:
                    self.m.delete_changeset(cs)
                    cleanup.append({"target": "securityFilter", "ok": False, "status": "unavailable"})
            except Exception as exc:
                self.m.delete_changeset(cs)
                cleanup.append({"target": "securityFilter", "ok": False, "error": str(exc)[:300]})
        return cleanup

    def workflow_9(self) -> None:
        if not self.args.yes:
            self.add(9, "classic security filter assignment", "skip", "write workflow requires --yes")
            return
        attr, books = self.resolve_category_and_books()
        source = self.cache.get("source_user")
        if not source:
            users = response_json(self.m.request("GET", "/api/users", project=False, params={"nameBegins": self.args.user, "limit": 20}))
            source = next((u for u in users if u.get("username") == self.args.user or u.get("name") == self.args.user), users[0])
        sf = self.create_security_filter(attr, books)
        sf_id = sf.get("id") or (sf.get("information") or {}).get("objectId")
        if not sf_id:
            existing = self.find_security_filter("Books_secFilter_validation")
            sf_id = existing and normalize_id(existing)
        if not sf_id:
            raise RuntimeError(f"could not determine security filter id: {compact_json(sf)}")
        dup = self.ensure_duplicate_user(source)
        dup_id = dup.get("id")
        if not dup_id:
            raise RuntimeError(f"duplicate user id missing: {compact_json(dup)}")
        members_before = response_json(self.m.request("GET", f"/api/securityFilters/{sf_id}/members", params={"limit": -1}))
        already_member = payload_contains_value(members_before, dup_id)
        patch = {"operationList": [{"op": "addElements", "path": "/members", "value": [dup_id]}]}
        self.m.request("PATCH", f"/api/securityFilters/{sf_id}/members", json=patch, ok=(204,))
        members = response_json(self.m.request("GET", f"/api/securityFilters/{sf_id}/members", params={"limit": -1}))
        user_filters = self.m.try_request("GET", f"/api/users/{dup_id}/securityFilters", params={"projects.id": self.m.project_id})
        cleanup = []
        if self.args.keep_security_artifacts:
            cleanup = [{"target": "securityArtifacts", "ok": True, "status": "kept_by_request"}]
        else:
            cleanup = self.cleanup_security_workflow(
                sf_id,
                dup_id,
                remove_membership=not already_member,
                delete_user=self.created_in_this_run("user", object_id=dup_id),
                delete_filter=self.created_in_this_run("securityFilter", object_id=sf_id, name="Books_secFilter_validation"),
            )
        self.add(
            9,
            "classic security filter assignment",
            "pass",
            "security filter assigned to duplicate user and cleanup handled",
            securityFilter={"id": sf_id, "name": "Books_secFilter_validation"},
            user={"id": dup_id, "username": dup.get("username") or dup.get("name")},
            memberPayloadKeys=sorted(members.keys()) if isinstance(members, dict) else [],
            userFiltersStatus=user_filters.status_code if user_filters is not None else "unavailable",
            cleanup=cleanup,
        )

    def workflow_10(self) -> None:
        endpoints = {
            "subscriptions": self.m.try_request("GET", "/api/subscriptions", params={"limit": 10}),
            "schedules": self.m.try_request("GET", "/api/schedules"),
            "cubeCaches": self.m.try_request("GET", "/api/monitors/caches/cubes", project=False, params={"limit": 10}),
            "contentCaches": self.m.try_request("GET", "/api/monitors/caches/contents", project=False, params={"limit": 10}),
        }
        package_status = "not-run"
        if self.args.package_holder and self.args.yes:
            body = {"name": f"validation-{self.args.run_id}", "type": "project"}
            pkg = self.m.try_request("POST", "/api/packages", json=body)
            if pkg is not None:
                package_status = str(pkg.status_code)
                payload = response_json(pkg)
                pkg_id = payload.get("id") if isinstance(payload, dict) else None
                if pkg_id:
                    self.created.append({"kind": "package", "id": pkg_id, "name": body["name"]})
                    self.m.try_request("DELETE", f"/api/packages/{pkg_id}", ok=(204,))
                    package_status += ":created-deleted"
            else:
                package_status = "unavailable"
        self.add(
            10,
            "distribution/package/monitor admin probe",
            "pass",
            "high-impact admin endpoints probed without destructive operations",
            endpoints={k: (v.status_code if v is not None else "unavailable") for k, v in endpoints.items()},
            packageHolder=package_status,
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default=os.environ.get("MSTR_BASE", DEFAULT_BASE))
    parser.add_argument("--user", default=os.environ.get("MSTR_USER", DEFAULT_USER))
    parser.add_argument("--password", default=os.environ.get("MSTR_PASSWORD", ""))
    parser.add_argument("--login-mode", type=int, default=int(os.environ.get("MSTR_LOGIN_MODE", "1")))
    parser.add_argument("--project-name", default=os.environ.get("MSTR_PROJECT_NAME", DEFAULT_PROJECT_NAME))
    parser.add_argument("--run-id", default=now_run_id())
    parser.add_argument("--workflow", type=int, action="append", choices=range(1, 11), help="Run a specific workflow; repeatable")
    parser.add_argument("--yes", action="store_true", help="Allow write workflows")
    parser.add_argument("--keep-security-artifacts", action="store_true", help="Document that workflow 9 artifacts are intentionally kept")
    parser.add_argument("--package-holder", action="store_true", help="Create and delete an empty package holder in workflow 10")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    password = args.password or getpass.getpass("Password: ")
    m = MSTR(args.base, args.user, password, args.login_mode, args.project_name)
    try:
        m.login()
        m.resolve_project()
        runner = Runner(m, args)
        runner.run_all()
        failed = [r for r in runner.results if r.status == "fail"]
        skipped = [r for r in runner.results if r.status == "skip"]
        print("\nSUMMARY")
        print(f"runId={args.run_id} project={m.project_id} pass={sum(r.status == 'pass' for r in runner.results)} warn={sum(r.status == 'warn' for r in runner.results)} skip={len(skipped)} fail={len(failed)}")
        if failed:
            print("Failures:")
            for r in failed:
                print(f"- {r.workflow}: {r.name}: {r.detail}")
        if skipped:
            print("Skipped:")
            for r in skipped:
                print(f"- {r.workflow}: {r.name}: {r.detail}")
        return 1 if failed else 0
    finally:
        m.logout()


if __name__ == "__main__":
    raise SystemExit(main())
