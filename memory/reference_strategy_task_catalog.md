---
name: Strategy task catalog
description: Map natural-language Strategy automation requests to references, helper commands, and REST/MCP/mstrio surfaces.
type: reference
originSessionId: codex-session
---
Use this as a routing table. Confirm exact operations with `strategy_api.py ops --search` / `describe` when implementing. The repo's platform goal is complete automation coverage where hooks exist: if a task has no typed helper yet, route through the owning domain skill or `strategy_api.py call`, then promote it to a helper when it becomes repeatable, risky, or multi-step. If no API/SDK/MCP/CLI/captured hook exists, record it as a known gap instead of treating it as implemented.

Coverage levels are defined in `reference_strategy_automation_coverage.md`: wrapped helper, skill workflow, generic REST hook, specialized hook, captured fallback, known gap.

## Environment/session
- "Log in", "check auth", "who am I": `auth-probe`, `/api/auth/login`, `/api/auth/identityToken`, `/api/sessions`.
- "List projects": `/api/projects` via `strategy_api.py call getProjects_1` or mstrio-py.
- "Use a different tenant/project": override `MSTR_BASE`, `MSTR_PROJECT_ID`, `MSTR_USER`, `MSTR_PASSWORD`.
- "Call an endpoint that has no helper yet": `strategy_api.py ops --search`, `describe`, then `call` (dry run until `--yes`); add an identity token (`build_mosaic.py api-call --with-identity-token`) only when the selected surface requires it.

## Object discovery and metadata
- "Find object/report/dashboard/model/user": helper `search-objects`, `/api/searches/results`, `/api/folders/{id}`, `/api/objects/{id}`.
- "Show dependencies/lineage" (corrected 2026-10-05 — there is no `/api/objects/{id}/dependencies` or `/dependents`): `POST /api/metadataSearches/results?usesObject=<id>;<type>` (what uses the object; `usedByObject=<id>;<type>` for what it uses; `usesRecursive` / `usedByRecursive` for indirect) → `{id, totalItems}`, then page `GET /api/metadataSearches/results?searchId=<id>&offset=&limit=`. Quick variant: `GET /api/searches/results?usesObjectId=<id>`. Counts only: `POST /api/searches/dependents/count` body `{usesOneOf:[ids]}`.
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
- "Build a Mosaic model from these classic attributes/facts/metrics", "port these schema object IDs": helper `build-from-schema-objects` (`build_mosaic.py`); reads classic definitions, maps their physical tables, batch-creates attributes + factMetrics in CS1, wires relationships in CS2, and creates derived metrics bottom-up in CS3. ApplySimple/custom-SQL/raw-SQL tokens and conditional-metric filter refs are flagged in the review file. See `reference_mosaic_schema_object_import.md`.
- "Set live/in-memory/off-memory": `set-serve-mode` or `PATCH /api/model/dataModels/{id}`.
- "Publish/refresh/delete model": `publish`, `refresh`, `delete-model --yes` after enumerating the target ID.
- "Add tables/attributes/metrics/relationships": Modeling Service under `/api/model/dataModels/{id}/...`; use changesets. **Relationship PUT is destructive** — use `put_relationships_merged()` (default in `wire-relationships`) or pass `--replace` explicitly. See the Relationships section of `reference_mosaic_rest_gotchas.md`.
- "Validate post-build topology / find isolated attributes / check wiring is complete": `build_mosaic.py validate-topology --model-id <id> --strict`. Surfaces isolated attrs on fact tables, fact tables with zero relationships, and numeric-named attrs that should have been metrics. Make this the LAST step of every wiring/build script. See `reference_mosaic_safety_helpers.md`.
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
- "Create/update/publish Intelligent Cube / OLAP cube": `/api/model/cubes`, then publish with `POST /api/v2/cubes/{cubeId}` (`publishCube_2`; `POST /api/cubes/{cubeId}` is internal and deprecated); see `reference_strategy_surface_matrix.md` ("Cubes and datasets").
- "Execute/read cube data": `POST /api/cubes/{cubeId}/instances`, then `GET /api/cubes/{cubeId}/instances/{instanceId}`.
- "Create/update Push Data / Super Cube / MTDI dataset": single-table `POST /api/datasets` or multi-table `POST /api/datasets/models` + `/uploadSessions`; publish/status endpoints under `/api/datasets/{datasetId}/uploadSessions/{uploadSessionId}`.
- "Cube caches/refresh/status": `GET /api/monitors/caches/cubes?clusterNode=<node>` (+ `GET/PATCH/DELETE …/cubes/{id}`) and `GET /api/monitors/caches/contents?clusterNode=<node>` — there is no bare `/api/monitors/caches` (corrected 2026-10-05; `reference_strategy_monitoring_jobs_alerts.md`); cube state via `HEAD /api/cubes/{id}` (`X-MSTR-CubeStatus`); `/api/datasets/cubes/{id}/status` is internal; use mstrio cube cache helpers when useful.

## Reports, dashboards, dossiers, documents
- "List/execute/export report or dashboard/document": `/api/reports`, `/api/dashboards`, `/api/dossiers`, `/api/documents`; see `reference_strategy_runtime_analytics.md`.
- "Export PDF": document/dashboard instance export endpoints.
- "Publish/unpublish to Library": read `reference_strategy_library_publications.md`; `POST /api/library` (additive, groups stay groups), per-recipient `DELETE /api/library/{id}/recipients/{recipientId}`; never bare `DELETE /api/library/{id}` (unpublishes for everyone); verify users/groups first.
- "Which dashboards/documents are published to which users/groups" / "copy Library publications to a duplicated project": per-object `GET /api/library/{id}` with `X-MSTR-ProjectID`; helper `strategy_library_publications.py export` then `replicate` (dry run unless `--apply`).

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
- "Project/server settings/VLDB": read `reference_strategy_admin_platform.md`; public `/api/v2/projects/{id}/settings` and `/api/v2/iserver/settings` (GET/PUT/PATCH; the v1 `/api/projects/{id}/settings` and `/api/iserver/settings` are internal — corrected 2026-10-05), object `vldb` and property set endpoints, mstrio-py settings helpers.
- "Migration/package import/export": read `reference_strategy_admin_platform.md`; migration/package APIs are high-impact, verify source/target environments, package type, package IDs, validation, and rollback/undo support.
- "Datasource administration": read `reference_strategy_admin_platform.md`; distinguish catalog reads from datasource/connection/login/mapping writes.
- "Auto Agent / Bot / AI chat": read `reference_strategy_ai_agents.md`; prefer the documented `/api/questions` Agent APIs (+ `GET /api/v2/bots/{id}/columns`); the rest of `/api/v2/bots` management is internal, only the `/api/bots/{id}/instances…` POSTs are deprecated (`GET /api/bots/{id}/configuration` and the question reads are public), and mstrio-py has an `Agent` class (corrected 2026-10-05).

## When unsure
Run:
```bash
python3 skills/strategy-platform/scripts/strategy_api.py ops --search "<domain word>"
python3 skills/strategy-platform/scripts/strategy_api.py describe <operationId>
```
Then make a read-only `call` to confirm the response shape before writing.
