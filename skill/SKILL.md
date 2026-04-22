---
name: build-mosaic-model
description: Build a Strategy Mosaic (MicroStrategy) semantic model from scratch against live warehouse tables. Use when the user asks to "build a mosaic model", "create a semantic model in Strategy", or provides a DB instance + schema + tables and wants a model wired up. Handles auth, warehouse-table discovery, model/table/attribute/metric creation, and relationships via the Strategy REST API.
---

# Build a Strategy Mosaic model from scratch

This skill is for **Mosaic data-model** creation and modification. If the user asks for a classic/project semantic-layer object (legacy attributes, project metrics/facts/filters, project security filters assigned to users/groups, subscriptions, users, groups, roles, VLDB, object administration), runtime analytics (reports, dashboards, documents, prompt answers, exports), AI/Agent/Bot work, or non-Mosaic cube/dataset work (Intelligent Cube, OLAP cube, Super Cube, MTDI, Push Data), route through `$REPO/strategy-automation/SKILL.md` and `memory/reference_strategy_surface_matrix.md` first. For classic-to-Mosaic mining, read `memory/reference_strategy_tutorial_semantic_field_study.md` before translating attributes/facts/metrics/filters/prompts/hierarchies into model candidates.

The user provides:
- **DB instance name** (the MicroStrategy Database Instance / datasource — looked up by name, resolved to `dbInstanceId`)
- **Schema** (aka namespace — the warehouse schema containing the tables)
- **List of table names** (may span multiple DB instances; treat each `(instance, schema, table)` triple independently)
- Optional **derived metrics**, **security filters / ACL grants or denies**, **data serve mode** (`connect_live`, `in_memory`, or tenant-supported `hybrid`), translations, certification, and publish/refresh instructions.

You produce a committed Mosaic data model containing:
- One logical table per input physical table (connected live to the source)
- Auto-generated attributes (one per ID/key/text column)
- Auto-generated fact metrics (one SUM per numeric column; user can edit aggregation later)
- Relationships inferred from shared key columns (best-effort)
- Model URL for the user to open in Library

**Destination folder / project are memorized** — see `reference_strategy_env.md` in memory.

For any endpoint uncertainty, use the instance's raw OpenAPI first:
```bash
python3 scripts/build_mosaic.py openapi-summary --out /tmp/strategy-openapi.yaml
```
The Swagger UI at `/api-docs/` is a JavaScript app; the machine-readable spec is usually `{Library}/api/openapi.yaml`.

## Execution flow

Always use the helper script `scripts/build_mosaic.py` from this skill folder. Do not re-implement the REST calls inline.

1. **Read memory first.** Confirm the env in memory (base URL, project ID, destination folder, credentials location) still matches what the user wants. If the user names a different project or folder, override via flags. Credentials must come from `MSTR_PASSWORD` or `--password`; do not write secrets into memory or this skill.
2. **Auth (handled by script).** Login → grab `X-MSTR-AuthToken`; then `POST /api/auth/identityToken` → grab `X-MSTR-IdentityToken` only for Mosaic data-model Modeling Service writes that require it. Classic/project semantic-layer workflows may fail if identity token is added; route those through the `strategy-automation` skill (`strategy-automation/SKILL.md`).
3. **Resolve DB instance.** `GET /api/datasources` (or `/api/dbobjects/databaseInstances` on older instances) — filter by name. Fail loudly if ambiguous.
4. **Discover warehouse tables.** Use the helper's `list-namespaces`, `list-tables`, and `describe-table`. On current Strategy Library servers this is `GET /api/datasources/{id}/catalog/namespaces/{namespaceId}/tables` and `GET /api/datasources/{id}/catalog/tables/{tableId}` where namespace/table IDs are base64 JSON. The script includes `discover` for live path variants and `openapi-summary` for the raw spec.
5. **Build in one changeset:**
   - `POST /api/model/changesets` (empty body) → `X-MSTR-MS-Changeset`
   - `POST /api/model/dataModels` with `{information:{name, destinationFolderId}, dataServeMode:"connect_live"}`. Use `"in_memory"` only when the user explicitly asks for an imported/cached model; use `"hybrid"` only when the tenant supports it and the user asks for it.
   - `POST /api/model/dataModels/{id}/tables` per input table. Body uses a `physicalTable` that references the warehouse table — prefer the `object` form over hand-rolled pipelines when creating fresh (no ref model to clone from):
     ```json
     {"information":{"name":"<TABLE>"},
      "physicalTable":{"type":"warehouse_partition_table",
                       "namespace":"<schema>",
                       "tableName":"<TABLE>",
                       "databaseInstance":{"objectId":"<dbInstanceId>"}}}
     ```
     Fall back to `type:"normal"` or `type:"pipeline"` if the server rejects; the TPCH reference script (see `<sibling harness dir>/build_tpch_mosaic_model.py`) shows the pipeline shape.
   - For each ID/text column → `POST .../attributes` with one key form pointing to the column, lookupTable = that table.
   - For each numeric column → `POST .../factMetrics` with `function:"sum"`, fact expression = the column.
   - `POST /api/model/changesets/{cs}/commit`.
6. **Relationships pass (second changeset).** For every column name shared between two tables, assume parent→child and create a `one_to_many` relationship via `PUT /api/model/dataModels/{id}/attributes/{childAttrId}/relationships`. Tell the user which ones were inferred and which ones to review.
7. **Print the model URL:** `{BASE}/app/library#/model/{modelId}`.

## Subtype codes (needed to filter folder listings)

- `779` = data model (object type 3)
- `3840` = logical_table
- `3072` = attribute
- `1033` = fact_metric

## Mosaic modeling concepts — what the REST API supports

The helper script auto-generates the simplest shape (single-form attributes, SUM fact metrics, inferred one-to-many rels). When the user asks for richer modeling, extend the payloads as follows — all are supported by the Modeling Service under `/api/model/dataModels/{id}/...`:

### Attribute relationships
Endpoint: `PUT /api/model/dataModels/{modelId}/attributes/{childId}/relationships?changesetId={cs}`
Body: `{"relationships":[{"parent":{"objectId","subType":"attribute"},"child":{...},"relationshipType":"one_to_many"|"many_to_many"|"one_to_one","relationshipTable":{"objectId","subType":"logical_table"}}]}`
- `relationshipTable` is the fact/bridge table where the join actually occurs.
- Compound keys → issue multiple relationship rows sharing the same child.

### Multi-form attributes (ID + DESC + any number of display forms)
Attribute body `forms[]` is a list. Each form has `{id?, category, type:"system"|"custom", displayFormat, expressions:[{expression,tables}], lookupTable, alias?}`.
- Exactly one form is marked as the **key form** via `keyForm.id` referencing the form's id. For the universal ID form the id is `45C11FA478E745FEA08D781CEA190FE5`; for display forms, omit `id` and let the server mint one.
- `displays.reportDisplays` / `displays.browseDisplays` control which forms appear by default. Set via `PATCH` post-create (see `build_tpch_mosaic_model.py` lines 340–347).
- For a Customer attribute with id + name + email: one form per column, key form = CUST_ID, display forms = CUST_NAME and EMAIL.

### Metric aggregations (single-fact)
Fact metric body:
```
{"information":{"name"}, "fact":{"dataType", "expressions":[{expression,tables}], "extensions":[], "entryLevel":[]},
 "function":"sum"|"avg"|"min"|"max"|"count"|"count_distinct"|"stdev"|"var", "functionProperties":[...],
 "dimty":{...}, "format":{"header":[],"values":[...]}}
```
- `function` drives the outer aggregate. `SUM(sales)` → `"sum"`; `AVG(discount)` → `"avg"` (see TPCH script's `METRIC_OVERRIDES` for the override pattern).
- `functionProperties` carries distinct-flag and similar modifiers.
- `format.values` is the number-format token list. TPCH script `_make_metric_format` shows currency/percent/integer templates.

### Compound metrics (derived from other metrics)
Same endpoint, but the body shifts from `fact` to a formula over existing metrics:
```
{"information":{"name":"Profit Margin"},
 "expression":{"tokens":[
    {"type":"metric_reference","value":"<Revenue metric id>"},
    {"type":"operator","value":"-"},
    {"type":"metric_reference","value":"<Cost metric id>"}]},
 "dimty":{...}, "format":{...}}
```
- No `fact` block, no `function`. The Modeling Service infers aggregation from component metrics.
- Ratio / margin / CAGR metrics all fit here.

### Conditional metrics (metric with a filter)
Layered on top of a fact or compound metric:
```
{"information":{"name":"Revenue (EMEA)"},
 "fact":{...},  "function":"sum",
 "conditionality":{"filter":{"objectId":"<filter id>","subType":"filter"},
                   "embed":true,
                   "removeAttrQualifications":false},
 ...}
```
- Filter object must exist first under `/api/model/dataModels/{id}/filters` (or be a project-level filter).
- `embed:true` inlines the filter; `false` keeps it as a reference.

### Level metrics (dimensionality override)
Controls "at what level does this metric aggregate" — e.g., "sum of order total at Customer level":
```
"dimty": {
  "dimensions":[{"objectId":"<attr id>","subType":"attribute","aggregation":"none|group_by"}],
  "filtering":"standard|absolute|ignore|none",
  "grouping":"standard|absolute|ignore|none",
  "allowAddedDimension":true
}
```
- Level metrics are the primary way to express "share of parent", "per-customer avg", etc. without writing SQL.
- To force a metric to roll up to Region regardless of report template: add the Region attribute to `dimty.dimensions` with `aggregation:"group_by"` and set `grouping:"absolute"`.

### Transformations (time-shift metrics, e.g. LY / YoY)
Separate top-level object class, created via `POST /api/model/dataModels/{id}/transformations`, then referenced by a conditional metric via `transformation:{"objectId":..., "subType":"transformation"}`.

### When you don't know the exact payload
MicroStrategy's Modeling Service accepts whatever `GET` returns. So for anything tricky:
1. Find an example of the construct in an existing project (the TPCH reference model has multi-form attributes and AVG/SUM metrics).
2. `GET /api/model/dataModels/{refModelId}/attributes/{id}` (or `/factMetrics/{id}`, `/filters/{id}`).
3. Post it back with new IDs and remapped table/object references — this is exactly the pattern `build_tpch_mosaic_model.py` uses for cloning.

## Failure modes to watch

- **Missing `X-MSTR-IdentityToken` for Mosaic data-model writes** → changeset commits can return 400. Fetch it only for the Mosaic data-model surface; classic/project workflows can require auth token + project ID without identity token.
- **Changeset commit failures** are often silent in the logs but loud in stderr text — the helper script prints full response bodies on non-2xx.
- **Ambiguous DB instance name** — there can be multiple instances with similar names across projects. Script fails closed unless user passes `--db-instance-id` directly.
- **`dataServeMode:"connect_live"`** is what matches the ref TPCH model; `"in_memory"` creates an importable/cached variant (the `-in_memory` suffix seen in `benchmark_extended_mosaic_trino.py`).
- **Publishing in-memory Mosaic models on {MSTR_BASE host}** uses `POST /api/cubes/{modelId}` with an empty body. The helper tries this before older/public publish variants.
- **Multi-source models:** the user can list tables from different DB instances. Pass instance/schema/table triples — the script groups them per instance for warehouse-table lookup, but all tables land in one model.

## Naming, descriptions, and inputs from ERDs / data dictionaries

The skill uses a three-tier fallback for every attribute + metric:
1. **Explicit override** — `--dictionary path.{json,yaml,csv}` entry for `TABLE.COLUMN`
2. **ERD relationships** — `--erd path.{json,yaml,dbml,mmd,sql}` (repeatable) supplies joins that override the shared-column inference
3. **Inference** — friendly-title-case column name; `Total <Col> (<Short Table>)` for metrics; shared-column → `one_to_many` relationship with child table as the join table

### When the user provides an ERD or dictionary
Claude should parse it (including **image ERDs** — read the PNG/JPG in-session, then write a structured list) and convert to the supported format before handing to the helper.

Supported ERD formats (parsed by `load_erd`):
- **JSON/YAML:** list of `{parent:"T.C", child:"T.C", relationship_table:"T", type:"one_to_many"}`
- **DBML:** `Ref: orders.user_id > users.id` (`>` = many-to-one; parent is the `>` target)
- **Mermaid erDiagram:** `USERS ||--o{ ORDERS : user_id`
- **SQL DDL:** any `CREATE TABLE ... REFERENCES other(col)` clause

Supported dictionary formats (parsed by `load_dictionary`):
- **JSON / YAML** with sections `attributes`, `metrics`, `relationships`, `tables`. Each `TABLE.COLUMN` entry: `{name, description, function?}`.
- **CSV** with columns `table, column, kind, name, description, function`

Config-driven builds can include the same artifacts:
```yaml
dictionary: /path/to/data_dictionary.json
erds: [/path/to/joins.dbml, /path/to/warehouse.sql]
```

If PyYAML is unavailable, the helper falls back to Ruby's YAML parser on macOS; JSON remains the most portable interchange format.

### When no ERD / dictionary is provided
- Relationships are inferred from shared column names across tables (earliest-added table = parent, others = children; `one_to_many`; relationship_table = child's table).
- Attribute names use title-cased column name, disambiguated with short table suffix if the same column exists in multiple tables.
- Metric names use `Total <Col> (<Short Table>)`.
- **Descriptions are auto-generated by Claude using domain knowledge** before the build runs. The workflow: Claude reads `describe-table` output + table names, writes a JSON dictionary with sensible descriptions (e.g. `CUSTOMER_NAME → "Full legal name of the customer account"`), saves it to a temp file, and passes it via `--dictionary`. This is the key guidance: **never ship a model with mechanical "Column X from table Y" descriptions when domain knowledge would yield something meaningful**. Only fall back to the generic template when the column name is truly opaque.

### Claude's responsibility at invocation time
Before running `build`, do the following:
1. Run `list-datasources`, `list-namespaces`, `list-tables`, `describe-table` for each table to confirm columns.
2. If the user supplied an ERD image / document, read it and convert relationships + descriptions to a dictionary JSON.
3. For every column not covered by user-provided docs, synthesize a business description from column/table semantics using domain reasoning.
4. Write `/tmp/<model>.dict.json` and pass `--dictionary` to `build`.
5. Pass any additional ERDs with `--erd`.

### If the user asks for derived metrics or access/security at build time
Build the base model first, then apply post-build operations against the returned `model_id`:
- Simple numeric measures: dictionary `metrics.TABLE.COLUMN.function` controls `sum`, `avg`, `min`, `max`, `count`, etc.
- Compound metrics over existing metrics: `create-compound-metric --model-id M --name N --formula 'METRIC_ID1 / METRIC_ID2'`.
- Tenant fallback for derived calculations: create a fact metric with an inline column formula using `character` operator tokens; this is the verified {MSTR_BASE host} pattern when compound metric references fail at commit.
- Filter-scoped metrics: create/reuse a filter first, then `create-conditional-metric`.
- Time-shift metrics: `create-transformation`, then `attach-transformation`.
- Mosaic row-level security: `--security-filter 'Name=ATTR_ID[:FORM_ID]=VALUE|memberIdOrName,...'` or `Name=@qualification.json|...`. Classic/project security filters use the legacy/admin surface, not this build flag.
- Object access: `--grant` and `--deny` use the data-model ACL endpoint for the model root during `build`; use `set-acl --model-id M --object-id O --sub-type fact_metric` for a metric/attribute/table after build.
- In-memory publish: pass `--data-serve-mode in_memory --publish`; the helper uses `POST /api/cubes/{modelId}` first.

## User, access, and legacy-object preflight helpers

Use these before applying row-level security, ACLs, user provisioning, or updates to existing schema objects:
```bash
python3 $REPO/skill/scripts/build_mosaic.py resolve-users --file users.csv
python3 $REPO/skill/scripts/build_mosaic.py create-users --file users.csv        # dry-run
python3 $REPO/skill/scripts/build_mosaic.py search-objects --name "Customer"
python3 $REPO/skill/scripts/build_mosaic.py get-model-object --kind legacy_attribute --object-id ATTR_ID --show-expression-as tokens --out /tmp/before.json
```

For existing Mosaic-contained objects use `--kind attribute|fact_metric|table|filter|security_filter --model-id MODEL_ID --object-id OBJECT_ID`. For classic schema objects use `legacy_attribute`, `legacy_metric`, `project_fact`, or `project_table`.

Only patch after the exact ID and request body have been reviewed:
```bash
python3 .../build_mosaic.py patch-model-object \
  --kind legacy_attribute --object-id ATTR_ID \
  --json-file /tmp/attribute.patch.json \
  --before-out /tmp/attribute.before.json \
  --yes
```

Modeling Service `PATCH` replaces top-level fields. Start from a current `GET`, keep every top-level field that must survive, then verify with another `GET`.

## Invocation pattern

When the user gives a prompt like:
> "Build a mosaic model. Instance: Snowflake Prod, schema: SALES, tables: CUSTOMER, ORDER, LINEITEM."

Run:
```bash
cd "$REPO"
python3 $REPO/skill/scripts/build_mosaic.py \
    --instance "Snowflake Prod" --schema SALES \
    --tables CUSTOMER ORDER LINEITEM \
    --name "Sales Mosaic"
```

For multi-source:
```bash
python3 .../build_mosaic.py \
    --source "Snowflake Prod:SALES:CUSTOMER,ORDER" \
    --source "Oracle Billing:FIN:INVOICE" \
    --name "Customer 360"
```

## Schema topology — star vs snowflake vs galaxy (how the skill reads your data)

The skill auto-detects data-design topology from the input tables using column-name patterns. No ERD needed; an ERD/dictionary only *overrides* the inference.

### Star schema (one fact, many dims, no sub-dim chains)
- Each dim table: one **entity attribute** with multi-table expressions (dim table + every fact table where its PK column appears).
- Each fact table: one entity attribute keyed on its own PK (or acronym-derived PK: `PURCHASE_ORDERS` → `PO_NUMBER`).
- Descriptor columns: single-table child attributes with `descriptor → entity` relationship on the same table.
- Cross-table: `dim_entity → fact_entity` relationship via the fact table.

### Snowflake schema (dims have sub-dims — e.g., Product → Category → Category Group)
Same entity-first pattern, but the dim chain emerges naturally:
- If `CATEGORY_ID` is the PK of `CATEGORIES` and also appears in `PRODUCTS`, the `Category` entity attribute gets expressions on both. The relationship `Category → Product` via `PRODUCTS` is created automatically.
- If `PRODUCTS` then appears in `ORDERS`, you get `Product → Order` via `ORDERS`, forming the chain `Category → Product → Order`.
- The skill walks this graph and **auto-creates a user-defined hierarchy object** (`Drill: Category > Product > Order`) for the longest chain — a first-class Mosaic object for drill-down paths.

### Galaxy / constellation (multiple facts sharing conformed dims)
- A non-PK descriptor column present in ≥2 tables (e.g., `REGION` in `SUPPLIERS` and `CUSTOMERS`, or `FISCAL_QUARTER` in every fact) is treated as a **conformed dimension** — one multi-table attribute rather than N per-table duplicates with `(Table)` suffix.
- Relationships wire from the conformed attribute to each table's entity attribute via that table.

### Noise columns (skipped entirely)
`SOURCE_SYSTEM`, `LOAD_TIMESTAMP`, `LAST_UPDATED_AT`, `INGESTION_DATE`, `LOAD_DATE`, `ETL_BATCH_ID`, `DW_CREATED_AT`, `DW_UPDATED_AT` — when present in 3+ tables, they're data-ingestion bookkeeping, not real dimensions. Add to the list via `--attr-cols` override if your org uses different conventions.

### Bridge / junction tables (many-to-many)
A table whose columns are ALL `*_ID` FKs to other tables' entities, with no descriptor columns, is a bridge. Not yet auto-wired as `many_to_many` — dictionary/ERD should declare the two sides for now.

### Overriding inference
Pass `--dictionary file.{json,yaml,csv}` with explicit relationships, or `--erd file.{dbml,mmd,sql,yaml,json}` to force specific joins. Dictionary `attributes[*]` entries also rename / re-describe any inferred attribute post-creation.

## Full Mosaic surface — what exists, and where

Mosaic (MicroStrategy) is a full metadata-backed semantic + analytics platform. When the user asks about *any* concept, locate it here, then fetch a live example via `GET` before synthesizing a new payload.

### Authentication & session
- `POST /api/auth/login` — `{username, password, loginMode}`. Modes: 1 standard, 8 LDAP, 16 SAML, 4096 Identity Token passthrough. Returns `X-MSTR-AuthToken`.
- `POST /api/auth/identityToken` — returns `X-MSTR-IdentityToken` (required for some Mosaic data-model changesets; avoid adding it to classic/project workflows unless verified).
- `POST /api/auth/delegate` — SSO delegation.
- `DELETE /api/auth/login` — logout.
- `GET /api/sessions` — session info (privileges, locale, time zone).

### Projects & environment
- `GET /api/projects` — list projects the user can see.
- `GET /api/projects/{id}/settings`, `PATCH …/settings` — project-level config (caching, governance, VLDB, data import).
- `GET /api/monitors/…` — cluster health, caches, job monitor.

### Folders, object browsing, search
- `GET /api/folders/{id}?limit=&offset=&filter[subtype]=` — list folder contents.
- `GET /api/folders/preDefined/{type}` — well-known roots (MyObjects=7, PublicObjects=8, SchemaObjects=9, etc.).
- `POST /api/searches` → `GET /api/searches/{id}/results` — metadata search (name/type/owner/date).
- `GET /api/objects/{id}?type=` — object header (name, owner, ACL, dates).
- `GET /api/objects/{id}/dependents` / `/dependencies` — lineage.

### Object type/subtype codes (know these — many endpoints filter on them)
- types: 2 filter, 3 data model ("report-level semantic layer"), 4 metric, 8 folder, 12 attribute, 15 fact, 29 report, 32 project, 34 user, 36 shortcut, 44 security filter, 55 document, 58 dashboard/dossier, 60 transformation, 65 consolidation, 68 prompt, 74 cube/intelligent cube, 776 logical table, 779 data model alias subtype.
- subtypes encode specialization: 776 normal table, 779 partition table, 780 freeform SQL, 1024 attribute, 1025 abstract attr, 1033 fact metric, 1034 compound metric, 1036 predicate metric, 1037 reference metric, 1280 consolidation, 1284 custom group, 2048 filter, 2049 filter partition, 2064 template, 2448 smart attribute, 8192 prompt, 8448 property set, 8576 schedule, 8704 link, 12288 dashboard, 12290 dossier, 14081 intelligent cube.

### Datasources (DB instances) & warehouse
- `GET /api/datasources` / `POST /api/datasources` — list / create DB instance.
- `GET /api/datasources/{id}/connections` — DBConnection + login.
- `POST /api/datasources/{id}/testConnection` — probe.
- Catalog navigation (paths vary — use `discover` subcommand):
  - Namespaces: `/api/datasources/{id}/catalog/namespaces` (or `/namespaces`)
  - Tables:     `/api/datasources/{id}/catalog/tables?namespace=`
  - Table detail: same + `/{tableName}`
- `GET /api/datasources/{id}/availableObjects` — for data import widgets.
- `POST /api/datasources/{id}/catalog/tables` — import a freeform SQL table.

### Data models (schema)
- `POST /api/model/dataModels` — new model. Body `{information:{name,destinationFolderId}, dataServeMode}`.
  - `dataServeMode`: `connect_live` (live queries to source), `in_memory` (imported / cached cube-backed model). Some tenants also support `hybrid`.
- `GET /api/model/dataModels/{id}` — full definition, including `schemaFolderId` (where all child objects live).
- `PATCH /api/model/dataModels/{id}` — rename, move, change serve mode.
- `POST /api/cubes/{id}` — {MSTR_BASE host} verified publish/materialize path for an in-memory Mosaic model. Public specs may also list `/api/dataModels/{id}/publish`; keep it as fallback, not first choice.
- `POST /api/model/dataModels/{id}/refresh` — incremental refresh of cached data.

### Changesets (unit of atomic metadata write)
- `POST /api/model/changesets` — open. Header `X-MSTR-MS-Changeset` must be sent on every subsequent write in the same batch.
- `POST /api/model/changesets/{cs}/commit` — apply.
- `DELETE /api/model/changesets/{cs}` — discard.
- Changesets can span multiple object types; split relationships/security filters into separate changesets because they reference objects that must already exist.

### Physical tables (all shapes)
Under `POST /api/model/dataModels/{id}/tables`:
- `warehouse_partition_table` — reference to a named warehouse table. Body: `{namespace, tableName, databaseInstance:{objectId}}`.
- `normal` — same as above but non-partitioned.
- `freeform_sql` — custom SQL table. Body includes `sqlStatement` + column mapping.
- `pipeline` — the clone form (see TPCH script) — carries preserved pipeline JSON.
- `partition` — logical partition over multiple physical tables.

### Attributes (all forms)
- Body fields: `information`, `forms[]`, `keyForm.id`, `attributeLookupTable`, `relationships`, `displays`, `childAttributes`, `hidden`, `hierarchyInfo`.
- Form `category`: `ID`, `DESC`, and any custom string. Form `type`: `system` (locked id like `45C11FA478E745FEA08D781CEA190FE5`) or `custom`.
- Form `displayFormat`: `text`, `number`, `date`, `picture`, `url`, `email`, `symbol`, `html_tag`.
- `displays.reportDisplays` / `displays.browseDisplays` — default form(s) shown in reports / in browse prompts.
- Compound keys: multiple forms with `category:"ID"` and `keyForm` references the compound form.
- `PATCH /api/model/dataModels/{id}/attributes/{aid}` — update.

### Facts (physical column bindings, separate from metrics)
- `POST /api/model/dataModels/{id}/facts` — create a fact (column + dataType + allowed table set).
- A fact metric's `fact` block embeds the fact expression inline; a reusable fact lets several metrics share it.

### Metrics (every kind)
Endpoint family: `/api/model/dataModels/{id}/factMetrics` (and sometimes `/metrics` for non-fact metrics).
- **Simple fact metric:** `function` + `fact.expressions[]`.
- **Functions:** `sum, avg, min, max, count, count_distinct, stdev, var, median, product, geo_mean, first, last`.
- **Smart metric / dynamic aggregation:** `functionProperties` = list of `{name:"Aggregation", value:"..."}` overrides, e.g. `smart_total`, `count_unique`.
- **Compound metric:** drop `fact`, use `expression.tokens` referencing other metric IDs via `{type:"metric_reference", value:"<mid>"}` with operators `+ - * / ()`.
- **Conditional metric:** add `conditionality.filter.objectId` + `embed` + `removeAttrQualifications`. The filter object lives in `/filters`.
- **Transformation metric:** add `transformation.objectId` (transformation must exist).
- **Level metric:** configure `dimty.dimensions[]` + `dimty.filtering`/`grouping` = `standard|absolute|ignore|none|ignore_warehouse`.
- **Pass-through / `ApplySimple` / `ApplyAgg`:** use database-specific function via `functionProperties` with `fragment:"..."`.
- **Format:** `format.values[]` token list (category/format/decimals/currency).

### Filters
- `POST /api/model/dataModels/{id}/filters`. Body: `{information, qualification:{tree:{type:"predicate_form_qualification"|"predicate_metric_qualification"|"predicate_joint_element_list"|"operator", ...}}}`.
- Predicate types: form (attribute@form operator value), metric (metric ranking / value), element list, set, joint, shortcut, embedded.
- Filters compose via `type:"operator", operator:"and|or|not", children:[...]`.

### Transformations (time-shift, prior-period, YoY)
- `POST /api/model/dataModels/{id}/transformations` — `{information, members:[{attribute, offset, mappingTable?}]}`.
- Attach to a metric via `transformation:{objectId,subType:"transformation"}` on the metric body.

### Consolidations & custom groups (virtual members / dynamic buckets)
- Consolidation: `POST /api/model/dataModels/{id}/consolidations` — enumerated elements each mapping to a filter expression (e.g., region groups).
- Custom group: `POST /api/model/dataModels/{id}/customGroups` — dynamic filter-driven buckets with banding.

### Prompts
- `POST /api/model/dataModels/{id}/prompts` — types: `attribute_element`, `attribute_qualification`, `hierarchy_qualification`, `value` (number/date/text/bigDecimal), `object`.
- Prompts are referenced inside filters, metrics, reports — enabling parameterization.

### Hierarchies (user-defined drill paths)
- `POST /api/model/dataModels/{id}/hierarchies` — `{attributes:[{id,filters,…}], relationships:[{parent,child}]}`. Separate from attribute parent-child relationships.

### Intelligent cubes (in-memory OLAP, backs `in_memory` models)
- `POST /api/cubes/{id}` publishes/materializes an in-memory Mosaic model on {MSTR_BASE host}.
- `POST /api/cubes`, `POST /api/cubes/{id}/instances`, `POST /api/cubes/{id}/publish`, `POST /api/cubes/{id}/refresh?refreshType=update|add|replace|incremental` exist for cube workflows, but `/instances` requires an already-published cube.
- Incremental refresh filter: `PATCH /api/cubes/{id}` with `incrementalRefresh.filterId`.

### Security & governance
- Mosaic data-model security filters: `POST /api/model/dataModels/{id}/securityFilters` — row-level security owned by a Mosaic data model. Assign members with `PATCH /api/dataModels/{id}/securityFilters/{sfId}/members` using `{operationList:[{op:"addElements",path:"/Members",value:[ids...]}]}`; the helper has an older POST fallback.
- Classic/project security filters: do **not** use the Mosaic data-model endpoint. Use top-level `/api/model/securityFilters` to create/read the project security-filter object and `/api/securityFilters/{id}/members` to assign users/groups. See `memory/reference_strategy_legacy_semantic_admin.md`.
- `GET/POST /api/users`, `/api/usergroups`, `/api/users/{id}/privileges`, `/api/users/{id}/securityRoles`.
- Data-model object ACL: `PATCH /api/model/dataModels/{modelId}/objects/{objectId}/acl?subType=<objectSubType>` with `{acl:{trusteeId:{granted,denied,subType:"user"|"user_group"}}}` inside a changeset.
- Data-model object translations: `PATCH /api/model/dataModels/{modelId}/objects/{objectId}/translations?subType=<objectSubType>`.
- Certified content: `PATCH /api/objects/{id}` with `certifiedInfo:{certified:true, date, user}`.

### Reports, dashboards, dossiers, documents
- `POST /api/reports`, `POST /api/dashboards`, `POST /api/dossiers`, `POST /api/documents`.
- Execute a report: `POST /api/reports/{id}/instances` then `GET /api/reports/{id}/instances/{instId}`.
- Dashboard export: `POST /api/documents/{id}/instances/pdf`.

### Subscriptions & distribution
- `POST /api/subscriptions` — delivery types: email, file, print, history list, cache update, mobile.
- `GET /api/schedules` — list schedules.

### VLDB properties (SQL generation behavior)
- `GET/PATCH /api/objects/{id}/vldbProperties?type=` — per-metric, per-table, per-report overrides controlling SQL generation (join types, GROUP BY strategy, count behavior, etc.).

### Mosaic MCP server (this tenant)
Connected as `<mosaic MCP server>`:
- `get_projects` — project list.
- `get_mosaic_models` — list of models in a project.
- `get_semantics` — attributes + metrics of a model (shape matches what the benchmark scripts embed in system prompts).
- `query` — Trino SQL against the published model (takes `schema` + `query`).

### Trino federation layer
Live models are queryable as Trino tables — `host={MSTR_BASE host}:443`, `catalog=sql`, `schema="{your project name lowercased}"`, basic-auth with the same MSTR creds. Every Mosaic model becomes one Trino "table" whose columns are the model's attributes + metrics (lowercase, quoted). In-memory variants appear with a `-in_memory` suffix.

### Clone-and-remap pattern (when payload shape is unknown)
1. Find a reference object (same kind, already working) via folder browse.
2. `GET` it to capture the exact JSON shape.
3. Generate fresh UUIDs for every inner `id`.
4. Remap every `objectId` that points at a table/attribute/metric you've replaced using a `{old_id → new_id}` dict.
5. `POST` it.

`build_tpch_mosaic_model.py` is the canonical example.

## Before trusting any endpoint path in this skill

MicroStrategy REST paths drift between versions. When a call 404s, first run `openapi-summary` to fetch `{Library}/api/openapi.yaml`, then run `discover` for live catalog variants (`/api/datasources` vs `/api/dbobjects/databaseInstances`, `/catalog/tables` vs `/tables` vs `/namespaces/{ns}/tables`). Adjust the constants at the top of the script and update memory with the tenant-specific finding.
