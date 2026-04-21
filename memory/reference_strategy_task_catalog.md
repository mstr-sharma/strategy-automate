---
name: Strategy task catalog
description: Map natural-language Strategy automation requests to references, helper commands, and REST/MCP/mstrio surfaces.
type: reference
originSessionId: local-codex-2026-04-21
---
Use this as a routing table. Confirm exact paths with `openapi-search` when implementing.

## Environment/session
- "Log in", "check auth", "who am I": `auth-probe`, `/api/auth/login`, `/api/auth/identityToken`, `/api/sessions`.
- "List projects": `/api/projects` via `api-call` or mstrio-py.
- "Use a different tenant/project": override `MSTR_BASE`, `MSTR_PROJECT_ID`, `MSTR_USER`, `MSTR_PASSWORD`.

## Object discovery and metadata
- "Find object/report/dashboard/model/user": helper `search-objects`, `/api/searches/results`, `/api/folders/{id}`, `/api/objects/{id}`.
- "Show dependencies/lineage": `/api/objects/{id}/dependencies`, `/dependents`.
- "Move/copy/rename/certify/translate": object endpoints; for Mosaic-contained objects prefer data-model object endpoints.
- "Read/update existing Mosaic object": `get-model-object` then `patch-model-object` with a saved before image.
- "Read/update legacy schema attribute/metric/table": `get-model-object --kind legacy_attribute|legacy_metric|project_table`, patch only after target ID and payload are reviewed.

## Datasources and warehouse catalog
- "List DB instances/connections/logins": `/api/datasources`, `/connections`, `/logins`.
- "Test connection": `/api/datasources/{id}/test` or connection test paths in OpenAPI.
- "List schemas/tables/columns": helper `list-namespaces`, `list-tables`, `describe-table`.
- "Create/update datasource or mapping": Datasource Management APIs; use mstrio-py only if wrapper is clearer.

## Mosaic semantic models
- "Build model from DB/schema/tables": `$build-mosaic-model`.
- "Set live/in-memory/hybrid": `set-serve-mode` or `PATCH /api/model/dataModels/{id}`.
- "Publish/refresh/delete model": `publish`, `refresh`, `delete-model`.
- "Add tables/attributes/metrics/relationships": Modeling Service under `/api/model/dataModels/{id}/...`; use changesets.
- "Create derived/compound/conditional/time metric": metric subcommands or clone/remap from existing metric JSON.
- "Security filter / row-level security": `/api/model/dataModels/{id}/securityFilters`; assign members with `/api/dataModels/{id}/securityFilters/{sfId}/members`.
- "ACL deny/grant on model object": `/api/model/dataModels/{modelId}/objects/{objectId}/acl?subType=...`.

## Published data access
- "What attributes/metrics are in this model": Mosaic MCP `get_semantics`, or `/api/cubes/{id}`.
- "Ask a data question": Mosaic MCP `query` or Trino federation (`catalog=sql`, schema `"shared studio"`).
- "Get report/cube data": Reports/Cubes JSON Data API; create instance then fetch result.

## Reports, dashboards, dossiers, documents
- "List/execute/export report or dashboard": `/api/reports`, `/api/dashboards`, `/api/dossiers`, `/api/documents`.
- "Export PDF": document/dashboard instance export endpoints.
- "Publish/unpublish to Library": published object endpoints in OpenAPI; verify users/groups first.

## Governance/admin
- "Resolve users from names/emails": helper `resolve-users`; final writes should use IDs.
- "Create users from a roster": helper `create-users` dry-runs by default; `--yes` performs `POST /api/users` and optional `/api/users/{id}/addresses`.
- "Patch users or memberships": `/api/users/{id}` with `operationList` (`add`, `replace`, `remove`) after resolving IDs.
- "Users/groups/security roles/privileges": `/api/users`, `/api/usergroups`, `/api/securityRoles`; mstrio-py is often useful.
- "Subscriptions/schedules/distribution": `/api/subscriptions`, `/api/schedules`, distribution services modules.
- "Caches/jobs/monitors": `/api/monitors`, cube/report cache endpoints, job monitor.
- "Project/server settings/VLDB": `/api/projects/{id}/settings`, object `vldbProperties`, mstrio-py settings helpers.
- "Migration/package import/export": migration/package APIs; high-impact, verify source/target environments and package IDs.

## When unsure
Run:
```bash
python3 skill/scripts/build_mosaic.py openapi-search "<domain word>" --context 3
```
Then make a read-only `api-call` to confirm response shape before writing.
