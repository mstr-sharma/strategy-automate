---
name: Strategy administration platform workflows
description: Clarify datasource administration, distribution/subscriptions, migrations/packages, monitors/caches, search/browse, settings, and project administration.
type: reference
originSessionId: codex-session
---
Use this when the user asks for platform administration beyond semantic modeling: datasources, distribution services, migrations/packages, monitors, caches, jobs, project load/unload, settings, search/browse, or object ownership.

## Datasources and warehouse catalog

Two lanes share "datasource" language:

- **Warehouse catalog/read lane:** read namespaces, tables, columns, table preview, SQL preview. Used for model building and discovery.
- **Datasource administration lane:** create/update/delete database sources, connections, logins, mappings, OAuth tokens, project association, catalog settings, job priorities, DSN conversion.

Important paths:

- Catalog (namespace-scoped; corrected 2026-10-05): `GET /api/datasources/{id}/catalog/namespaces` → `GET …/catalog/namespaces/{ns}/tables` → `GET …/namespaces/{ns}/tables/{tableId}` (columns) and `…/tables/{tableId}/result` (preview); `…/namespaces/{ns}/tableSchemas` is internal; catalog settings `GET/PATCH …/catalog/settings`. There is no un-scoped `…/catalog/tables/{tableId}`. SQL preview `POST /api/datasources/{id}/sqlQuery` is internal.
- Admin: `/api/datasources`, `/api/datasources/{id}`, `/api/datasources/connections`, `/api/datasources/logins`, `/api/datasources/mappings`, `/api/datasources/{id}/projects`, `/api/datasources/{id}/jobPriorities`; connection test `POST /api/datasources/{id}/test` (204).
- DB object helpers: `GET /api/drivers`, `GET /api/gateways`. The `/api/dbobjects/dbmss|dsns|drivers` paths are **deprecated** and `/api/dbConnections` is internal + deprecated (corrected 2026-10-05).
- OAuth sources: `/api/datasources/{id}/oauth/auth`, `/oauth/token`.

Never write datasource passwords/logins to memory or repo. For destructive datasource changes, verify dependent projects and mappings first.

## Distribution services

Distribution spans more than `/api/subscriptions`:

- Subscriptions: `/api/subscriptions`, `/api/subscriptions/{id}`, `/api/subscriptions/{id}/send`, `/api/subscriptions/{id}/status`, `/api/subscriptions/{id}/owner`, `/api/subscriptions/query`.
- Schedules/events: `/api/schedules`, `/api/events`.
- User delivery addresses: `/api/users/{id}/addresses` and `/api/v2/users/{userId}/addresses`.
- Contacts/contact groups: `/api/contacts`, `/api/contactGroups`.
- Shared/dynamic recipients: `/api/dynamicRecipientLists`, `/api/subscriptions/recipients/results`, `/api/subscriptions/recipients/personalAddresses`.
- Transmitters/devices/images/templates: `/api/transmitters`, `/api/subscriptions/images`, template endpoints as exposed.

Privileges determine whether a caller sees only their own subscriptions or all project subscriptions. Read schedules, recipients, content IDs, prompt requirements, and delivery mode before creating/updating.

## Migrations and packages

High-impact lane. Use read/validate-first and capture source/target environment IDs.

- Package holder: `POST /api/packages`.
- Package definition/update: `GET/PUT /api/packages/{packageId}`.
- Package binary: `GET/PUT /api/packages/{packageId}/binary`.
- Package object detail: `GET /api/packages/{packageId}/objects`.
- Import: `POST /api/packages/imports`, `GET/DELETE /api/packages/imports/{importId}`.
- Undo package: `/api/packages/imports/{importId}/undoPackage/binary` and `/api/migrations/imports/{importId}/binary`.
- Migration records/groups: `/api/migrations`, `/api/migrationGroups`, validation/import/certification/transformation endpoints.

Package types matter:

- `project` packages carry project-level objects and require `X-MSTR-ProjectID`.
- `configuration` packages carry configuration-level objects and should omit project ID.
- `project security` packages carry users/user groups for a project and have different ACL replacement limits.

Avoid `keep_both` rules if the user needs undo/rollback support.

## Monitors, caches, jobs, and project administration

Common monitor/cache lanes:

- Cube cache monitor: `/api/monitors/caches/cubes`, `/api/monitors/caches/cubes/{cacheId}`, `/aggregatedUsages`, `/manipulations/{id}/status`.
- Content caches: `GET /api/monitors/caches/contents?clusterNode=<node>` (`clusterNode` required — so is it on `…/caches/cubes`); alter/remove with `PATCH /api/v2/monitors/caches/contents?clusterNode=<node>` (v1 PATCH deprecated).
- Object/element cache purge: `DELETE /api/monitors/projects/{projectId}/caches/{element|object|report|all}` → 204 (plural `caches`; corrected 2026-10-05).
- Jobs: `GET /api/v2/monitors/jobs?nodeName=<node>`, cancel via `DELETE /api/v2/monitors/jobs/{id}` or `POST /api/v2/monitors/cancelJobs` (v1 job paths deprecated). User connections: `GET /api/monitors/userConnections`, `DELETE /api/monitors/userConnections/{id}`. Details: `reference_strategy_monitoring_jobs_alerts.md`.
- Project load/unload/status: `/api/monitors/projects/status`, `/api/monitors/iServer/nodes/.../projects/...`.
- Cluster/nodes: `/api/monitors/iServer/nodes`, `/api/iserver/clusterStartupMembership`.
- Library/server status and restarts: `/api/monitors/libraryServer/status`.

Privileges are usually required for cache/admin monitor operations. Many operations are asynchronous and return IDs/status locations; poll before reporting success.

## Search, browse, lineage, and object management

Search variants:

- Quick search: `/api/searches/results` is fast but may be indexed/stale.
- Metadata search: `POST /api/metadataSearches/results`, then `GET /api/metadataSearches/results` or `/tree`; better for stored result sets and tree views.
- Folder browse: `/api/folders`, `/api/folders/{id}`, `/api/folders/preDefined/{folderType}`.
- Object management/search: `/api/objects`, `/api/objects/{id}`, bulk copy/move/delete, ownership, inspection, recommendations.
- Lineage/dependencies: `POST /api/metadataSearches/results?usesObject=<id>;<type>` (or `usedByObject=`) → `GET /api/metadataSearches/results?searchId=<id>`; quick `GET /api/searches/results?usesObjectId=<id>`; counts `POST /api/searches/dependents/count`. There is no `/api/objects/{id}/dependencies|dependents` (corrected 2026-10-05). Verify object type/subtype first.

When modifying existing objects, resolve by ID and type, then read the object before writing. Names are not unique.

## Settings, properties, and localization

Settings/properties are layered:

- Server/project settings (corrected 2026-10-05): the public surface is v2 — `GET/PUT/PATCH /api/v2/iserver/settings` (+ `/config`) and `GET/PUT/PATCH /api/v2/projects/{id}/settings` (+ `/config`). The v1 `/api/iserver/settings`, `/api/iserver/settings/publicsettings` and `/api/projects/{id}/settings` are internal.
- Object VLDB: `/api/objects/{id}/vldb/propertySets`, `/api/objects/{id}/vldb/propertySets/{name}`.
- Object extended properties: `/api/objects/{id}/type/{type}/propertySets...`.
- Modeling applicable properties: `.../applicableAdvancedProperties`, `.../applicableVldbProperties`.
- Translations/locales: `/api/objects/{type}/{id}/translations` and data-model object translation endpoints.
- Language formatting: `/api/languages/.../formattingSettings`.

Always read existing values and patch only intended keys.
