---
name: Strategy OpenAPI reference
description: How agents should discover and use the machine-readable Strategy REST OpenAPI spec instead of scraping the Swagger UI.
type: reference
originSessionId: codex-session
---
The Swagger / API Explorer page at `{Library}/api-docs/` is a JavaScript app. Do not scrape it as HTML.

Use the raw OpenAPI file:
- `https://demo.microstrategy.com/MicroStrategyLibrary/api/openapi.yaml`
- `{MSTR_BASE}/api/openapi.yaml`
- Local cached copy, when present: `$REPO/openapi.yaml`

Use `?visibility=all` when the Swagger UI shows additional operations or when a public/default spec looks incomplete:
- `{Library}/api/openapi.yaml?visibility=all`
- `{Library}/api/openapi.yaml?visibility=internal`

Verified 2026-04-21:
- content type: `application/yaml`
- `openapi: 3.0.1`
- `info.title: Strategy REST`
- `info.version: "2026"`
- studio tenant returned 652 paths and tags including Authentication, Data Models, Datasource Management, Cubes, Changesets, Security Filters.
- `/api-docs/swagger-config` returned 404.

Use the helper instead of manual curl:
```bash
cd "$REPO"
python3 skill/scripts/build_mosaic.py openapi-summary --limit 80
python3 skill/scripts/build_mosaic.py openapi-search "dataModels" --context 2
python3 skill/scripts/build_mosaic.py openapi-summary --out /tmp/strategy-openapi.yaml
```

If a local `openapi.yaml` exists in the Mosaic Build root, treat it as a reference/cache, not as the source of truth. Refresh it from the tenant when endpoint behavior matters.

Before searching by endpoint name, read `reference_strategy_surface_matrix.md` when the noun is overloaded (`attribute`, `metric`, `security filter`, `ACL`, `cube`, `dataset`, `model`, `agent`). The same noun can belong to classic project metadata, a Mosaic data model, Push Data, runtime JSON Data APIs, or admin/security.

For one-off REST operations that are not wrapped yet:
```bash
python3 skill/scripts/build_mosaic.py api-call --method GET --path /api/projects
python3 skill/scripts/build_mosaic.py api-call --method PATCH --path /api/model/dataModels/<id> --json-file /tmp/body.json
```

For read-first automation flows:
```bash
python3 skill/scripts/build_mosaic.py search-objects --name "Object Name"
python3 skill/scripts/build_mosaic.py resolve-users --user person@example.com
python3 skill/scripts/build_mosaic.py get-model-object --kind legacy_attribute --object-id <id> --show-expression-as tokens
python3 skill/scripts/build_mosaic.py patch-model-object --kind legacy_attribute --object-id <id> --json-file /tmp/patch.json --before-out /tmp/before.json --yes
```

Classic/project auth gotcha verified on `a verified Strategy Cloud tenant`: do not automatically add `X-MSTR-IdentityToken` for top-level classic Modeling Service reads/writes. `X-MSTR-AuthToken` plus `X-MSTR-ProjectID` worked; adding identity token caused `/api/model/metrics/{id}` to return a false "Wrong projectId" error. Mosaic data-model workflows may still require identity token; follow Mosaic-specific references when the surface is `/api/model/dataModels/...`.

Important OpenAPI paths for Mosaic automation:
- `POST /api/model/changesets`, `POST /api/model/changesets/{changesetId}/commit`, `DELETE /api/model/changesets/{changesetId}`
- `POST /api/model/dataModels`, `GET/PATCH /api/model/dataModels/{dataModelId}`
- `GET/POST /api/model/dataModels/{dataModelId}/tables`
- `GET/POST /api/model/dataModels/{dataModelId}/attributes`, `PUT /api/model/dataModels/{dataModelId}/attributes/{attributeId}/relationships`
- `GET/POST /api/model/dataModels/{dataModelId}/metrics` for advanced metrics; tenant also accepts `/factMetrics` for fact metrics.
- `GET/POST /api/model/dataModels/{dataModelId}/factMetrics`
- `GET/POST /api/model/dataModels/{dataModelId}/securityFilters`
- `PATCH /api/dataModels/{dataModelId}/securityFilters/{securityFilterId}/members` for assigning members; body is JSON Patch style: `{operationList:[{op:"addElements",path:"/members",value:[ids...]}]}`.
- `PATCH /api/model/dataModels/{dataModelId}/objects/{objectId}/acl?subType=<objectSubType>` for ACL on model-contained objects.
- `PATCH /api/model/dataModels/{dataModelId}/objects/{objectId}/translations?subType=<objectSubType>` for name/description/form translations.
- `GET/PATCH /api/model/attributes/{attributeId}` for classic/legacy schema attributes outside a Mosaic data model; use changesets and request `showExpressionAs=tokens` when editing expressions.
- `GET/PATCH /api/model/metrics/{metricId}`, `/api/model/facts/{factId}`, `/api/model/tables/{tableId}` for classic schema objects.
- `GET/POST /api/users`, `GET/PATCH/DELETE /api/users/{id}`, `POST /api/users/{id}/addresses` for user management; dry-run and resolve exact duplicates before creating users.
- `POST /api/cubes/{cubeId}` publishes an in-memory cube/model on {MSTR_BASE host}; public spec also lists data-model publish endpoints, but use the tenant-verified cube POST first.

Important OpenAPI paths for classic/project semantic-layer and admin automation:
- `POST /api/model/attributes`, `GET/PATCH /api/model/attributes/{attributeId}` for classic/project attributes.
- `GET /api/model/systemHierarchy` and `GET/PUT /api/model/systemHierarchy/attributes/{attributeId}/relationships` for classic project attribute relationship graph.
- `GET/POST /api/model/hierarchies`, `GET/PATCH /api/model/hierarchies/{hierarchyId}` for classic user hierarchies (`dimension_user`, `dimension_user_hierarchy`).
- `POST /api/model/metrics`, `GET/PUT /api/model/metrics/{metricId}` for classic/project metrics.
- `POST /api/model/securityFilters` creates a **classic project security filter** in a changeset. This is top-level Modeling Service, not `/api/model/dataModels/{id}/securityFilters`.
- `GET /api/model/securityFilters/{securityFilterId}` reads a classic security filter definition; use `showExpressionAs=tree|tokens` when modifying or validating qualification shape.
- `GET/POST /api/model/prompts`, `GET/PATCH /api/model/prompts/{promptId}` for editable classic prompt objects. System prompts return an explicit non-editable error.
- `GET /api/securityFilters` lists project security filters.
- `PATCH /api/securityFilters/{id}/members` assigns/revokes a classic project security filter for users/groups with `{operationList:[{op:"addElements",path:"/members",value:[ids...]}]}`.
- `GET /api/securityFilters/{id}/members` verifies assignments.
- `GET /api/users/{id}/securityFilters` verifies the filters visible on a user by project.
- `POST /api/users?sourceUserId=<sourceUserId>` duplicates a user; body still requires `username` and `fullName`.
- `GET /api/attributes/{id}/elements?searchTerm=<value>` resolves classic schema attribute element IDs for element-list qualifications when tenant-supported. Public OpenAPI may only show report/cube/data-model-scoped element paths; fall back to `/api/reports/{reportId}/attributes/{attributeId}/elements` or instance-scoped report/cube paths if generic lookup is unavailable.
- `GET/PUT /api/objects/{id}?type=<type>` reads/updates classic object metadata and ACL/object security.
- `GET/POST/PATCH /api/securityRoles`, `/api/users/{id}/securityRoles`, `/api/users/{id}/privileges`, `/api/usergroups/{id}/privileges` handle role/capability governance, not row-level security.

Important OpenAPI paths for cube and dataset families:
- Intelligent/OLAP cube definition: `POST /api/model/cubes`, `GET/PUT /api/model/cubes/{cubeId}`.
- Intelligent/OLAP cube publish: `POST /api/v2/cubes/{cubeId}` in official docs; some tenants also expose `POST /api/cubes/{cubeId}`.
- Cube execution/data: `POST /api/cubes/{cubeId}/instances`, `GET /api/cubes/{cubeId}/instances/{instanceId}`, cube element endpoints under `/api/cubes/{cubeId}/attributes/{attributeId}/elements`.
- Push Data single-table dataset / Super Cube: `POST /api/datasets`, `PATCH /api/datasets/{datasetId}/tables/{tableId}`.
- Push Data multi-table / MTDI dataset: `POST /api/datasets/models`, `POST /api/datasets/{datasetId}/uploadSessions`, `PUT /api/datasets/{datasetId}/uploadSessions/{uploadSessionId}`, `POST .../publish`, `GET .../publishStatus`.
- Dataset status/refresh/security views: `/api/datasets/cubes/{id}/status`, `/api/datasets/{datasetId}/instances/{instanceId}/refresh`, `/api/datasets/{id}/securityFilterViews`.

Important OpenAPI paths for runtime analytics:
- Reports/cubes: `/api/reports/{reportId}/instances`, `/api/cubes/{cubeId}/instances`, `/api/cubes/{cubeId}/instances/{instanceId}`.
- Dossiers/dashboards: `/api/dossiers/{dossierId}/instances`, `/api/dossiers/{dossierId}/instances/{instanceId}/filters`, `/api/dashboards...` tenant variants.
- Documents: `/api/documents/{id}/instances`, `/api/documents/{id}/definition`, instance visualization/query/export endpoints.
- Runtime prompts: document/dossier/report prompt endpoints under `/prompts`, `/prompts/answers`, `/promptsAnswers`, `/answerPrompts`, `/rePrompt`.

Important OpenAPI paths for platform administration:
- Datasources: `/api/datasources`, `/api/datasources/connections`, `/api/datasources/logins`, `/api/datasources/mappings`, `/api/datasources/{id}/catalog/...`.
- Distribution: `/api/subscriptions`, `/api/schedules`, `/api/contacts`, `/api/contactGroups`, `/api/dynamicRecipientLists`, `/api/transmitters`.
- Migrations/packages: `/api/packages`, `/api/packages/{packageId}/binary`, `/api/packages/imports`, `/api/migrations`, `/api/migrationGroups`.
- Monitors/cache/project admin: `/api/monitors/caches/...`, `/api/monitors/projects/status`, `/api/monitors/iServer/nodes`, `/api/iserver/...`.
- Search/browse/object admin: `/api/searches/results`, `/api/metadataSearches/results`, `/api/folders`, `/api/objects`.
- Settings/properties: `/api/iserver/settings`, `/api/projects/{id}/settings`, `/api/objects/{id}/vldb/propertySets`, object property set endpoints.

Important OpenAPI paths for AI/agents:
- Auto Agent questions: `/api/questions`, `/api/questions/withImage`, `/api/questions/suggestions`, `/api/questions/{questionId}`, `/api/questions/{questionId}/stream`, `/api/questions/{questionId}/fulldata`.
- Agent management currently appears under `/api/v2/bots...`: create/read/modify/copy agents, chats, columns, config, descriptions, training jobs/sets, NER indexing.
- Legacy/deprecated Bot APIs: `/api/bots...` and `/api/chats...`.
- Nuggets/learnings/AI-adjacent: `/api/nuggets`, `/api/learnings`, dashboard auto narrative and dataset AI indexing endpoints.

When docs and tenant behavior disagree, prefer this order:
1. Tenant-verified gotcha in `feedback_mosaic_gotchas.md`
2. Live `openapi-summary` / `/api/openapi.yaml`
3. Official REST docs at `https://microstrategy.github.io/rest-api-docs/`
4. Clone-and-remap from a working object returned by `GET`
