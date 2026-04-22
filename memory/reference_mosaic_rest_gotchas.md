---
name: Mosaic REST API payload gotchas
description: Exact payload shapes and ordering rules for creating Mosaic models / tables / attributes / metrics via REST — things the OpenAPI spec does not make obvious.
type: reference
---

Verified against a Strategy ONE Library Modeling Service in 2026. These rules came out of a real build of a product-hierarchy model on a Snowflake-backed datasource; the shapes are tenant-agnostic.

## Model creation
- `POST /api/model/dataModels` body **must** use `"subType":"report_emma_cube"` in `information`. `logical_table` is rejected with `Invalid subtype DssSubTypeTable. Expected subtype: DssSubTypeReportEmmaCube`.
- `destinationFolderId` is required; the caller must have Write access. `Subject Areas` is read-only for non-admins — fall back to `My Objects` (`GET /api/folders/myPersonalObjects` → `"My Objects"`).
- Model-scoped default folder IDs vary per tenant. Never hardcode. Always resolve from `/api/folders/preDefined/{type}` or `/api/folders/myPersonalObjects` for the current session's project.

## Physical tables
- `POST /api/model/dataModels/{id}/tables`: the accepted shape on current Library servers is `physicalTable.type: "pipeline"` with a `pipeline` field containing a **stringified JSON** describing `rootTable → source → importSource`. `warehouse_partition_table` is rejected with `Invalid value for field 'type'`. A bare `normal` type rejects the `databaseInstance` field (`Unrecognized field: databaseInstance`).
- The pipeline JSON shape that works (see `scripts/build_mosaic.py` L694–L722):
  ```json
  {
    "id": "<uuid>",
    "rootTable": {
      "id": "<uuid>", "type": "root",
      "children": [{
        "id": "<uuid>", "name": "<TABLE>", "type": "source",
        "columns": [{ "id":"<uuid>", "name":"COL", "dataType":{...}, "sourceDataType":{...} }, ...],
        "importSource": { "type":"single_table", "dataSourceId":"<dbInstanceId>", "namespace":"<schema>", "tableName":"<TABLE>", "sql":"" }
      }]
    }
  }
  ```
- The outer `physicalTable.columns` list is a separate flat array with `{information:{name}, dataType, columnName}` — both the outer and the inner pipeline `columns` must be present.

## Column objectIds (the #1 trap)
- After `POST .../tables`, column objectIds are **visible inside the changeset** but are **ephemeral until commit**. A subsequent attribute/metric that references those IDs in the same uncommitted changeset will fail at commit with `Object with ID '...' and type 26 (Column) is not found in metadata`.
- Safe ordering: **commit tables first**, then re-`GET /api/model/dataModels/{mid}/tables/{tid}?showColumns=true` to capture the post-commit column objectIds, then open a new changeset for attributes/metrics.
- Exception to ordering: Mosaic will reject commit of a changeset that contains only tables with `Mosaic model cannot be saved because it is empty` and `table doesn't have any metric or attribute`. Workaround: include at least one attribute **or** fact metric referencing each table in the same changeset that creates the table. The simplest version is a single throwaway attribute or a per-table fact metric per new table. Tables committed by the auto-builder script (`build_mosaic.py build`) satisfy this automatically because attributes/metrics are created in the same changeset.

## Attributes (multi-form)
- `POST /api/model/dataModels/{id}/attributes` body shape:
  ```json
  {
    "information": {"name","description","subType":"attribute"},
    "forms": [
      { "id":"45C11FA478E745FEA08D781CEA190FE5", "category":"ID", "type":"system", "displayFormat":"number",
        "dataType": {...},
        "expressions": [{"expression":{"text","tokens":[<column_reference>, <eot>]}, "tables":[<logical_table refs>]}],
        "alias":"COL", "lookupTable": {...} },
      ... custom forms ...
    ],
    "keyForm": {"id":"45C11FA478E745FEA08D781CEA190FE5"},
    "attributeLookupTable": {"objectId","subType":"logical_table","name"},
    "displays": {"reportDisplays":[{"id","name"}], "browseDisplays":[...]}
  }
  ```
- The ID form's constant `objectId` `45C11FA478E745FEA08D781CEA190FE5` is a platform-wide key form id (safe to reuse across tenants).
- An ID form whose expression tables include multiple logical tables (`LU_CATEGORY` AND `LU_SUBCATEG`) is **how you tell Mosaic two tables share that attribute**. Without this, there is no join path and queries cartesian.
- **Multi-table ID expressions — the non-obvious shape.** In legacy semantic-layer JSON, a single `expressions[0]` entry lists all tables in `tables[]` and its tokens reference one project-level column objectId. **This does NOT work in Mosaic.** Mosaic validates column objectIds per physical table and each table has its own. Submit **one expression entry per `(table, column)` pair** inside the `expressions[]` array — each with its own `tables:[one_table]` and its own tokens pointing at that table's column objectId. Without this split, you get either `Table X doesn't have the columns: Y` at attribute creation, or `Table cannot be used as the join table for a relationship involving attribute` at relationship creation.
- For relationships: the parent attribute's `expressions[]` must include the `relationshipTable` — i.e., `Category → Subcategory via LU_SUBCATEG` requires Category to have an expression entry with `tables:[LU_SUBCATEG]` referencing that table's `CATEGORY_ID` column object.
- The `expression.tokens` array must end with `{"type":"end_of_text","value":""}` or Modeling Service rejects it with `The tree or token is required for expression` (a misleading error — the real issue is missing EOT).

## Fact metrics (custom formulas)
- `POST /api/model/dataModels/{id}/factMetrics` with `text`-only expression is rejected. Provide tokens:
  ```json
  "expressions": [{"expression":{
     "text":"QTY_SOLD * (UNIT_PRICE - DISCOUNT)",
     "tokens":[
       {"type":"column_reference","value":"QTY_SOLD","target":{"objectId":"<col id>","subType":"column","name":"QTY_SOLD"}},
       {"type":"character","value":"*"},
       {"type":"character","value":"("},
       {"type":"column_reference","value":"UNIT_PRICE","target":{"objectId":"<col id>","subType":"column","name":"UNIT_PRICE"}},
       {"type":"character","value":"-"},
       {"type":"column_reference","value":"DISCOUNT","target":{"objectId":"<col id>","subType":"column","name":"DISCOUNT"}},
       {"type":"character","value":")"},
       {"type":"end_of_text","value":""}
     ]
  }, "tables":[{"objectId":"<od logical table id>","subType":"logical_table","name":"ORDER_DETAIL"}]}]
  ```
- Operators (`* + - / ( )`) are `character` tokens. Functions (`Sum`, `Concat`, `ApplySimple`) are `function` tokens with `target.subType:"function"` and the well-known function objectId. Use `showExpressionAs=tokens` on a working metric to see the exact shape before inventing one.

## Relationships
- `PUT /api/model/dataModels/{id}/attributes/{childId}/relationships?changesetId=<cs>` (or via header `X-MSTR-MS-Changeset`). Body is the full list, not a delta.
- Must be a separate changeset from attribute creation. Attributes need to be committed first; otherwise the relationship references objects the server hasn't materialized yet.
- `relationshipTable` is the fact/bridge table where the join actually occurs (for 1:M, the child's lookup table; for M:M, the bridge table).
- **PUT is a wholesale REPLACE of the child's relationship list, not an append.** Calling PUT multiple times against the same child attribute (e.g., once per parent) within a single changeset wipes every previous PUT — only the last one survives. Every call returns `200` so the bug is silent. **Always consolidate all parents for a given child into ONE PUT call** with `relationships:[rel1, rel2, ...]`. This is the single most common silent-failure in Mosaic relationship wiring — observed on Item with 5 parents where all 5 POSTs returned 200 but only Warranty→Item persisted. Pattern: build a `per_child: dict[childId, list[relationship_body]]` map first, then one PUT per key.

## Login modes per tenant (observed)
| Tenant | Working modes | Notes |
|---|---|---|
| Example SAML-backed demo tenant | 16 (SAML) | Modes 1 and 8 rejected |
| Example standard-auth tenant | 1 (standard) | Mode 8 (LDAP) returns `INVALID_AUTH_MODE` |

Always tell the helper which mode per tenant via `MSTR_LOGIN_MODE`. Different users on the same tenant may have different SSO configs — test before assuming. The initial `/api/auth/login` call succeeds even when the user has no access to the target project, so a successful login is not proof of a working project session. Always validate by calling a project-scoped endpoint.

## DB instance + schema discovery
- `list-datasources` lists every DB instance visible to the session, not the project.
- `list-namespaces --instance-id X` can return 500 `Database error connection. Please try again` when the instance is orphaned or its credentials have rotated. Surface the full error; do not silently retry.
- Warehouse schema names must be passed exactly as the datasource returns them (often uppercase). Trino federation schema naming is different from the MSTR project name — Trino schemas are typically lowercased with spaces preserved and require double-quoting in SQL (e.g., a project named `Shared Studio` becomes `"shared studio"` in Trino).

## Trino federation naming
- Column names from the Trino side differ from Mosaic REST. Descriptor attributes appear as `"<name> (<id form name> id)"` (e.g., `"category name (category desc id)"`). Check `get_semantics` output first; never guess column names from the UI.
- Category hierarchy + fact joins fail with `A cartesian join is detected` until the bridging entity attribute (Subcategory on both `LU_SUBCATEG` and `LU_ITEM`) exists AND the relationships are wired. Both are required.

## Delete
- `DELETE /api/model/dataModels/{id}` returns `HTTP 204` on success, `HTTP 404` if already deleted. Treat 404 as idempotent success when cleaning up mid-script orphans.

## Session cap
- Studio tenant enforces a per-user per-project interactive session cap. Symptom is `500 (Maximum number of interactive session per user for project exceeded while trying to login user … to project …)` on any API call that attempts a fresh session.
- Every helper script creates a new session on login; long iterative debug loops exhaust the pool fast.
- **Always call `m.logout()` (which sends `DELETE /api/auth/login`) at the end of a script run.** Wrap the session in try/finally so exceptions still release it.
- If you hit the cap, wait 5–10 min for idle sessions to expire, or have an admin terminate them via `/api/sessions`. Do not paper over with retries.
