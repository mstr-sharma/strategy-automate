---
name: Mosaic REST API map
description: Verified endpoint paths and payload shapes for the {MSTR_BASE host} MicroStrategy REST API; covers auth, datasources, catalog, data models, changesets, metrics, filters, transformations, security, translations, VLDB.
type: reference
originSessionId: initial-session
---
All paths prefixed with `{BASE} = {MSTR_BASE}`. Unless otherwise noted, send `X-MSTR-AuthToken`, `X-MSTR-ProjectID`, and (for writes) `X-MSTR-IdentityToken` + `X-MSTR-MS-Changeset`.

## OpenAPI / docs
- Raw machine-readable spec: `GET /api/openapi.yaml` (OpenAPI 3.0.1, title `Strategy REST`, version `2026` as of 2026-04-21).
- Swagger/API Explorer UI: `/api-docs/` is a JavaScript app; use it interactively, not as a scrape target.
- `api-docs/swagger-config` 404s on {MSTR_BASE host}; use `openapi-summary` in the helper.

## Auth
- `POST /api/auth/login` body `{username,password,loginMode:1}` → response header `X-MSTR-AuthToken` (lowercase `X-Mstr-Authtoken` on some responses).
- `POST /api/auth/identityToken` → header `X-MSTR-IdentityToken`. Required before any `/api/model/*` write.
- `DELETE /api/auth/login` — logout.

## Datasources / warehouse catalog (verified 2026-04-20)
- `GET /api/datasources` → `{"datasources":[{id,name,description,database,dbms,...}]}` (`id` is 32-hex)
- `GET /api/datasources/{dsId}/catalog/namespaces` → `{"namespaces":[{name, id}]}` where `id` = base64(`{"ns":"<schemaName>"}`)
- `GET /api/datasources/{dsId}/catalog/namespaces/{namespaceId}/tables` → `{"tables":[{name, id, namespace}]}` where table `id` = base64(`{"tbn":"<tableName>","ns":"<schema>"}`)
- `GET /api/datasources/{dsId}/catalog/tables/{tableId}` → full column list + metadata
- `POST /api/datasources/{dsId}/testConnection`

**ID encoding:** namespace + table IDs are NOT opaque UUIDs — they are base64(JSON). The helper script encodes them; if you hand-craft, add `=` padding to multiple of 4.

## Changesets (transactional unit for all schema writes)
- `POST /api/model/changesets` body `{}` → `{id}`. Send as `X-MSTR-MS-Changeset` on every subsequent write.
- `POST /api/model/changesets/{id}/commit`
- `DELETE /api/model/changesets/{id}` (discard)
- Some writes accept `?changesetId={id}` as query param instead of header.

## Data models
- `POST /api/model/dataModels` body:
  ```json
  {"information":{"name":"X","destinationFolderId":"<folderId>"},
  "dataServeMode":"connect_live" | "in_memory" | "hybrid"}
  ```
- `GET /api/model/dataModels/{id}` — full def including `schemaFolderId`
- `PATCH /api/model/dataModels/{id}` — rename, move, change `dataServeMode`
- `DELETE /api/objects/{id}?type=3` — delete a data model (type 3)

## Physical tables inside a model
- `POST /api/model/dataModels/{id}/tables` with `physicalTable` variants:
  - **warehouse_partition_table** (preferred for live):
    ```json
    {"information":{"name":"T"},
     "physicalTable":{"type":"warehouse_partition_table",
                      "namespace":"SCHEMA","tableName":"T",
                      "databaseInstance":{"objectId":"<dsId>"}}}
    ```
  - **pipeline** — used by clone-and-remap (TPCH script); pipeline JSON preserved from source.
  - **freeform_sql** — body includes `sqlStatement` + column mapping.

## Attributes / facts / metrics / filters / transformations
See `reference_mosaic_modeling_concepts.md` for full body shapes. Endpoints:
- `POST /api/model/dataModels/{id}/attributes`
- `POST /api/model/dataModels/{id}/facts`
- `POST /api/model/dataModels/{id}/factMetrics` (also used for compound/conditional/transformation metrics — differentiator is which top-level keys are set)
- `POST /api/model/dataModels/{id}/filters`
- `POST /api/model/dataModels/{id}/transformations`
- `POST /api/model/dataModels/{id}/hierarchies`
- `POST /api/model/dataModels/{id}/consolidations`, `/customGroups`, `/prompts`
- `PUT .../attributes/{aid}/relationships?changesetId=…` — set parent-child relationships
- `POST .../securityFilters` → then assign with `PATCH /api/dataModels/{dataModelId}/securityFilters/{securityFilterId}/members`
- Classic schema objects outside a Mosaic model use `/api/model/attributes/{attributeId}`, `/api/model/metrics/{metricId}`, `/api/model/facts/{factId}`, and `/api/model/tables/{tableId}`. Read with `showExpressionAs=tokens|tree`, patch through a changeset, then commit.

## Cubes (in-memory model backing store)
- `POST /api/cubes/{id}` — verified {MSTR_BASE host} publish path for in-memory Mosaic models.
- `POST /api/cubes/{id}/publish` — public/older cube publish variant; keep as fallback.
- `POST /api/cubes/{id}/refresh?refreshType=update|add|replace|incremental`
- `PATCH /api/cubes/{id}` for `incrementalRefresh.filterId`.

## Governance: ACL, translations, certification
- Data-model-contained object ACL: `PATCH /api/model/dataModels/{dataModelId}/objects/{objectId}/acl?subType=<objectSubType>` inside a changeset. Body: `{acl:{trusteeId:{granted:<mask>, denied:<mask>, subType:"user"|"user_group"}}}`.
- Global `POST /api/objects/{objId}/acl` is not accepted on {MSTR_BASE host} for the tested object-security use case; use the data-model ACL endpoint when object belongs to a Mosaic model.
  Rights mask flags: read=1, write=2, delete=4, control=32, execute=128, browse=64, use=512, inherit=1024, full=255.
- Data-model translations: `PATCH /api/model/dataModels/{dataModelId}/objects/{objectId}/translations?subType=<objectSubType>` inside a changeset. Body has `name.translationValues` and/or `description.translationValues` keyed by locale.
- Global translations in public spec use `/api/objects/{type}/{id}/translations`, not `/api/objects/{id}/translations`.
- `PATCH /api/objects/{objId}` body `{certifiedInfo:{certified:true}}`
- `GET/PATCH /api/objects/{id}/vldbProperties?type=` — SQL-generation overrides.

## Users / security roles / privileges
- `GET /api/users?nameBegins=X&limit=N`
- `POST /api/users` creates a user; required body fields are `username` and `fullName`. Optional: `password`, `enabled`, `standardAuth`, `memberships`, `languageId`, SSO/LDAP fields.
- `PATCH /api/users/{id}` uses `{operationList:[{op:"add"|"replace"|"remove", path:"/memberships", value:[...]}]}`.
- `POST /api/users/{id}/addresses` creates the default email address (`deliveryMode:"EMAIL"`, `device:"GENERIC_EMAIL"`).
- `GET /api/usergroups`, `POST /api/users/{id}/securityRoles`, `GET /api/users/{id}/privileges`.

## Folders / search
- `GET /api/folders/{folderId}?limit=N&offset=M` → flat list of items with `subtype`.
- `POST /api/searches` → `GET /api/searches/{id}/results`.
- Key subtypes for filtering: 3840 logical_table, 3072 attribute, 1033 fact_metric, 1034 compound_metric, 779 data_model.

## Known quirks
- **`/api/datasources`** returns every datasource the user can see regardless of project; filter client-side by name.
- **Catalog IDs are base64(JSON)**, not UUIDs — must be computed, not guessed.
- **Changesets can silently fail to commit** if any referenced object (e.g., a security-filter member) doesn't resolve; helper script prints the full response on non-2xx.
- **Relationships must live in a separate changeset after tables/attributes commit** — the objects referenced must already exist in metadata.
