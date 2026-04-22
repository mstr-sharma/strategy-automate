---
name: Strategy task catalog
description: Map natural-language Strategy automation requests to references, helper commands, and REST/MCP/mstrio surfaces.
type: reference
originSessionId: codex-session
---
Use this as a routing table. Confirm exact paths with `openapi-search` when implementing. The repo's platform goal is complete automation coverage where hooks exist: if a task has no typed helper yet, route through the generic OpenAPI + `api-call` hook, then promote it to a helper when it becomes repeatable, risky, or multi-step. If no API/SDK/MCP/CLI/captured hook exists, record it as a known gap instead of treating it as implemented.

Coverage levels are defined in `reference_strategy_automation_coverage.md`: wrapped helper, generic REST hook, specialized hook, captured fallback, known gap.

## Environment/session
- "Log in", "check auth", "who am I": `auth-probe`, `/api/auth/login`, `/api/auth/identityToken`, `/api/sessions`.
- "List projects": `/api/projects` via `api-call` or mstrio-py.
- "Use a different tenant/project": override `MSTR_BASE`, `MSTR_PROJECT_ID`, `MSTR_USER`, `MSTR_PASSWORD`.
- "Call an endpoint that has no helper yet": `openapi-search`, then `api-call --method ... --path ...`; add `--identity-token` only when the selected surface requires it.

## Object discovery and metadata
- "Find object/report/dashboard/model/user": helper `search-objects`, `/api/searches/results`, `/api/folders/{id}`, `/api/objects/{id}`.
- "Show dependencies/lineage": `/api/objects/{id}/dependencies`, `/dependents`.
- "Move/copy/rename/certify/translate": object endpoints; for Mosaic-contained objects prefer data-model object endpoints.
- "Read/update existing Mosaic object": `get-model-object` then `patch-model-object` with a saved before image.
- "Read/update legacy schema attribute/metric/table": `get-model-object --kind legacy_attribute|legacy_metric|project_table`, patch only after target ID and payload are reviewed.
- "Ambiguous attribute/metric/security/cube request": read `reference_strategy_surface_matrix.md`, resolve target ownership/container, then choose endpoints.

## Datasources and warehouse catalog
- "List DB instances/connections/logins": `/api/datasources`, `/connections`, `/logins`.
- "Test connection": `/api/datasources/{id}/test` or connection test paths in OpenAPI.
- "List schemas/tables/columns": helper `list-namespaces`, `list-tables`, `describe-table`.
- "Create/update datasource or mapping": Datasource Management APIs; use mstrio-py only if wrapper is clearer.

## Mosaic semantic models
- "Build model from DB/schema/tables": the `build-mosaic-model` skill.
- "Set live/in-memory/hybrid": `set-serve-mode` or `PATCH /api/model/dataModels/{id}`.
- "Publish/refresh/delete model": `publish`, `refresh`, `delete-model --yes` after enumerating the target ID.
- "Add tables/attributes/metrics/relationships": Modeling Service under `/api/model/dataModels/{id}/...`; use changesets.
- "Create derived/compound/conditional/time metric": metric subcommands or clone/remap from existing metric JSON.
- "Mosaic data-model security filter / row-level security": `/api/model/dataModels/{id}/securityFilters`; assign members with `/api/dataModels/{id}/securityFilters/{sfId}/members`. Use only when the user names a Mosaic data model/model ID or asks to secure a modern data model.
- "ACL deny/grant on model object": `/api/model/dataModels/{modelId}/objects/{objectId}/acl?subType=...`.

## Legacy/project semantic layer
- "Classic/project security filter for users/groups": create/read definition with `/api/model/securityFilters`, list/assign with `/api/securityFilters` and `/api/securityFilters/{id}/members`; see `reference_strategy_legacy_semantic_admin.md`.
- "Create/update legacy attribute/metric/fact/filter/table": top-level Modeling Service (`/api/model/attributes`, `/api/model/metrics`, `/api/model/facts`, `/api/model/filters`, `/api/model/tables`) with changesets; do not route to `/api/model/dataModels/{id}/...` unless a Mosaic model is explicitly in scope.
- "Update legacy attribute form/expression/table mapping": `GET /api/model/attributes/{id}?showExpressionAs=tree|tokens`, clone/remap the returned payload, then `PATCH /api/model/attributes/{id}` in a changeset.
- "Find Mosaic candidate tables from legacy reports/documents": read `reference_strategy_legacy_to_mosaic_mining.md`; run `strategy_semantic_mine.py --mode top-down --report ...` or `--document ...`.
- "Find reports/objects that depend on a table": read `reference_strategy_legacy_to_mosaic_mining.md`; run `strategy_semantic_mine.py --mode reverse --table ...` or `--seed TABLE_ID;15`.
- "Object move/copy/certify/ACL/VLDB outside Mosaic": use `/api/objects/{id}`, `/api/objects/{id}/copy`, `/api/objects/{id}/certify`, `GET/PUT /api/objects/{id}?type=...` for ACL/object security, and object VLDB endpoints; verify `type` and `subtype` first.

## Published data access
- "What attributes/metrics are in this model": Mosaic MCP `get_semantics`, or `/api/cubes/{id}`.
- "Ask a data question": Mosaic MCP `query` or Trino federation (`catalog=sql`, schema `"{your project name lowercased}"`).
- "Get report/cube/dashboard/document data": read `reference_strategy_runtime_analytics.md`; create instance, answer prompts/apply runtime filters when needed, then fetch result/export.
- "Prompted report/dashboard/document": read prompts first, answer on the runtime instance; do not modify `/api/model/prompts` unless the user asks to change prompt definition.
- "Runtime filter/view filter/metric limit/requested objects": instance request body or dashboard filter endpoint; do not create project filter objects unless explicitly requested.

## Cubes and datasets
- "Create/update/publish Intelligent Cube / OLAP cube": `/api/model/cubes`, then publish with `/api/v2/cubes/{cubeId}` or tenant-supported `/api/cubes/{cubeId}`; see `reference_strategy_cubes_and_datasets.md`.
- "Execute/read cube data": `POST /api/cubes/{cubeId}/instances`, then `GET /api/cubes/{cubeId}/instances/{instanceId}`.
- "Create/update Push Data / Super Cube / MTDI dataset": single-table `POST /api/datasets` or multi-table `POST /api/datasets/models` + `/uploadSessions`; publish/status endpoints under `/api/datasets/{datasetId}/uploadSessions/{uploadSessionId}`.
- "Cube caches/refresh/status": `/api/monitors/caches`, `/api/datasets/cubes/{id}/status`, dataset/cube refresh endpoints; use mstrio cube cache helpers when useful.

## Reports, dashboards, dossiers, documents
- "List/execute/export report or dashboard/document": `/api/reports`, `/api/dashboards`, `/api/dossiers`, `/api/documents`; see `reference_strategy_runtime_analytics.md`.
- "Export PDF": document/dashboard instance export endpoints.
- "Publish/unpublish to Library": published object endpoints in OpenAPI; verify users/groups first.

## Governance/admin
- "Resolve users from names/emails": helper `resolve-users`; final writes should use IDs.
- "Create users from a roster": helper `create-users` dry-runs by default; `--yes` performs `POST /api/users` and optional `/api/users/{id}/addresses`.
- "Duplicate a user": `POST /api/users?sourceUserId=<sourceUserId>` with required body fields `username` and `fullName`; if target username exists, verify and reuse.
- "Patch users or memberships": `/api/users/{id}` with `operationList` (`add`, `replace`, `remove`) after resolving IDs.
- "Users/groups/security roles/privileges": `/api/users`, `/api/usergroups`, `/api/securityRoles`; mstrio-py is often useful.
- "Object security / ACL grant or deny": use `GET/PUT /api/objects/{id}?type=...` for classic objects; use data-model object ACL endpoint for Mosaic-contained objects; never treat ACL as a security filter.
- "Subscriptions/schedules/distribution": `/api/subscriptions`, `/api/schedules`, distribution services modules.
- "Subscriptions/schedules/distribution": read `reference_strategy_admin_platform.md`; `/api/subscriptions`, `/api/schedules`, contacts, addresses, dynamic recipients, transmitters.
- "Caches/jobs/monitors/project load/unload": read `reference_strategy_admin_platform.md`; `/api/monitors`, cube/content cache endpoints, project status endpoints.
- "Project/server settings/VLDB": read `reference_strategy_admin_platform.md`; `/api/projects/{id}/settings`, `/api/iserver/settings`, object `vldb` and property set endpoints, mstrio-py settings helpers.
- "Migration/package import/export": read `reference_strategy_admin_platform.md`; migration/package APIs are high-impact, verify source/target environments, package type, package IDs, validation, and rollback/undo support.
- "Datasource administration": read `reference_strategy_admin_platform.md`; distinguish catalog reads from datasource/connection/login/mapping writes.
- "Auto Agent / Bot / AI chat": read `reference_strategy_ai_agents.md`; prefer Auto Agent question/config paths over deprecated Bot APIs.

## When unsure
Run:
```bash
python3 skill/scripts/build_mosaic.py openapi-search "<domain word>" --context 3
```
Then make a read-only `api-call` to confirm response shape before writing.
