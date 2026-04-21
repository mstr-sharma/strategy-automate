---
name: Strategy administration platform workflows
description: Clarify datasource administration, distribution/subscriptions, migrations/packages, monitors/caches, search/browse, settings, and project administration.
type: reference
originSessionId: local-codex-2026-04-21
---
Use this when the user asks for platform administration beyond semantic modeling: datasources, distribution services, migrations/packages, monitors, caches, jobs, project load/unload, settings, search/browse, or object ownership.

## Datasources and warehouse catalog

Two lanes share "datasource" language:

- **Warehouse catalog/read lane:** read namespaces, tables, columns, table preview, SQL preview. Used for model building and discovery.
- **Datasource administration lane:** create/update/delete database sources, connections, logins, mappings, OAuth tokens, project association, catalog settings, job priorities, DSN conversion.

Important paths:

- Catalog: `/api/datasources/{id}/catalog/namespaces`, `/tables`, `/tableSchemas`, `/tables/{tableId}`, `/result`, `/sqlQuery`.
- Admin: `/api/datasources`, `/api/datasources/{id}`, `/api/datasources/connections`, `/api/datasources/logins`, `/api/datasources/mappings`, `/api/datasources/{id}/projects`, `/api/datasources/{id}/jobPriorities`.
- DB object helpers: `/api/dbobjects/dbmss`, `/api/dbobjects/dsns`, `/api/dbobjects/drivers`, `/api/dbConnections`.
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
- Content caches: `/api/monitors/caches/contents`.
- Object/element cache purge: `/api/monitors/projects/{projectId}/cache/{cacheType}`.
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
- Lineage/dependencies: dependency/dependent paths in OpenAPI; verify object type/subtype first.

When modifying existing objects, resolve by ID and type, then read the object before writing. Names are not unique.

## Settings, properties, and localization

Settings/properties are layered:

- Server/project settings: `/api/iserver/settings`, `/api/projects/{id}/settings`, public/default settings endpoints.
- Object VLDB: `/api/objects/{id}/vldb/propertySets`, `/api/objects/{id}/vldb/propertySets/{name}`.
- Object extended properties: `/api/objects/{id}/type/{type}/propertySets...`.
- Modeling applicable properties: `.../applicableAdvancedProperties`, `.../applicableVldbProperties`.
- Translations/locales: `/api/objects/{type}/{id}/translations` and data-model object translation endpoints.
- Language formatting: `/api/languages/.../formattingSettings`.

Always read existing values and patch only intended keys.
