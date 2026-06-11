---
name: Mosaic API gotchas learned
description: Undocumented-or-surprising Mosaic REST behaviors — lifecycle symptom journal. Catalog base64 IDs, X-MSTR-IdentityToken mandatory, changeset commit rounds, managed-attribute trap (8004cd15), publish/delete paths, /api/users lockdown, ACL endpoint asymmetry, snowflake + entity-first patterns. Exact payload shapes live in reference_mosaic_rest_gotchas.md; session cap in feedback_build_mosaic_session_leak.md. Pair with reference_strategy_error_codes.md to grep from symptom to fix.
type: feedback
tags: [mosaic, build, payload, error-code]
---

## Table of contents

**Auth + changesets + session**
- [X-MSTR-IdentityToken is mandatory for Mosaic data-model changesets](#x-mstr-identitytoken-is-mandatory-for-mosaic-data-model-changesets)
- [Changesets don't magically cross-reference](#changesets-dont-magically-cross-reference)
- [Opening too many sessions without logout throws "Maximum interactive sessions per user"](#opening-too-many-sessions-without-logout-throws-maximum-interactive-sessions-per-user)

**Catalog + discovery**
- [Catalog IDs are base64(JSON), not UUIDs](#catalog-ids-are-base64json-not-uuids)
- [`/api/datasources` is project-agnostic](#apidatasources-is-project-agnostic)
- [Raw OpenAPI is at `/MicroStrategyLibrary/api/openapi.yaml`](#raw-openapi-is-at-microstrategylibraryapiopenapi-yaml)

**Payload shapes**
- [Table creation requires the "pipeline" shape, not "warehouse_partition_table"](#table-creation-requires-the-pipeline-shape-not-warehouse_partition_table)
- [Attributes must have a `displays` PATCH after create, or the changeset commit fails](#attributes-must-have-a-displays-patch-after-create-or-the-changeset-commit-fails)
- [Fact metric `fact.dataType` is a dict, not a string](#fact-metric-factdatatype-is-a-dict-not-a-string)
- [Fact metric `expression.tokens` operators use `type:"character"` not `"operator"`](#fact-metric-expressiontokens-operators-use-typecharacter-not-operator)
- [When payload shape is unknown: clone-and-remap](#when-payload-shape-is-unknown-clone-and-remap)

**Publish + delete**
- [Publish an in-memory data model via `POST /api/cubes/{modelId}` (empty body) → 202](#publish-an-in-memory-data-model-via-post-apicubesmodelid-empty-body--202)
- [Cube/model delete: `DELETE /api/objects/{id}?type=3`](#cubemodel-delete-delete-apiobjectsidtype3)

**Users, ACL, permissions**
- [`/api/users` is locked down on this tenant; use `/api/searches/results` to find users](#apiusers-is-locked-down-on-this-tenant-use-apisearchesresults-to-find-users)
- [Object ACL: use the data-model-contained object endpoint first](#object-acl-use-the-data-model-contained-object-endpoint-first)

**Schema topology + relationships**
- [Snowflake schema support](#snowflake-schema-support)
- [Canonical pattern: entity-first attribute creation](#canonical-pattern-entity-first-attribute-creation)
- [Relationships with shared keys need attribute-MERGE during creation, not after (superseded)](#relationships-with-shared-keys-need-attribute-merge-during-creation-not-after-superseded)

**Python-side bite**
- [Python operator precedence bit me on `or … if isinstance(…) else`](#python-operator-precedence-bit-me-on-or--if-isinstance-else)

---

## Auth + changesets + session

### X-MSTR-IdentityToken is mandatory for Mosaic data-model changesets
`POST /api/auth/identityToken` returns the token in a response header. Without it, changeset commits 400 silently.
**Why:** Early Mosaic build scripts failed commits until the `identityToken` call was added to every Modeling-Service write.
**How to apply:** fetch identity token immediately after login for Mosaic data-model writes; `MSTR.login(identity=True)` in the Mosaic helper does this. Do not automatically add identity token to classic/project Modeling Service reads/writes such as `/api/model/attributes`, `/api/model/metrics`, `/api/model/facts`, or `/api/model/securityFilters`; on a verified Strategy Cloud tenant it caused false project errors.

### Changesets don't magically cross-reference
Objects referenced inside a changeset must already exist (committed). Relationships + security filters + translations need a *separate* changeset AFTER the model + tables + attrs + metrics commit.
**Why:** Modeling writes must commit in rounds; mixing object-create and relationship-PUT in one changeset hits "object not found" errors.
**How to apply:** in `build`, commit base model first, THEN open a second changeset for relationships, SF, ACL, translations.

### Opening too many sessions without logout throws "Maximum interactive sessions per user"
Canonical coverage: `feedback_build_mosaic_session_leak.md` (cap ~5 per user per project; auth-token logout does NOT reap iServer sessions — ~30-min idle timer; one-session-one-process rule). Failure signature `8004cb0a` / iServerCode `-2147072486` in `reference_strategy_error_codes.md`.

---

## Catalog + discovery

### Catalog IDs are base64(JSON), not UUIDs
`namespaceId` = base64(`{"ns":"<schema>"}`); `tableId` = base64(`{"tbn":"<table>","ns":"<schema>"}`). The helper has `encode_ns_id` / `encode_tb_id`. Don't pass the raw schema name to `/tables` — it 404s.
**Why:** Learned the hard way when `--namespace PUBLIC` kept returning 404. The GET namespaces response shows the b64 id; decode it to confirm pattern.
**How to apply:** any new endpoint that takes `{ns_id}` / `{tb_id}` in the path must use these encoders; similarly decode if the REST response returns them raw.

### `/api/datasources` is project-agnostic
Canonical coverage: `reference_mosaic_rest_gotchas.md` § "DB instance + schema discovery" — returns everything visible to the user regardless of `X-MSTR-ProjectID`; filter client-side.

### Raw OpenAPI is at `/MicroStrategyLibrary/api/openapi.yaml`
The Swagger UI SPA exists at `/api-docs/`, but the useful machine-readable spec is `/api/openapi.yaml` under the Library root. `api-docs/swagger-config` 404s on the current tenant. Use `openapi-summary` to confirm title/version/path count, and use `discover` for live catalog path variants.

---

## Payload shapes

### Table creation requires the "pipeline" shape, not "warehouse_partition_table"
Canonical payload + ordering rules: `reference_mosaic_rest_gotchas.md` § "Physical tables" (full pipeline JSON, fresh-UUID rule, outer-vs-inner column shapes, clone-pattern fallback).

### Attributes must have a `displays` PATCH after create, or the changeset commit fails
Error: `Attribute 'X' cannot be saved because it has no report display.` Post-create, PATCH `/attributes/{aid}` with `{"displays":{"reportDisplays":[{"id":<formId>}], "browseDisplays":[{"id":<formId>}]}}` using form IDs from the POST response. This is the `8004cf06` case in `reference_strategy_error_codes.md`.

### Fact metric `fact.dataType` is a dict, not a string
Pass the full `{type, precision, scale}` object (the same shape the describe-table response returns) rather than a string like `"float"`. A string returns 400 "Cannot deserialize value of type int from String 'float'".

### Fact metric `expression.tokens` operators use `type:"character"` not `"operator"`
Canonical token shapes (operator/function/EOT tokens, full working example): `reference_mosaic_rest_gotchas.md` § "Fact metrics (custom formulas)".

### When payload shape is unknown: clone-and-remap
Fetch a working object via `GET /api/model/dataModels/{refModelId}/attributes/{id}` (or `/factMetrics/{id}` / `/filters/{id}`), generate fresh UUIDs for every inner `id`, remap every `objectId` that points at a replaced table/attr/metric, POST it back. Full procedure in `reference_strategy_object_cloning.md`.
**Why:** Modeling Service payloads are deeply nested and undocumented in places; the returned JSON is always a valid POST body.
**How to apply:** for transformation/conditional/level metrics and advanced form types, clone from any existing Mosaic model in the tenant that already has that construct (find via `search-objects --type 3`) before writing new payloads from scratch.

---

## Publish + delete

### Publish an in-memory data model via `POST /api/cubes/{modelId}` (empty body) → 202
NOT `/api/cubes/{id}/instances` (the latter requires an already-published cube and returns 500 otherwise). Same model id is used as cube id. Public OpenAPI also lists `/api/dataModels/{dataModelId}/publish`, but the verified no-interaction path on Strategy ONE Cloud tenants is the cube POST. Do not fire both concurrently — see `reference_mosaic_publish_path.md` ("Never fire both publish endpoints") for the iServerCode `-2147072194` lockout.

### Cube/model delete: `DELETE /api/objects/{id}?type=3`
Returns 204 on success. Type 3 = data model.

---

## Users, ACL, permissions

### `/api/users` is locked down on this tenant; use `/api/searches/results` to find users
`GET /api/users?limit=N` returns `{}` empty even for admin on some tenants. To find a user by name, search for any object they own via `/api/searches/results?name=<firstName>&limit=50` and read the `result[].owner.{id,name}` fields. The owner tuple carries the user's 32-hex id.

### Object ACL: use the data-model-contained object endpoint first
- Public OpenAPI exposes `PATCH /api/model/dataModels/{dataModelId}/objects/{objectId}/acl?subType=<objectSubType>` with body `{acl:{trusteeId:{granted,denied,subType:"user"|"user_group"}}}` and a changeset commit.
- Use this for Mosaic model children (attributes, fact metrics, model folders, etc.).
- Keep the older failures below as evidence of endpoints that do not work for this use case.

**Global object ACL PUT rejects every shape tried so far:**
- `POST /api/objects/{id}/acl` → 404
- `PUT /api/objects/{id}?type=4` with `{"acl":[{"trustee":{"id":TID,...},...}]}` → 400 "trustee is not valid"
- Same with flat `{"trusteeId":TID, "trusteeType":34, "trusteeSubtype":8704, "rights":..., "deny":true, "type":1}` → 500 "Invalid object ID"
- `PUT /api/objects/{id}/acl/{trusteeId}` / `PATCH /api/objects/{id}` → 404 / 405
- `PUT /api/permissions` → 404

**How to apply:** for objects inside a Mosaic data model, use the data-model ACL endpoint above. Only fall back to Library UI / Command Manager for global metadata objects that are not addressable through a data model.

---

## Schema topology + relationships

### Snowflake schema support
The entity-first pattern handles snowflake data design natively — no special-casing needed for dim chains. If `CATEGORY_ID` is the PK of a `CATEGORIES` dim and also appears in `PRODUCTS`, the same column-name heuristic creates a `Category` entity attribute with expressions on both, and wires `Category → Product` automatically. Multi-hop chains like `Category → Product → Order` fall out of the pairwise entity→entity inference.

Additions for snowflake:
- **Conformed dimensions:** a non-PK, non-noise string column in ≥2 tables (e.g., `REGION` in CUSTOMERS + SUPPLIERS) is created as ONE multi-table attribute instead of per-table duplicates with `(Table)` suffix.
- **Hierarchy path detection:** DFS over the entity-adjacency graph finds the longest dim chain (≥3 nodes) and emits a `hierarchy_path` + attempts to create a user-defined hierarchy object. The hierarchy POST endpoint on some tenants returned 404 at both `/hierarchies` and `/userHierarchies` — the relationships still wire correctly; the standalone hierarchy object is a nice-to-have. TBD: discover the right path (possibly `/drillHierarchies` or via `/objects` type 47).
- **Expanded noise list:** `SOURCE_SYSTEM, LOAD_TIMESTAMP, LAST_UPDATED_AT, INGESTION_DATE, LOAD_DATE, ETL_BATCH_ID, DW_CREATED_AT, DW_UPDATED_AT` (threshold: present in ≥3 tables).

### Canonical pattern: entity-first attribute creation
Each table's PK column becomes ONE multi-table "entity" attribute with expressions on every occurrence of that column. All other columns become descriptor attributes on their single table. Relationships are then:
- descriptor → entity (within the same table, join_table = that table)
- dim-entity → fact-entity (when the dim's PK column also exists on the fact table; join_table = the fact table)

MSTR validates `attribute must exist on the join table` — which this pattern satisfies because the dim entity's expressions include the fact table.

PK heuristic: strip timestamp prefix → try `{singular}_{ID|NUMBER|KEY|NO}` on the table singular (PRODUCTS → PRODUCT_ID) AND on the acronym of multi-word tables (PURCHASE_ORDERS → PO → PO_NUMBER). Fallback: any `*_ID|*_NUMBER|*_KEY` column (excluding noise like SOURCE_SYSTEM).

Noise columns (present in every table but not real dimensions — e.g., SOURCE_SYSTEM, LOAD_TIMESTAMP, LAST_UPDATED_AT) are skipped from attribute creation entirely.

### Relationships with shared keys need attribute-MERGE during creation, not after (superseded)

> Superseded by `feedback_mosaic_relationship_wiring.md` (six-step conformance recipe). Fix: create shared-key attributes with multi-table expressions on the FIRST POST — the entity-first pattern in `build_mosaic.py` does this; for post-hoc wiring use `build_mosaic.py wire-relationships`.
> Historical dead ends it replaced: separate per-fact FK attributes → `8004ccc7` "Table cannot be used as the join table…"; naive post-create expression-append PATCH resolves column-reference tokens against MSTR's auto-generated managed attributes in `\Managed Objects\Dataset Schema Folder\` → `8004cd15` "Object (of type: Attribute) not allowed in this place"; DELETE-then-recreate → "cannot be deleted because other objects depend on it", even mid-changeset.

---

## Python-side bite

### Python operator precedence bit me on `or … if isinstance(…) else`
`x.get("k") or x if isinstance(x,list) else []` parses as `(x.get("k") or x) if isinstance(x,list) else []` — so when `x` is a dict, the entire thing is `[]`. Always parenthesize the conditional.
**Why:** `list-datasources` returned `[]` despite a full server response.
**How to apply:** any normalization of `dict_or_list_body.get(...) or body if isinstance...` needs explicit parens.
