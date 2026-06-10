---
name: Strategy surface matrix
description: The ONE noun→surface routing file — classic semantic objects, Mosaic data-model objects, runtime analytics, cube/dataset families (Intelligent Cube, Super Cube/MTDI Push Data, DDA/MDX, Mosaic), AI/agents, and admin/security.
type: reference
originSessionId: codex-session
---
Use this before choosing endpoints. Strategy has overlapping nouns across product generations; route by ownership and runtime surface. For coverage audits, pair this with `reference_strategy_automation_coverage.md` so each surface is marked as wrapped helper, generic REST hook, specialized hook, captured fallback, or known gap.

## Routing rule

Ask or infer where the object lives:

- **Project metadata / legacy semantic layer:** classic MicroStrategy objects in a project folder: attributes, facts, metrics, filters, prompts, transformations, security filters, reports, cubes, folders. Use top-level Modeling Service and Object Management endpoints.
- **Mosaic data model:** modern model-contained objects: tables, model attributes, model metrics, fact metrics, relationships, model security filters, model object ACL/translations. Use `/api/model/dataModels/{dataModelId}/...`.
- **Runtime analytics / JSON Data API:** execute or fetch data from reports/cubes/dashboards/documents; use instances, prompt answers, runtime filters, exports, and requested objects. This reads or runs content rather than redefining semantic objects.
- **Push Data / MTDI dataset:** external data uploaded to Strategy as a dataset/super cube. Use `/api/datasets...`; dataset attributes/metrics are dataset definitions, not project schema objects.
- **Admin/security/governance:** users, groups, ACLs, security roles, privileges, subscriptions, schedules, monitors, caches, migrations, datasources, settings.
- **AI/agents/MCP:** Auto Agent, deprecated Bot APIs, chat/question APIs, AI service, nuggets/learnings, unstructured-data, or Mosaic MCP query/semantic inspection. Discover in live OpenAPI and prefer MCP for semantic query when connected.

If a request is ambiguous, resolve the object by ID/name first and inspect its `type`, `subtype`, ancestors, and container.

## Attributes

Classic/project attribute:

- Create: `POST /api/model/attributes` in a changeset.
- Read/update: `GET/PATCH /api/model/attributes/{attributeId}` with `showExpressionAs=tree|tokens` when editing expressions.
- Relationships/system hierarchy: `GET /api/model/systemHierarchy/attributes/{attributeId}/relationships`; update via `PUT` in a schema changeset.
- User hierarchies/drill paths: `GET/POST /api/model/hierarchies`, `GET/PATCH /api/model/hierarchies/{hierarchyId}`.
- Elements: `GET /api/attributes/{id}/elements?searchTerm=<value>` when tenant-supported; otherwise use report/cube-scoped element endpoints. Resolve exact schema attributes by ancestor path, because identical names can also appear in Agent/Object Template folders.
- Object metadata/ACL: `GET/PUT /api/objects/{id}?type=12`.
- Object type/subtype: type `12`, common subtype `3072` (`attribute`).

Mosaic data-model attribute:

- Create/list: `GET/POST /api/model/dataModels/{dataModelId}/attributes`.
- Read/update/delete: `GET/PATCH/DELETE /api/model/dataModels/{dataModelId}/attributes/{attributeId}`.
- Relationships: `GET/PUT /api/model/dataModels/{dataModelId}/attributes/{attributeId}/relationships`.
- ACL/translations: `/api/model/dataModels/{dataModelId}/objects/{objectId}/acl|translations?subType=attribute`.

Runtime/dataset attribute:

- Cube/report instance APIs expose selected attributes for execution and result fetching.
- Cube element browsing uses `/api/cubes/{cubeId}/attributes/{attributeId}/elements` or instance-specific variants.
- Push Data dataset attributes are JSON definitions inside `/api/datasets` or `/api/datasets/models`; they are not reusable project schema attributes.

## Metrics

Classic/project fact:

- Read/update: `GET/PATCH /api/model/facts/{factId}` with `showExpressionAs=tree|tokens`.
- Fact definitions expose all expression/table mappings, entry level, and fact extensions/allocation rules. Use these for table discovery and grain review before modernizing into Mosaic.

Classic/project metric:

- Create: `POST /api/model/metrics` in a changeset.
- Read/update: `GET/PUT /api/model/metrics/{metricId}`.
- Applicable advanced properties: `GET /api/model/metrics/{metricId}/applicableAdvancedProperties`.
- Supports expression, dimensionality (`dimty`), conditionality, subtotals, thresholds, formats, VLDB/applicable properties.
- Official docs call out unsupported metric families for this API: training metrics, extreme metrics, reference line metrics, and relationship metrics.

Mosaic data-model metric:

- General model metrics: `GET/POST /api/model/dataModels/{dataModelId}/metrics`; `GET/PUT/DELETE /metrics/{metricId}`.
- Fact metrics: `GET/POST /api/model/dataModels/{dataModelId}/factMetrics`; `GET/PATCH/DELETE /factMetrics/{factMetricId}`.
- Embedded objects in model metrics: `/metrics/{metricId}/embeddedObjects`.
- Use these only when a Mosaic data model is explicitly in scope.

Runtime/dataset metric:

- Cube/report execution can request metrics dynamically; this does not create or update the project metric definition.
- Push Data dataset metrics are dataset-level definitions over uploaded columns; they do not behave like project metrics.

## Prompts and filters

Prompt/filter wording spans metadata and runtime surfaces:

- **Prompt object definition:** `/api/model/prompts` (classic/project metadata) or model-contained prompt endpoints when available.
- **Prompt answers:** report/dashboard/document runtime instance endpoints; answers do not modify the prompt object.
- **Filter object definition:** `/api/model/filters` or data-model filter endpoints.
- **Runtime view filters/metric limits/template limits:** instance request body or dashboard filter manipulation; not persisted.
- **Security filters:** row-level data security assigned to users/groups; not the same as runtime filters.

See `reference_strategy_runtime_analytics.md` for prompt/filter execution details.

## Security and access

Keep four concepts separate:

- **Object ACL / object security:** who can browse/read/write/delete/control an object.
- **Security filter / row-level data security:** what data rows/elements a user/group can see.
- **Security roles / privileges:** what capabilities a user/group has in a project/server.
- **Subscriptions/distribution access:** who receives or owns schedules/deliveries.

Classic object ACL:

- Read object and ACL: `GET /api/objects/{id}?type=<EnumDSSXMLObjectTypes>`.
- Update object ACL/name/folder/owner: `PUT /api/objects/{id}?type=<type>` with `acl` entries and optional `propagateACLToChildren`. Each `acl` entry carries `op` (`ADD`, `REPLACE`, etc.), `trustee`, `rights`, `denied`, `inheritable`, and `type`.
- ACL rights are bitmask values: Browse `1`, Use/Execute `2`, Read `4`, Write `8`, Delete `16`, Control `32`, Use `64`, Execute `128`, Full `255`.
- For folders, `inheritable` and propagation behavior control child object inheritance.

Mosaic data-model object ACL:

- Read/update via `/api/model/dataModels/{dataModelId}/objects/{objectId}/acl?subType=<subType>`.
- Update requires `X-MSTR-MS-Changeset`; commit the changeset afterward.
- In the model ACL body, granted/denied both `0` removes a user from the ACL.

Classic project security filter:

- Definition: `/api/model/securityFilters`.
- Assignment: `/api/securityFilters/{id}/members`.
- See `reference_strategy_legacy_semantic_admin.md`.

Mosaic data-model security filter:

- Definition: `/api/model/dataModels/{dataModelId}/securityFilters`.
- Assignment: `/api/dataModels/{dataModelId}/securityFilters/{securityFilterId}/members`.

Security roles and privileges:

- Security roles: `/api/securityRoles`, `/api/users/{id}/securityRoles`, `/api/usergroups/{id}/securityRoles`.
- Privileges: `/api/iserver/privileges`, `/api/sessions/privileges`, `/api/users/{id}/privileges`, `/api/usergroups/{id}/privileges`.
- Roles/privileges grant capabilities; they do not define row-level data restrictions or object ACL by themselves.

## Cubes and datasets

Use this section whenever the user says cube, OLAP, Intelligent Cube, Super Cube, MTDI, Push Data, dataset, refresh, publish, cache, or data extraction. Route cube requests by cube family.

Intelligent Cube / OLAP cube (project cube object; official docs describe "Manage cube objects" as Modeling Service workflows):

- Create definition: `POST /api/model/cubes`
- Read definition: `GET /api/model/cubes/{cubeId}`
- Update definition: `PUT /api/model/cubes/{cubeId}`
- Publish/materialize: `POST /api/v2/cubes/{cubeId}` in current docs; some tenants also support `POST /api/cubes/{cubeId}`.
- Execute/read data: `POST /api/cubes/{cubeId}/instances`, then `GET /api/cubes/{cubeId}/instances/{instanceId}`.
- Browse cube elements: `/api/cubes/{cubeId}/attributes/{attributeId}/elements` and instance-specific variants.
- Monitor cache: `/api/monitors/caches/...` and cube cache monitor endpoints.
- Typical create body: `information.subType: "report_cube"`, `template.rows`/`template.columns`/`template.pageBy`, optional `filter`, `options.dataRefresh`, `dataPartition`, language options, optional `advancedProperties`. FFSQL cube variants can include `sourceType: "custom_sql_free_form"` and table definitions.

Super Cube / MTDI / Push Data dataset (external-data cube created from uploaded data; official docs call this the Push Data API):

- Single-table workflow: create and upload in one call with `POST /api/datasets`; update table data with `PATCH /api/datasets/{datasetId}/tables/{tableId}`. Good for small/simple single-table datasets.
- Multi-table/incremental workflow: create dataset model with `POST /api/datasets/models`, create upload session with `POST /api/datasets/{datasetId}/uploadSessions`, upload chunks with `PUT /api/datasets/{datasetId}/uploadSessions/{uploadSessionId}`, publish with `POST .../uploadSessions/{uploadSessionId}/publish`, poll with `GET .../uploadSessions/{uploadSessionId}/publishStatus`.
- Dataset publish/refresh/status endpoints include `/api/datasets/{datasetId}`, `/api/datasets/cubes/{id}/status`, `/api/datasets/{datasetId}/instances/{instanceId}/refresh`.
- Dataset definitions include tables, column headers, dataset attributes, and dataset metrics. These are not the same as project schema attributes/metrics unless separately modeled.

DDA/MDX cube (runtime retrieval/execution; treat as execution/data-access surfaces first):

- Confirm the cube type/subtype and datasource/MDX role before writing.
- Use `GET /api/cubes/{cubeId}` or object metadata to inspect.
- Some endpoints include `X-MSTR-MdxDbRoleId`; do not assume Intelligent Cube create/update bodies apply.

Mosaic data model (not the same thing as a classic cube — created and edited with `/api/model/dataModels`, not `/api/model/cubes`):

- Semantic editing: `/api/model/dataModels/{dataModelId}/tables|attributes|metrics|factMetrics|relationships|securityFilters`.
- Data serve mode: `connect_live`, `in_memory`, and tenant-supported `hybrid`.
- Publish/materialization: see `reference_mosaic_publish_path.md` — the one publish file (UI-verified `/api/cubes/{id}?cubeAction=publish` trigger vs the 3-step `/api/dataModels` flow, single-trigger rule, dataType preconditions).
- Query/semantic inspection: prefer Mosaic MCP (`get_semantics`, `query`) when connected; otherwise use REST cube/model APIs as available.

## Runtime analytics

Reports, cubes, dashboards/dossiers, and documents share instance-oriented flows:

- Report/cube instances: `/api/reports/{id}/instances`, `/api/cubes/{id}/instances`.
- Dashboard/dossier instances and filters: `/api/dossiers/{id}/instances`, `/api/dossiers/{id}/instances/{instanceId}/filters`.
- Document instances and exports: `/api/documents/{id}/instances`, `/pdf`, `/excel`, `/csv`, visualization export endpoints.
- Prompt answer endpoints live under document/dossier/report instance families.

See `reference_strategy_runtime_analytics.md`.

## Admin/platform workflows

Datasource admin, subscriptions, schedules, contacts, migration packages, monitors, caches, project load/unload, settings, search/browse, lineage, and object ownership have their own endpoint families. See `reference_strategy_admin_platform.md`.

## AI agents and bots

Auto Agent and legacy Bot naming is in transition:

- Prefer `/api/questions...` and `/api/v2/bots...` for Auto Agent-style workflows.
- Treat `/api/bots...` and `/api/chats...` as legacy/deprecated unless required.
- See `reference_strategy_ai_agents.md`.

## mstrio-py package map

Use mstrio-py when wrappers make a workflow safer, but keep the REST path in notes:

- Classic Modeling: `mstrio.modeling.schema.attribute`, `mstrio.modeling.metric`, `mstrio.modeling.security_filter`.
- Users/groups/security: `mstrio.users_and_groups`, `mstrio.access_and_security.security_role`, `mstrio.access_and_security.privilege`.
- ACL helpers: `mstrio.utils.acl`; examples in `code_snippets/acl_mgmt.py`.
- Cubes/datasets: `mstrio.project_objects.datasets.olap_cube`, `super_cube`, `cube_cache`, plus `mstrio.api.cubes` and `mstrio.api.datasets`. Repo examples: `code_snippets/intelligent_cube.py`, `code_snippets/create_super_cube.py`, `code_snippets/cube_cache.py`, `workflows/import_cube_data_into_dataframe.py`. Use wrappers for reads, cache operations, and Push Data ergonomics; for generated automation memory, still record the REST endpoint family used and the object IDs created or modified.
