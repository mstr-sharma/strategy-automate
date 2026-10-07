---
name: Mosaic REST API map
description: Verified endpoint paths and payload shapes for the {MSTR_BASE host} MicroStrategy REST API; covers auth, datasources, catalog, data models, changesets, metrics, filters, transformations, security, translations, VLDB.
type: reference
originSessionId: initial-session
---
All paths prefixed with `{BASE} = {MSTR_BASE}`. Unless otherwise noted, send `X-MSTR-AuthToken`, `X-MSTR-ProjectID`, and for Mosaic data-model writes `X-MSTR-MS-Changeset`. `X-MSTR-IdentityToken` is tenant-dependent. `build_mosaic.py` mints it for Mosaic data-model changeset pipelines (`login(identity=True)`: on the verified Cloud tenant, commits returned 400 without it, 2026-08-19) and leaves it off for plain reads and classic/project Modeling calls; if a write 403s with `8004cb09`, rerun without it (`feedback_mosaic_identity_token_privilege_downgrade.md`). Never send it on classic/project Modeling Service endpoints.

## OpenAPI / docs
- Raw machine-readable spec: `GET /api/openapi.yaml` (OpenAPI 3.0.1, title `Strategy REST`, version `2026` as of 2026-04-21).
- Swagger/API Explorer UI: `/api-docs/` is a JavaScript app; use it interactively, not as a scrape target.
- `api-docs/swagger-config` 404s on {MSTR_BASE host}; use `strategy_api.py sync` / `ops` (or the older `openapi-summary`).

## Auth
- `POST /api/auth/login` body `{username,password,loginMode:1}` → response header `X-MSTR-AuthToken` (lowercase `X-Mstr-Authtoken` on some responses).
- `POST /api/auth/identityToken` → header `X-MSTR-IdentityToken`. Tenant-dependent for Mosaic data-model changesets (on in build_mosaic's pipelines — see above); avoid for classic/project Modeling Service unless a specific endpoint proves it needs it.
- `POST /api/auth/logout` — logout. (`DELETE /api/auth/login` is not in the spec and answers 404 — corrected 2026-10-05.)

## Datasources / warehouse catalog (verified 2026-04-20)
- `GET /api/datasources` → `{"datasources":[{id,name,description,database,dbms,...}]}` (`id` is 32-hex)
- `GET /api/datasources/{dsId}/catalog/namespaces` → `{"namespaces":[{name, id}]}` where `id` = base64(`{"ns":"<schemaName>"}`)
- `GET /api/datasources/{dsId}/catalog/namespaces/{namespaceId}/tables` → `{"tables":[{name, id, namespace}]}` where table `id` = base64(`{"tbn":"<tableName>","ns":"<schema>"}`)
- `GET /api/datasources/{dsId}/catalog/namespaces/{namespaceId}/tables/{tableId}` → full column list + metadata (`{"columns":[{name,dataType:{type,precision,scale}}]}`; numeric(p,s) → `decimal`, varchar(n) → `fixed_length_string`). The shorter `/catalog/tables/{tableId}` form 404s (observed 2026-09-17); `describe-table` in the helper uses the namespace-scoped path. The `/catalog/namespaces` list can lag behind a freshly created schema while the namespace-scoped table list already resolves it.
- `POST /api/datasources/{dsId}/test` → 204 — connection test (there is no `/testConnection`; corrected 2026-10-05)

**ID encoding:** namespace + table IDs are NOT opaque UUIDs — they are base64(JSON). The helper script encodes them; if you hand-craft, add `=` padding to multiple of 4.

## Changesets (transactional unit for all schema writes)
- `POST /api/model/changesets` body `{}` → `{id}`. Send as `X-MSTR-MS-Changeset` on every subsequent write.
- `POST /api/model/changesets/{id}/commit`
- `DELETE /api/model/changesets/{id}` (discard)
- Always send the changeset as the `X-MSTR-MS-Changeset` header: no operation in the spec declares a `changesetId` query parameter (150 operations declare the header). Corrected 2026-10-05 — earlier text said some writes take `?changesetId=`.

## Data models
- `POST /api/model/dataModels` body:
  ```json
  {"information":{"name":"X","destinationFolderId":"<folderId>"},
  "dataServeMode":"connect_live" | "in_memory" | "off_memory"}   # spec enum, 2026; no "hybrid"
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
- `POST /api/model/dataModels/{id}/factMetrics` — fact metrics (a `fact` block + `function`); `attach-transformation` still posts transformation metrics here (unverified)
- `POST /api/model/dataModels/{id}/metrics` — derived metrics: compound, level, conditional (conditional adds `POST .../metrics/{metricId}/embeddedObjects` for its filter); verified bodies in `reference_mosaic_derived_metrics.md`
- `GET /api/model/dataModels/{id}/hierarchy` — read-only list of every relationship in the model's hierarchy.
- **Not data-model sub-resources (corrected 2026-10-05):** the spec has no `/api/model/dataModels/{id}/facts`, `/filters`, `/transformations`, `/hierarchies`, `/consolidations`, `/customGroups` or `/prompts`. Those objects exist only at project level — `POST /api/model/facts`, `/filters`, `/transformations`, `/hierarchies`, `/consolidations`, `/customGroups`, `/prompts` (changeset-scoped).
- `PUT .../attributes/{aid}/relationships` with the `X-MSTR-MS-Changeset` header — set parent-child relationships (earlier text said `?changesetId=`; the spec only takes the header)
- `POST .../securityFilters` → then assign with `PATCH /api/dataModels/{dataModelId}/securityFilters/{securityFilterId}/members`
- Classic schema objects outside a Mosaic model use `/api/model/attributes/{attributeId}`, `/api/model/metrics/{metricId}`, `/api/model/facts/{factId}`, and `/api/model/tables/{tableId}`. Read with `showExpressionAs=tokens|tree`, patch through a changeset, then commit.

## Cubes (in-memory model backing store) — corrected 2026-10-05
- Mosaic publish = the documented `/api/dataModels/{id}` flow: `POST …/instances` → `POST …/publish` (`tables[].refreshPolicy`) → `GET …/publishStatus` → `DELETE …/instances/{instanceId}`. See `reference_mosaic_publish_path.md`.
- `POST /api/cubes/{id}` (`?cubeAction=publish`) — internal + deprecated in the spec; the {MSTR_BASE host} Studio UI fired it in 2026-04 captures. Tenant-observed fallback only, never in the same run as the documented flow.
- `POST /api/v2/cubes/{id}` — public publish for Intelligent / MTDI cubes (202 + job id); `HEAD /api/cubes/{id}` returns cube state in `X-MSTR-CubeStatus`.
- Not in the spec: `POST /api/cubes/{id}/publish`, `POST /api/cubes/{id}/refresh`, `PATCH /api/cubes/{id}` (earlier text listed them). Incremental refresh is its own object: `POST /api/model/incrementalRefresh` (define) + `POST /api/incrementalRefresh/{irrId}` (run). Scheduled Mosaic refresh is a subscription (`reference_strategy_subscriptions_and_schedules.md`).

## Governance: ACL, translations, certification
- Data-model-contained object ACL: `PATCH /api/model/dataModels/{dataModelId}/objects/{objectId}/acl?subType=<objectSubType>` inside a changeset. Body: `{acl:{trusteeId:{granted:<mask>, denied:<mask>, subType:"user"|"user_group"}}}`.
- There is no `/api/objects/{objId}/acl` sub-resource (a `POST` there 404s). Classic ACL is `GET /api/objects/{id}?type=` (read `acl[]`) and `PUT /api/objects/{id}?type=` with an `acl` body (write); use the data-model ACL endpoint when the object belongs to a Mosaic model.
  Rights mask flags (EnumDSSXMLAccessRightFlags; corrected 2026-10-05 — the old table here was wrong): browse=1, use_execute=2, read=4, write=8, delete=16, control=32, use=64, execute=128; bundles view=197, modify=221, full=255. Inheritance is the separate `inheritable` flag, not a bit. See `reference_mosaic_acl.md`.
- Data-model translations: `PATCH /api/model/dataModels/{dataModelId}/objects/{objectId}/translations?subType=<objectSubType>` inside a changeset. Body has `name.translationValues` and/or `description.translationValues` keyed by locale.
- Global translations in public spec use `/api/objects/{type}/{id}/translations`, not `/api/objects/{id}/translations`.
- Certify: `PUT /api/objects/{objId}/certify?type=<type>&certify=true|false` (the spec has no `PATCH /api/objects/{id}`; corrected 2026-10-05).
- VLDB: `GET/DELETE /api/objects/{id}/vldb/propertySets` and `PUT …/vldb/propertySets/{name}` (internal; datasets/documents), plus public `GET /api/model/{reports|cubes|datamarts}/{id}/applicableVldbProperties`. There is no `/api/objects/{id}/vldbProperties` (corrected 2026-10-05).

## Users / security roles / privileges
- `GET /api/users?nameBegins=X&limit=N`
- `POST /api/users` creates a user; required body fields are `username` and `fullName`. Optional: `password`, `enabled`, `standardAuth`, `memberships`, `languageId`, SSO/LDAP fields.
- `PATCH /api/users/{id}` uses `{operationList:[{op:"add"|"replace"|"remove", path:"/memberships", value:[...]}]}`.
- `POST /api/users/{id}/addresses` creates the default email address (`deliveryMode:"EMAIL"`, `device:"GENERIC_EMAIL"`).
- `GET /api/usergroups`, `GET /api/users/{id}/securityRoles` (read), `PATCH /api/securityRoles/{id}/members` (assign — there is no `POST /api/users/{id}/securityRoles`; corrected 2026-10-05), `GET /api/users/{id}/privileges`.

## Folders / search
- `GET /api/folders/{folderId}?limit=N&offset=M` → flat list of items with `subtype`.
- Quick search: `GET /api/searches/results?name=…&type=…`. Stored metadata search: `POST /api/metadataSearches/results` → `{id}`, then `GET /api/metadataSearches/results?searchId=<id>&offset=&limit=`. (There is no `POST /api/searches` / `GET /api/searches/{id}/results`; corrected 2026-10-05.)
- Key subtypes for filtering: 3840 logical_table, 3072 attribute, 1033 fact_metric, 1034 compound_metric, 779 report_emma_cube (a Mosaic model only with extType 448 — data-import cubes share 779).

## Known quirks
- **`/api/datasources`** returns every datasource the user can see regardless of project; filter client-side by name.
- **Catalog IDs are base64(JSON)**, not UUIDs — must be computed, not guessed.
- **Changesets can silently fail to commit** if any referenced object (e.g., a security-filter member) doesn't resolve; helper script prints the full response on non-2xx.
- **Relationships must live in a separate changeset after tables/attributes commit** — the objects referenced must already exist in metadata.

## Model-level operations added in the 2026 spec (listed 2026-10-01, not yet exercised)
- `POST /api/model/dataModels/{id}/export` → the model as YAML (`ms-YamlModel`); `POST …/restore` (multipart YAML file) restores a definition inside a changeset — commit it; `POST …/saveAs` (`ms-DataModelSaveAsRequest`) copies the model. First documented export/import path for Mosaic models; try before building another clone-and-remap script.
- `GET …/externalDataModels/{externalId}/objects?showDefinition=` → the objects a composed model imported from one base model.
