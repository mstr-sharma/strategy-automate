---
name: Mosaic API gotchas learned
description: Bugs and lessons from the first pass building the mosaic-build skill — keep these in mind when extending.
type: feedback
originSessionId: cef55f31-c57d-4220-b4dc-eddfff684771
---
## Catalog IDs are base64(JSON), not UUIDs
`namespaceId` = base64(`{"ns":"<schema>"}`); `tableId` = base64(`{"tbn":"<table>","ns":"<schema>"}`). The helper has `encode_ns_id` / `encode_tb_id`. Don't pass the raw schema name to `/tables` — it 404s.
**Why:** Learned the hard way when `--namespace PUBLIC` kept returning 404. The GET namespaces response shows the b64 id; decode it to confirm pattern.
**How to apply:** any new endpoint that takes `{ns_id}` / `{tb_id}` in the path must use these encoders; similarly decode if the REST response returns them raw.

## Python operator precedence bit me on `or … if isinstance(…) else`
`x.get("k") or x if isinstance(x,list) else []` parses as `(x.get("k") or x) if isinstance(x,list) else []` — so when `x` is a dict, the entire thing is `[]`. Always parenthesize the conditional.
**Why:** `list-datasources` returned `[]` despite a full server response.
**How to apply:** any normalization of `dict_or_list_body.get(...) or body if isinstance...` needs explicit parens.

## `X-MSTR-IdentityToken` is mandatory for Modeling-Service changesets
`POST /api/auth/identityToken` returns the token in a response header. Without it, changeset commits 400 silently.
**Why:** The TPCH build script failed commits until the `identityToken` call was added — see `build_tpch_mosaic_model.py:105–108`.
**How to apply:** always fetch identity token immediately after login; `MSTR.login()` in the helper does this.

## Changesets don't magically cross-reference
Objects referenced inside a changeset must already exist (committed). Relationships + security filters + translations need a *separate* changeset AFTER the model + tables + attrs + metrics commit.
**Why:** TPCH script commits in two rounds; mixing them in one changeset hits "object not found" errors.
**How to apply:** in `build`, commit base model first, THEN open a second changeset for relationships, SF, ACL, translations.

## When payload shape is unknown: clone-and-remap
Fetch a working object via `GET /api/model/dataModels/{refModelId}/attributes/{id}` (or `/factMetrics/{id}` / `/filters/{id}`), generate fresh UUIDs for every inner `id`, remap every `objectId` that points at a replaced table/attr/metric, POST it back. The TPCH build script is the canonical example.
**Why:** Modeling Service payloads are deeply nested and undocumented in places; the returned JSON is always a valid POST body.
**How to apply:** for transformation/conditional/level metrics and advanced form types, clone from the TPCH reference (id `3D4154B75ACF47DCB90806983EF57160`) before writing new payloads from scratch.

## `/api/datasources` is project-agnostic
Returns every datasource visible to the user regardless of `X-MSTR-ProjectID`. Filter client-side if the user only wants those attached to a specific project.

## Raw OpenAPI is at `/MicroStrategyLibrary/api/openapi.yaml`
The Swagger UI SPA exists at `/api-docs/`, but the useful machine-readable spec is `/api/openapi.yaml` under the Library root. `api-docs/swagger-config` 404s on the current tenant. Use `openapi-summary` to confirm title/version/path count, and use `discover` for live catalog path variants.

## Table creation requires the "pipeline" shape, not "warehouse_partition_table"
The MSTR Modeling docs mention `type:"warehouse_partition_table"` but on studio.strategy.com it returns 400 "Invalid value for field 'type'". Use `type:"pipeline"` with an inner `rootTable.children[0].importSource:{type:"single_table", dataSourceId, namespace, tableName, sql:""}`. See `build_tpch_mosaic_model.py` for the canonical shape or `cmd_build` in the helper after the 2026-04-21 fix.
**How to apply:** always build the pipeline JSON with fresh UUIDs for every inner id, and set outer `physicalTable.columns` as `[{information:{name}, dataType, columnName}]` (no top-level id) while inner `pipeline.rootTable.children[].columns` uses `[{id, name, dataType, sourceDataType}]`.

## Attributes must have a `displays` PATCH after create, or the changeset commit fails
Error: `Attribute 'X' cannot be saved because it has no report display.` Post-create, PATCH `/attributes/{aid}` with `{"displays":{"reportDisplays":[{"id":<formId>}], "browseDisplays":[{"id":<formId>}]}}` using form IDs from the POST response.

## Fact metric `fact.dataType` is a dict, not a string
Pass the full `{type, precision, scale}` object (the same shape the describe-table response returns) rather than a string like `"float"`. A string returns 400 "Cannot deserialize value of type int from String 'float'".

## Fact metric `expression.tokens` operators use `type:"character"` not `"operator"`
For a formula inside a fact metric, the operator token type is `character` (not `operator`, `metric_reference`, or `object_reference`). Working shape:
```
"tokens":[{"type":"column_reference","value":"TOTAL_COST"},
          {"type":"character","value":"/"},
          {"type":"column_reference","value":"QUANTITY_ORDERED"}]
```
This is what made the "derived calculation" (fact metric with inline formula) finally commit.

## Publish an in-memory data model via `POST /api/cubes/{modelId}` (empty body) → 202
NOT `/api/cubes/{id}/instances` (the latter requires an already-published cube and returns 500 otherwise). Same model id is used as cube id. Public OpenAPI also lists `/api/dataModels/{dataModelId}/publish`, but the studio tenant's verified no-interaction path is cube POST.

## Cube/model delete: `DELETE /api/objects/{id}?type=3`
Returns 204 on success. Type 3 = data model.

## `/api/users` is locked down on this tenant; use `/api/searches/results` to find users
`GET /api/users?limit=N` returns `{}` empty even for admin. To find a user by name, search for any object they own via `/api/searches/results?name=<firstName>&limit=50` and read the `result[].owner.{id,name}` fields. Verified: `O'Connell, Tommy` has user id `DBE00854E14B8D8919D3FBADCA61894B`.

## Object ACL: use the data-model-contained object endpoint first
- Public OpenAPI exposes `PATCH /api/model/dataModels/{dataModelId}/objects/{objectId}/acl?subType=<objectSubType>` with body `{acl:{trusteeId:{granted,denied,subType:"user"|"user_group"}}}` and a changeset commit.
- Use this for Mosaic model children (attributes, fact metrics, model folders, etc.).
- Keep the older failures below as evidence of endpoints that do not work on studio.strategy.com for this use case.

### Global object ACL PUT on this tenant rejects every shape tried so far
- `POST /api/objects/{id}/acl` → 404
- `PUT /api/objects/{id}?type=4` with `{"acl":[{"trustee":{"id":TID,...},...}]}` → 400 "trustee is not valid"
- Same with flat `{"trusteeId":TID, "trusteeType":34, "trusteeSubtype":8704, "rights":..., "deny":true, "type":1}` → 500 "Invalid object ID "
- `PUT /api/objects/{id}/acl/{trusteeId}` / `PATCH /api/objects/{id}` → 404 / 405
- `PUT /api/permissions` → 404

**How to apply:** for objects inside a Mosaic data model, use the data-model ACL endpoint above. Only fall back to Library UI / Command Manager for global metadata objects that are not addressable through a data model.

## Snowflake schema support (2026-04-21)
The entity-first pattern handles snowflake data design natively — no special-casing needed for dim chains. If `CATEGORY_ID` is the PK of a `CATEGORIES` dim and also appears in `PRODUCTS`, the same column-name heuristic creates a `Category` entity attribute with expressions on both, and wires `Category → Product` automatically. Multi-hop chains like `Category → Product → Order` fall out of the pairwise entity→entity inference.

Added for snowflake:
- **Conformed dimensions:** a non-PK, non-noise string column in ≥2 tables (e.g., `REGION` in CUSTOMERS + SUPPLIERS) is created as ONE multi-table attribute instead of per-table duplicates with `(Table)` suffix.
- **Hierarchy path detection:** DFS over the entity-adjacency graph finds the longest dim chain (≥3 nodes) and emits a `hierarchy_path` + attempts to create a user-defined hierarchy object. The hierarchy POST endpoint on this tenant returned 404 at both `/hierarchies` and `/userHierarchies` — the relationships still wire correctly; the standalone hierarchy object is a nice-to-have. TBD: discover the right path (possibly `/drillHierarchies` or via `/objects` type 47).
- **Expanded noise list:** `SOURCE_SYSTEM, LOAD_TIMESTAMP, LAST_UPDATED_AT, INGESTION_DATE, LOAD_DATE, ETL_BATCH_ID, DW_CREATED_AT, DW_UPDATED_AT` (threshold: present in ≥3 tables).

## Canonical pattern: entity-first attribute creation (RESOLVED 2026-04-21)
Each table's PK column becomes ONE multi-table "entity" attribute with expressions on every occurrence of that column. All other columns become descriptor attributes on their single table. Relationships are then:
- descriptor → entity (within the same table, join_table = that table)
- dim-entity → fact-entity (when the dim's PK column also exists on the fact table; join_table = the fact table)

MSTR validates `attribute must exist on the join table` — which this pattern satisfies because the dim entity's expressions include the fact table.

PK heuristic: strip timestamp prefix → try `{singular}_{ID|NUMBER|KEY|NO}` on the table singular (PRODUCTS → PRODUCT_ID) AND on the acronym of multi-word tables (PURCHASE_ORDERS → PO → PO_NUMBER). Fallback: any `*_ID|*_NUMBER|*_KEY` column (excluding noise like SOURCE_SYSTEM).

Noise columns (present in every table but not real dimensions — e.g., SOURCE_SYSTEM, LOAD_TIMESTAMP, LAST_UPDATED_AT) are skipped from attribute creation entirely.

Verified on Supply Chain model (4 tables, 17 attrs, 7 base + 1 derived metrics, 16 relationships) in ~19s end-to-end.

## Relationships with shared keys need attribute-MERGE during creation, not after (OLD — see pattern above)
MSTR requires the parent attribute in a relationship to have an expression on the join (fact) table — not just the dimension table. So "Product ID" on PRODUCTS can't be the parent of a relationship joining via OPPORTUNITIES unless Product ID also has an expression on OPPORTUNITIES.

**What doesn't work:**
- Creating separate FK-side attributes per fact table ("Product ID (Opportunities)", "Product ID (Purchase Orders)") and wiring rel between them — MSTR rejects with `8004ccc7 "Table cannot be used as the join table for a relationship involving attribute"`.
- PATCHing the parent attribute post-create to append a new expression on the fact table. The PATCH validator resolves column-reference tokens against MSTR's auto-generated "managed attribute" objects in `\Managed Objects\Dataset Schema Folder\`, hitting `8004cd15 "Object (of type: Attribute) not allowed in this place"` with managed attr IDs like `C0718A20DFC74E5483270BDAB3EDE83F`.
- DELETE-then-recreate the parent attribute: MSTR errors with "cannot be deleted because other objects depend on it" once any metric/lookup references it, even mid-changeset.

**What's needed for a proper fix:**
Create shared-key attributes with multi-table expressions on the FIRST POST. When the dictionary/ERD declares `{parent: DIM.KEY, child: FACT.KEY}` with the same column name, the build should:
1. Skip creating the FK-side attribute on the fact table.
2. Create ONE parent attribute with `forms[].expressions` listing every (table, column) pair — PRODUCTS + OPPORTUNITIES + PURCHASE_ORDERS — all in one POST.
3. Use a DIFFERENT attribute (the fact table's real PK, e.g. Opportunity ID / PO Number) as the child of the relationship PUT.

This is architectural, not a post-hoc patch — needs a rewrite of `cmd_build`'s attribute-creation phase. Until then, the skill should default to `--skip-relationships` when the dictionary includes shared-key rels, and document that the relationships need to be set via Workstation UI or a follow-up skill session.

## Opening too many sessions without logout throws "Maximum interactive sessions per user"
When iterating on probes, the tenant caps at ~10 concurrent sessions. Call `DELETE /api/auth/login` between probe scripts, or reuse one long-lived session. Hard 500 until sessions time out (~10 min).
