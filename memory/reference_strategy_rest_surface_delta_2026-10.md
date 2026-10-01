---
name: Strategy REST surface delta, April → October 2026
description: Dated inventory of REST paths that appeared in the public OpenAPI spec between the April 2026 snapshot (652 paths) and 2026-10-01 (762 public, 1,178 with internal), grouped by family with their summaries, plus the one removed path and the refresh procedure.
type: reference
---

# Strategy REST surface delta (public spec), 2026-04-21 → 2026-10-01

Counts are from `{Library}/api/openapi.yaml` (`info.version: "2026"`) on a Strategy ONE Cloud tenant: **652** public paths in the April snapshot kept in this repo's first commit (`openapi.yaml`, since trimmed), **762** public paths today, **1,178** with `?visibility=all`. New public paths: **111**; removed: **1**. Internal-only additions (not listed here, `visibility: internal`): 416, mostly under `/v2`, `/admin`, `/iserver`, `/mstrServices`, `/objects`, `/config`. Treat internal paths as reachability, never as a contract.

## Highlights worth wiring into automation

- **Query visibility** — `GET /api/telemetry/performance/queryProfile/{trinoQueryId}` and `…/sourceBreakdown/{instanceId}[/{templateId}]`
  turn a Mosaic SQL (Trino) query id into the engine's jobs and per-pass SQL; `GET /api/telemetry/performance` +
  `/elementList` list performance statistics; `GET /api/telemetry/usage-insights/model/{modelId}/executions` drills a model's
  executions. Verified 2026-10-01 — see `reference_strategy_sql_visibility.md`.
- **Mosaic data models as YAML** — `POST /api/model/dataModels/{id}/export` (returns the YAML definition), `POST …/restore`
  (restores a YAML definition inside a changeset — commit afterwards), `POST …/saveAs` (copy a model under a new name). This is
  the first documented export/import path for a Mosaic model; `GET …/externalDataModels/{externalId}/objects` reads what a
  composed model imported from each base model (pairs with `reference_mosaic_model_linking.md`).
- **Explorer MCP servers** — `GET/POST /api/explorer/mcp/servers`, `PUT/DELETE …/{name}`, `…/connect`, `…/disconnect`,
  `…/status`, `…/jsonrpc` (proxy JSON-RPC to a named server), `…/callback` (OAuth): the Library can now hold MCP server
  configurations and proxy calls — the admin surface behind "direct Mosaic access over MCP".
- **Scripts** — `POST /api/scripts/conversion` (Command Manager script → Python, `/bulk` + status), evaluation history and logs,
  log-retention settings.
- **Admin bulk operations** — `POST /api/privileges/bulkUpdate` (grant/revoke/replace with a change-journal comment),
  `PATCH /api/securityRoles/{id}/members`, `GET /api/securityRoles/projects/{projectId}`, `PATCH /api/subscriptions/owner`
  (batch owner change), `POST /api/projects/warehouseExecutionSettings/bulkRead|bulkWrite`,
  `POST /api/projects/deleteUnusedManagedObjects` (+ status), `GET /api/datasources/logins/export`.
- **Reports** — `GET/PUT/DELETE /api/reports/{id}/bulkExport` (+ `/transform`), `GET/PUT /api/reports/{id}/cacheInvalidationSchedule`.
- **AI surfaces** — `POST /api/questions/{questionId}/transformsql` (the full SQL behind an Auto question), `POST /api/nuggets`
  (bulk nugget creation), `POST /api/autoExpert/intake`, `GET/PUT /api/explorer/config`, `/api/explorer/webSearch/config`,
  Explorer chats (`POST /api/explorer/chats/{chatId}/messages`), `GET/PUT/POST/DELETE /api/ontology/vocabularies…`.
- **Flows** — `GET/POST /api/flows`, `PATCH /api/flows/{id}` (user-scoped Flow objects).
- **Cubes** — `POST /api/cubes/dumpcubes` (dump cube instances to external resources).
- **Removed** — `/api/telemetry/dashboards/interactions` (use `/api/telemetry/objects/interactions`).

## New public paths by family

### /api/admin (2)

- `/api/admin/mstrServices/mosaic/settings/commit` — `POST` Commit Mosaic settings
- `/api/admin/mstrServices/mosaic/settings/stage` — `POST` Save draft Mosaic settings

### /api/autoExpert (1)

- `/api/autoExpert/intake` — `POST` Create a case

### /api/configurations (1)

- `/api/configurations/historyMessageExpirationDay` — `GET` Get history message expiration days; `PUT` Update history message expiration days

### /api/cubes (1)

- `/api/cubes/dumpcubes` — `POST` Trigger the process to dump cubes to external resources

### /api/datasources (1)

- `/api/datasources/logins/export` — `GET` Export database login credentials

### /api/documentationDefinitions (1)

- `/api/documentationDefinitions/refreshTenantIds` — `POST` Refresh tenant IDs for documentation definitions

### /api/dossiers (1)

- `/api/dossiers/{dossierId}/instances/{instanceId}/manipulations` — `PUT` Apply manipulations to a dossier instance

### /api/explorer (12)

- `/api/explorer/chats/{chatId}/messages` — `POST` Post a question to the specified agent, or the agents in the specified\
- `/api/explorer/chats/{chatId}/messages/{messageId}` — `GET`
- `/api/explorer/chats/{chatId}/messages/{messageId}/files/{fileId}` — `GET`
- `/api/explorer/config` — `GET` Get shared Explorer configuration.; `PUT` Update shared Explorer configuration.
- `/api/explorer/mcp/servers` — `GET` Get all MCP server configurations.; `POST` Create an MCP server configuration.
- `/api/explorer/mcp/servers/callback` — `GET` OAuth callback for an MCP server.
- `/api/explorer/mcp/servers/status` — `GET` Get MCP server connection status for the current user.
- `/api/explorer/mcp/servers/{name}` — `PUT` Update an MCP server configuration by name.; `DELETE` Delete an MCP server configuration by name.
- `/api/explorer/mcp/servers/{name}/connect` — `POST` Connect to an MCP server.
- `/api/explorer/mcp/servers/{name}/disconnect` — `POST` Disconnect from an MCP server.
- `/api/explorer/mcp/servers/{name}/jsonrpc` — `POST` Proxy MCP JSON-RPC requests to an MCP server by name.
- `/api/explorer/webSearch/config` — `GET` Get Explorer web search configuration.; `PUT` Update Explorer web search configuration.

### /api/flows (2)

- `/api/flows` — `GET` List Flows for the calling user; `POST` Create a new Flow
- `/api/flows/{id}` — `PATCH` Update a Flow

### /api/hierarchies (1)

- `/api/hierarchies/{hierarchyId}/dataExplorer` — `POST` Browse hierarchy data explorer

### /api/mdxDataSources (2)

- `/api/mdxDataSources/{mdxDataSourceId}` — `GET`
- `/api/mdxDataSources/{mdxDataSourceId}/cubes/{cubeId}` — `PATCH`

### /api/model (4)

- `/api/model/dataModels/{dataModelId}/export` — `POST` Export a data model to YAML
- `/api/model/dataModels/{dataModelId}/externalDataModels/{externalDataModelId}/objects` — `GET` Read the objects of an external data model in the current data model.
- `/api/model/dataModels/{dataModelId}/restore` — `POST` Restore a data model from YAML
- `/api/model/dataModels/{dataModelId}/saveAs` — `POST` Save a data model as a new data model

### /api/multitenant (1)

- `/api/multitenant/tenant/{tenantId}/settings` — `GET`; `PATCH`

### /api/nuggets (1)

- `/api/nuggets` — `POST` Create a collection of nuggets

### /api/objects (2)

- `/api/objects/all/translations` — `POST` Fetch object translations
- `/api/objects/translations` — `POST` Fetch translations for specific objects

### /api/ontology (4)

- `/api/ontology/vocabularies` — `GET` Get Ontology Vocabularies
- `/api/ontology/vocabularies/fields/{fieldName}` — `PUT` Replace Field Vocabulary
- `/api/ontology/vocabularies/fields/{fieldName}/values` — `POST` Add Vocabulary Value
- `/api/ontology/vocabularies/fields/{fieldName}/values/{value}` — `DELETE` Remove Vocabulary Value

### /api/preferences (6)

- `/api/preferences/project/{projectId}/schedules` — `GET` Get schedule project preference; `PUT` Set schedule project preference
- `/api/preferences/webpreferences/currentuser` — `GET`; `PATCH`
- `/api/preferences/webpreferences/currentuser/project/{projectId}` — `GET`; `PATCH`
- `/api/preferences/webpreferences/project/{projectId}` — `GET`; `PATCH`
- `/api/preferences/webpreferences/user/{userId}` — `GET`; `PATCH`
- `/api/preferences/webpreferences/user/{userId}/project/{projectId}` — `GET`; `PATCH`

### /api/privileges (1)

- `/api/privileges/bulkUpdate` — `POST` Bulk grant, revoke, or replace privileges

### /api/projects (5)

- `/api/projects/deleteUnusedManagedObjects` — `POST` Delete unused managed objects in a project
- `/api/projects/deleteUnusedManagedObjects/status` — `GET` Get delete unused managed objects status
- `/api/projects/warehouseExecutionSettings/bulkRead` — `POST` Bulk read warehouse execution settings by project list
- `/api/projects/warehouseExecutionSettings/bulkWrite` — `POST` Bulk update warehouse execution settings by project list
- `/api/projects/{projectId}/statusMessage` — `GET` Get the project status message configuration; `PATCH` Update the project status message configuration

### /api/questions (1)

- `/api/questions/{questionId}/transformsql` — `POST` Get transformed full SQL for the question.

### /api/reports (3)

- `/api/reports/{reportId}/bulkExport` — `GET` Get bulk export configuration; `PUT` Create or update bulk export configuration; `DELETE` Remove bulk export configuration
- `/api/reports/{reportId}/bulkExport/transform` — `POST` Transform report to bulk export
- `/api/reports/{reportId}/cacheInvalidationSchedule` — `GET` Get a report's cache invalidation schedule; `PUT` Update a report's cache invalidation schedule

### /api/scripts (7)

- `/api/scripts/conversion` — `POST` Convert Command Manager script to Python
- `/api/scripts/conversion/bulk` — `POST` Submit a bulk Command Manager to Python conversion task
- `/api/scripts/conversion/bulk/{id}` — `GET` Get bulk Command Manager conversion task status
- `/api/scripts/evaluationList/{id}` — `GET` Get execution IDs for a script
- `/api/scripts/evaluationLog/{id}/{evaluationId}` — `GET` Get execution log for a script evaluation
- `/api/scripts/evaluations` — `GET` Get script evaluation history
- `/api/scripts/settings/logRetention` — `GET` Get script execution log retention settings; `PUT` Update script execution log retention settings

### /api/searchObjects (1)

- `/api/searchObjects/{searchObjectId}/translations` — `POST` Fetch translations by search object

### /api/securityRoles (2)

- `/api/securityRoles/projects/{projectId}` — `GET` Get security role memberships for a specific project
- `/api/securityRoles/{id}/members` — `PATCH` Update members of a specific security role

### /api/sessions (1)

- `/api/sessions/privilegesAll` — `GET`

### /api/subscriptions (1)

- `/api/subscriptions/owner` — `PATCH` Batch change subscription owner

### /api/telemetry (28)

- `/api/telemetry/admin/bot-interactions/details` — `GET` Get Bot Interaction Details
- `/api/telemetry/admin/runtime-config` — `GET` List runtime configs
- `/api/telemetry/admin/runtime-config/{key}` — `GET` Get runtime config by key; `PUT` Update runtime config
- `/api/telemetry/lakehouse-migration/status` — `GET` Get lakehouse migration completion status
- `/api/telemetry/objects/client-executions` — `GET` Get Client Executions
- `/api/telemetry/objects/interactions` — `GET` Get Object Interactions
- `/api/telemetry/objects/unused` — `GET` Get Unused Objects
- `/api/telemetry/performance` — `GET` Get Performance Statistics
- `/api/telemetry/performance/elementList` — `GET` Get distinct performance column elements
- `/api/telemetry/performance/queryProfile/{trinoFragmentId}/sourceBreakdown/{instanceId}` — `GET` Get Query Profile by Trino Fragment ID and Document Instance ID
- `/api/telemetry/performance/queryProfile/{trinoFragmentId}/sourceBreakdown/{instanceId}/{templateId}` — `GET` Get Query Profile by Trino Fragment ID and Document Instance ID
- `/api/telemetry/performance/queryProfile/{trinoQueryId}` — `GET` Get Query Profile by Trino Query ID
- `/api/telemetry/processing/status` — `GET` Get status for data processing
- `/api/telemetry/sentinel-performance-data` — `DELETE` Delete sentinel performance data older than specified timestamp
- `/api/telemetry/usage-insights/model/{modelId}/executions` — `GET` Get Data Model Usage Drilldown Executions
- `/api/telemetry/usage-insights/model/{modelId}/executions/elementList` — `GET` Get Data Model Execution Drilldown Element List
- `/api/telemetry/usage-insights/model/{modelId}/users` — `GET` Get Data Model Usage Drilldown Users
- `/api/telemetry/usage-insights/model/{modelId}/users/elementList` — `GET` Get Data Model User Drilldown Element List
- `/api/telemetry/usage-insights/object/{objectId}/executions` — `GET` Get Semantic Object Usage Drilldown Executions
- `/api/telemetry/usage-insights/object/{objectId}/executions/elementList` — `GET` Get Semantic Object Execution Drilldown Element List
- `/api/telemetry/usage-insights/object/{objectId}/users` — `GET` Get Semantic Object Usage Drilldown Users
- `/api/telemetry/usage-insights/object/{objectId}/users/elementList` — `GET` Get Semantic Object User Drilldown Element List
- `/api/telemetry/usage-insights/source/{sourceId}/executions` — `GET` Get Source Usage Drilldown Executions
- `/api/telemetry/usage-insights/source/{sourceId}/executions/elementList` — `GET` Get Source Execution Drilldown Element List
- `/api/telemetry/usage-insights/source/{sourceId}/models` — `GET` Get Source Usage Drilldown Models
- `/api/telemetry/usage-insights/source/{sourceId}/models/elementList` — `GET` Get Source Model Drilldown Element List
- `/api/telemetry/usage-insights/source/{sourceId}/users` — `GET` Get Source Usage Drilldown Users
- `/api/telemetry/usage-insights/source/{sourceId}/users/elementList` — `GET` Get Source User Drilldown Element List

### /api/testCenters (9)

- `/api/testCenters/integrityComparisons/{integrityComparisonId}/comparisons/{comparisonId}/rename` — `POST` Rename a Comparison Test result
- `/api/testCenters/integrityComparisons/{integrityComparisonId}/comparisons/{comparisonId}/resume` — `POST` Resume the aborted Comparison Test execution
- `/api/testCenters/integrityComparisons/{integrityComparisonId}/managedTests/{integrityTestId}` — `PUT` Update a Baseline Test managed by a Comparison Test
- `/api/testCenters/integrityTests/{integrityTestId}/baselines/{baselineId}/rename` — `POST` Rename a Baseline Test result
- `/api/testCenters/integrityTests/{integrityTestId}/baselines/{baselineId}/resume` — `POST` Resume the aborted Baseline Test execution
- `/api/testCenters/integrityTests/{integrityTestId}/baselines/{baselineId}/testObjectBaselines/{testObjectBaselineId}/pdf` — `GET` Get PDF captured during Baseline Test execution of a dossier or report
- `/api/testCenters/integrityTests/{integrityTestId}/resolvedTestObjects` — `GET` Preview resolved execution objects for a Baseline Test without running
- `/api/testCenters/internal/baseline-result-files` — `GET`
- `/api/testCenters/settings` — `GET` Get current settings; `PATCH` Partially update settings

### /api/users (4)

- `/api/users/aiSettings` — `GET` Get AI settings for the current user; `PUT` Update AI settings for the current user
- `/api/users/merge` — `POST` Merge users and usergroups
- `/api/users/merge/status` — `GET` Get merge job status
- `/api/users/merge/{jobId}/cancel` — `DELETE` Cancel merge job

### /api/v2 (5)

- `/api/v2/bots/cubes/status` — `POST` Get agent cube status.
- `/api/v2/bots/{botId}/caches/temp/check` — `POST` Check temp cache status
- `/api/v2/bots/{botId}/caches/temp/promote` — `POST` Promote temp cache entry
- `/api/v2/cubes/{cubeId}/instances/{instanceId}/parameters` — `GET` List the parameters of a Mosaic data model instance; `PATCH` Change the parameter values of a Mosaic data model instance
- `/api/v2/projects/setPlatformAnalytics` — `PATCH` |2

## Removed

- `/api/telemetry/dashboards/interactions`

## Cross-reference: the vendor's "What's new in the REST API" page (read 2026-10-01)

`https://microstrategy.github.io/rest-api-docs/whats-new` lists the documented additions by release; the 2026 entries map onto the paths above:

| Release | Documented additions | Paths in this inventory |
| --- | --- | --- |
| September 2026 | Apply Parameters to a Data Model Instance | `/api/dataModels/{dataModelId}/instances/{instanceId}` family (parameters on a data-model instance) |
| May 2026 | Save a Data Model as a New Data Model | `POST /api/model/dataModels/{id}/saveAs` |
| April 2026 | Export a Data Model, Restore a Data Model, Create unstructured data | `POST …/export`, `POST …/restore`, `POST /api/nuggets` |
| March 2026 | Unstructured Data APIs | `/api/nuggets…` (see `skills/create-unstructured-data/`) |
| January 2026 | External data models (retrieve / create / update / delete / update object / refresh) and data-model links (retrieve / create / update) | `…/externalDataModels…`, `…/links` (`reference_mosaic_model_linking.md`) |
| December 2025 | Retrieve data through a cube instance, retrieve a data model's SQL view | `POST /api/v2/cubes/{id}/instances`, `GET /api/v2/cubes/{id}/sqlView` (`reference_strategy_sql_visibility.md`) |
| November 2025 | System-hierarchy relationships, scope filter objects | `GET /api/model/systemHierarchy…`, scope filters |
| October 2025 | Data-model create/update, folders, tables, attributes, base metrics, smart attributes, metrics + embedded objects, workspaces, pipelines, source/wrangle tables, translations | the `/api/model/dataModels/{id}/…` build surface this repo's `build_mosaic.py` wraps |
| September 2025 | Data-model reads (model, folders, tables, metrics, embedded objects, attributes, relationships, smart attributes, base metrics, hierarchy); Bot APIs deprecated, "Next-Gen AI" renamed "Agent" | the inventory surface in `reference_strategy_mosaic_field_study.md` |
| August 2025 | Data-model refresh + scheduled refresh, security filters (CRUD + members), attribute elements, object ACL | `reference_mosaic_rest_api.md` security-filter and ACL sections |

The telemetry query-profile, Explorer MCP-server, scripts-conversion and admin bulk endpoints are in the tenant spec but not (yet) on the What's-new page — treat them as shipped-but-undocumented and verify behavior before relying on them.

## Where the official docs live

- Swagger UI on any Library: `{MSTR_BASE}/api-docs/index.html` (the JavaScript app; use the raw `api/openapi.yaml` for machines — `reference_strategy_openapi.md`).
- GitHub-hosted docs with what's-new, getting-started and common workflows: `https://microstrategy.github.io/rest-api-docs/`.
- Postman collection "Strategy REST API" (workspace `microstrategysdk`): `https://www.postman.com/microstrategysdk/microstrategy-rest-api/collection/77temg9/strategy-rest-api` — the same families as the spec with runnable examples; useful for request-body shapes the spec leaves as free-form strings (manipulations, bookmarks).

## Refresh procedure

```bash
curl -sS "$MSTR_BASE/api/openapi.yaml" -o /tmp/openapi-public.yaml
curl -sS "$MSTR_BASE/api/openapi.yaml?visibility=all" -o /tmp/openapi-all.yaml
python3 skills/build-mosaic-model/scripts/build_mosaic.py openapi-summary --out /tmp/openapi-all.yaml   # or diff path sets with a 20-line script: lines matching '^  /api/'
```

Diff the `^  /api/…:` path keys of the new file against this inventory; add the new families here with a date, move verified behavior into the topical memory (`reference_mosaic_rest_api.md`, `reference_strategy_sql_visibility.md`, admin/security references), and record anything tenant-specific in `captures/`. Related: `reference_strategy_openapi.md` (how to fetch the spec), `reference_strategy_surface_matrix.md`.
