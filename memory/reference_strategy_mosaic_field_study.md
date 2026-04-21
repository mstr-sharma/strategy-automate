---
name: Strategy Mosaic field study + legacy bridge
description: Live REST inventory of Mosaic data models on {MSTR_BASE host} ({MSTR_PROJECT_NAME} project) plus the object-by-object bridge from classic/project semantic-layer concepts to Mosaic equivalents.
type: reference
---
Use this when the user asks to inspect, clone, translate, or convert between legacy (classic project) semantic-layer objects and Mosaic data models. Pair with `reference_strategy_tutorial_semantic_field_study.md` (classic) and `reference_strategy_legacy_to_mosaic_mining.md` (discovery helper).

Grounded in a live REST sweep on 2026-04-21 against `{MSTR_BASE host}` / project `{MSTR_PROJECT_NAME}` (id `{MSTR_PROJECT_ID}`). Raw inventory at `/tmp/strategy-mosaic-inventory-full.json`; do not commit raw tenant payloads. Regenerate with:

```bash
cd $REPO
MSTR_PASSWORD=... /usr/bin/python3 skill/scripts/strategy_mosaic_inventory.py \
  --workers 12 --out /tmp/strategy-mosaic-inventory-full.json
```

Anaconda's OpenSSL hangs on `{MSTR_BASE host}` TLS; use `/usr/bin/python3`.

## Discovery

- Mosaic data models surface in classic search as **type `3` (report), subType `779` (data_model)**. List via `/api/searches/results?type=3&pattern=4&limit=200&getAncestors=true` and filter `subtype==779`.
- MCP MCP `get_mosaic_models` returned 133 in {MSTR_PROJECT_NAME}; REST search returned **156** (the extra 23 include legacy Hyper / MTDI datasets that still carry subType 779 but have no modern `dataServeMode`). Prefer REST when counts need to match metadata truth; MCP is the published-catalog view.
- One data model (`2E5BC134AF423523BAF8C2A628980B86`) returned `8004e457 "Given object is not a Mosaic model"` on every `/api/model/dataModels/{id}/*` endpoint despite searching as subType 779 — a real anomaly to expect.
- 117/156 `GET /api/model/dataModels/{id}/securityFilters` calls returned `8004c738 "User does not have Control access"` — that's the normal response when the session user did not author the filter. Only the owner can list per-model security filters.

## Mosaic sub-resource map (used by the inventory helper)

All inside `/api/model/dataModels/{dataModelId}`:

- `` — model definition (`information`, `dataServeMode`, `schemaFolderId`)
- `/tables` — **stub** list (`information.{objectId,name,subType:"logical_table"}`); 2nd pass `/tables/{tid}` for `physicalTable.{type, namespace, tableName, databaseInstance, columns, preStatement, postStatement, sqlStatement}`
- `/attributes?showExpressionAs=tree` — full body with `forms[]`, `keyForm`, `displays`, `attributeLookupTable`, `relationships[]`, `sortBy`, `smartAttribute`
- `/factMetrics?showExpressionAs=tree` — auto-derived metrics (one per fact column); default expression is `Sum(column)`, level set to the table's entry level
- `/metrics?showExpressionAs=tree` — user-authored custom metrics (compound/conditional/level/transformation in classic terms, but here represented as one expression tree)
- `/hierarchy` — single per-model relationship graph (`relationships[]` + `attributes[]`)
- `/securityFilters?showFilterTokens=true` — Mosaic model-scoped filters (different from classic project security filters)
- `/externalDataModels` — cross-model references (model-to-model composition)
- `/folders` — internal schema folders
- `/objects/{objectId}/acl?subType=...` — object ACL inside a changeset
- `/objects/{objectId}/translations?subType=...` — translations inside a changeset
- `/links` — **requires `X-MSTR-MS-Changeset` even for GET** on {MSTR_BASE host}; skip for read-only inventory

## Portfolio observations ({MSTR_PROJECT_NAME}, 156 models)

- **Totals:** 3309 attributes, 1419 fact metrics, 168 custom metrics, 585 physical tables, 1 readable security filter (117 privilege-denied), 23 external-data-model links, 168 folders, 2693 hierarchy relationships.
- **`dataServeMode` distribution:** 119 `in_memory`, 22 `connect_live`, 15 blank (legacy Hyper/MTDI datasets: Finanzas, Trimble Hyper, Customer Hyper, Agents Hyper, HomeDepot Sample Retail Data, Penguin Tenant/Cluster Hyper Dataset, etc.).
- **Physical tables:** 585/585 are `physicalTable.type = "pipeline"`. Studio uses pipeline (build-from-cube) pattern universally — even `connect_live` models. `warehouse_partition_table` is the documented live shape but is not in active use; `freeform_sql` likewise unused here.
- **Attribute forms:** 3085 system + 415 custom. Custom forms are almost always extra descriptive columns (e.g., `MANAGER_NAME`, `PRODUCT_NAME`, `region_name`) with category `"<Attr> None"` rather than `DESC`. Expressions stay simple (single-column `ApplySimple`-equivalent); complex `Concat`/`ApplySimple(...)` expressions found in classic Tutorial are rare here.
- **Relationships:** 1830 `one_to_many` + 1 `many_to_many`; **zero `one_to_one`**. Mosaic auto-inference defaults every parent/child edge to one-to-many unless the user explicitly sets it. Classic Tutorial had 58/14/1 across the three types — translation from classic must preserve one-to-one edges deliberately.
- **Metric shapes:** 1517/1587 carry `dimty|dimensionality|levels` (every Mosaic metric ships with a level since facts have entry levels). 98 are conditional. **Zero** `compound`, `transformation`, or `smartMetric`. Every advanced metric shape is expressed as an inline expression tree rather than object composition.
- **External data models:** 12 models reference others (BREAD Comprehensive Analysis Suite references 5+ models; Unified Supplier Model, TB Integrated Asset Health, Cardmember Rewards Model, etc.).

## Attribute anatomy (Mosaic body → classic equivalent)

Mosaic `GET /api/model/dataModels/{mid}/attributes/{aid}?showExpressionAs=tree` returns the **same JSON shape** as classic `GET /api/model/attributes/{aid}?showExpressionAs=tree`. Fields:

- `information.{objectId, subType:"attribute", name, dateCreated, dateModified, acg}` — identical semantics.
- `forms[] = { id, name:"", category:"ID"|"DESC"|"<Custom Label>", type:"system"|"custom", displayFormat, expressions[].{text,tree}, lookupTable, autoMapping }` — in Mosaic, `forms[].name` is frequently empty; identify forms by `category`. Mosaic system forms (`45C11FA478E745FEA08D781CEA190FE5` ID / `516CE79B9CD24BCC85859A495CE5A5C5` DESC) still use the universal UUIDs from classic.
- `keyForm` — same semantics.
- `displays.{reportTextList, browseTextList}` — same.
- `attributeLookupTable` — in Mosaic always points at the pipeline-materialized table; in classic it points at the warehouse lookup table.
- `relationships[] = { parent:{objectId,name,subType}, child:{...}, relationshipType:"one_to_many"|"one_to_one"|"many_to_many", relationshipTable:{objectId,name} }` — same tuple shape; see note above about auto-inference bias.

**Translation rule:** classic attribute bodies can be cloned into a Mosaic model with only container remapping (model id substitution) IF the lookup tables already exist as physical tables in the target Mosaic model. Custom forms with `ApplySimple(...)` or `Concat(...)` expressions port directly.

## Metric anatomy (Mosaic body → classic equivalent)

`GET /api/model/dataModels/{mid}/factMetrics/{fmid}` and `.../metrics/{mid}` both return the classic metric body shape. Observed expression kinds:

- **Simple aggregate** (dominant): `Sum({Extended Price})`, `Avg({Wait Time Minutes})`. `expression.tree.type = "object_reference"` wrapping a fact/metric ref with a function.
- **Compound expression** (inlined): `Sum({Loans Approved}) / NullToZero(Sum({Applications Submitted}))`. `expression.tree.type = "operator"`, `functions` contain `divide, null_to_zero, sum`.
- **Transformation-style** (inlined, not a separate transformation object): `PreviousYear({Transaction Date}({Transaction Date}),1,{Expense Amount})` and `(Sum({Expense Amount}) - PreviousYear(...)) / PreviousYear(...)` — these would be separate transformation objects in classic but are expressed as function calls in Mosaic.
- **Level/conditional metadata** carried alongside the expression; no separate `conditionality` object in the live bodies we read, but `hasConditionality` keys appear on 98/1587.
- **Subtotals / thresholds / smart totals / format** keys all present in the body schema even though this tenant doesn't populate them heavily.

**Translation rules:**

- Classic **compound metric** (`Sum(A) / Sum(B)`) → Mosaic custom metric with same expression text; no changeset/transformation-object gymnastics needed.
- Classic **conditional metric** (metric + filter qualification) → Mosaic custom metric with `condition` block inside the expression tree; wrap the original metric expression and add the filter reference.
- Classic **level metric** (metric with attribute dim list) → Mosaic metric; `levels` or `dimty` field carries the attribute list at the data-model scope (objects referenced by `objectId` within the same model).
- Classic **transformation metric** (e.g., Last Year Sales via transformation object `Last Year`) → **inline the transformation** into a function call: `PreviousYear({Order Date}({Order Date}), 1, {Sales})`. The transformation table is not a first-class object in Mosaic; replicate its semantics inside expression trees.
- Classic **fact-derived simple metric** (`Sum(FACT)`) → Mosaic creates this automatically as a **factMetric** when the fact column is added to a table. Do not re-create.
- Classic **smart metric / compound fact** → expand into explicit operator tree; Mosaic has no `smartMetric` flag in observed data.

## Fact and fact-extension translation

Classic has a first-class `fact` object (`type 13`, `/api/model/facts/{id}`) with `expressions[]`, `tableMappings[]`, `entryLevel[]`, and **fact extensions** (many-to-many joins to push a fact through a bridge).

Mosaic has **no direct fact endpoint**. Facts are implicit:

- Every warehouse column in a Mosaic model table becomes a candidate fact column; adding it to a `factMetrics` definition promotes it.
- Multi-expression facts (`ApplySimple("CASE WHEN ... THEN A ELSE B END", A, B)`) must be pushed to either a database view / pipeline transformation **or** expressed as a custom metric.
- **Fact extensions** (bridge-table joins so a fact rolls up through an extra dimension) must be modeled as explicit relationships in the Mosaic hierarchy, not as a separate extension object. If the bridge is many-to-many, the relationship must be set to `many_to_many` (and pruned in auto-inference, which defaults to one-to-many).

## Hierarchy / relationships translation

Classic: two layers — `GET /api/model/systemHierarchy` (global) and `GET /api/model/hierarchies/{id}` (user drill hierarchies).

Mosaic: **one layer** — `GET /api/model/dataModels/{mid}/hierarchy` returns all relationships in the model plus the attribute set. User drill hierarchies are not first-class; drill behavior is inferred from relationships and form displays.

**Translation rules:**

- Project system-hierarchy relationships inside a Mosaic model become model-hierarchy relationships; `parent/child/relationshipType/relationshipTable` tuple is preserved.
- Classic **user hierarchies** (e.g., `Geography`, `Products`) do not port as-is; the attribute set becomes part of the Mosaic model, and drill paths are lost. Reconstruct in client apps / dashboards, not in the model.
- Auto-inference bias: Mosaic marks almost everything as `one_to_many`. If the classic relationship is `one_to_one` or `many_to_many`, set it explicitly after import — the Studio portfolio shows this is currently under-modeled.

## Filter, prompt, consolidation, custom group translation

- **Project filter objects** (`type 1`): no direct Mosaic container. Convert to either a security filter on the Mosaic model or a runtime filter at report/dashboard time. Custom-group filters (classic subtype 257) must be rebuilt as consolidations or logical metric conditions.
- **Prompts** (`type 10`): no Mosaic endpoint exists. Prompts are runtime concerns; migrate their semantics into runtime filters, agent questions, or dashboard-level inputs.
- **Security filters**: classic `/api/model/securityFilters/{id}` + `/members` is project-scoped; Mosaic `/api/model/dataModels/{mid}/securityFilters/{sfid}` + `/members` is model-scoped. Expression/qualification JSON is the same shape. Reassign membership per target model.
- **Consolidations / custom groups**: not visible in Mosaic. Express as compound metrics with `case_when` / nested operator expressions, or as model-level filters.

## Governance translation

- **ACL**: classic `GET/PUT /api/objects/{id}/acl?type=...` is global; Mosaic-contained objects **must** use `PATCH /api/model/dataModels/{mid}/objects/{oid}/acl?subType=...` inside a changeset. Rights mask is the same (read=1, write=2, delete=4, control=32, execute=128, browse=64, use=512, inherit=1024).
- **Translations**: classic `/api/objects/{type}/{id}/translations` vs Mosaic `/api/model/dataModels/{mid}/objects/{oid}/translations?subType=...` inside a changeset. Same `name.translationValues` + `description.translationValues` shape keyed by locale.
- **Certification**: `PATCH /api/objects/{id}` `{certifiedInfo:{certified:true}}` works on both legacy objects and Mosaic-contained objects; the Mosaic model itself is certified through this same global endpoint using its model id.
- **VLDB**: `GET/PATCH /api/objects/{id}/vldbProperties?type=...` still the path; for Mosaic, pass the model id. Model-scoped VLDB overrides live at data-model level, not per-metric.

## Storage / runtime translation

- **In-memory Mosaic models** back onto the Intelligent Cube family — `POST /api/cubes/{id}/publish` (or studio-verified `POST /api/cubes/{id}`) publishes; `POST /api/cubes/{id}/refresh?refreshType=update|add|replace|incremental` refreshes. Incremental filter set via `PATCH /api/cubes/{id}` `incrementalRefresh.filterId`.
- **Connect-live Mosaic models** skip cube storage but still require a `pipeline` table shape on this tenant. Direct `warehouse_partition_table` wiring is documented in `reference_mosaic_rest_api.md` but not in production use here.
- **Hyper / MTDI Super Cubes** that now appear as subType 779 (`dataServeMode == ""`): treat as read-only. Do not attempt changeset writes; they need an explicit upgrade path that isn't covered by `/api/model/dataModels` writes.

## Things that do NOT cleanly cross the bridge

- Classic **agent/template** attributes (`subtype 3072/1024`) and **system/transformation** attributes — already flagged in classic field study as `/api/model/attributes/{id}` failures; they are not Mosaic candidates.
- Classic **prompts** — no Mosaic counterpart; migrate to runtime or agent UX.
- Classic **custom groups / consolidations** — recreate as expression-level logic.
- Classic **drill hierarchies (user hierarchies)** — the attribute set ports; the drill definition is lost.
- Classic **dynamic/unmapped metrics** tied to transformation objects without expression equivalents — audit manually.
- Legacy **Hyper datasets** surfaced as subType 779 — don't treat as Mosaic-writable until re-authored.

## Helper usage cheat-sheet

```bash
# Full sweep (writes /tmp/strategy-mosaic-inventory-<stamp>.json)
MSTR_PASSWORD=... /usr/bin/python3 skill/scripts/strategy_mosaic_inventory.py --workers 12

# Narrow by name fragment for iterative analysis
MSTR_PASSWORD=... /usr/bin/python3 skill/scripts/strategy_mosaic_inventory.py \
  --model-name "BREAD" --out /tmp/mosaic-bread.json

# Single known model
MSTR_PASSWORD=... /usr/bin/python3 skill/scripts/strategy_mosaic_inventory.py \
  --model-name "snowflake tpch_sf1 test" --max-models 1
```

Output fields per model: `counts`, `dataServeMode`, `attributes[]` (forms, relationships, tables), `factMetrics[]`, `customMetrics[]` (with `expressionText`, `expressionKind`, `functions`), `tables[]` (physicalType/columnCount), `hierarchy` (relationshipCount + types), `securityFilters[]`, `externalDataModels[]`, `subresourceStatuses` (ok + error per endpoint).

Portfolio-level rollups: `physicalTableTypes`, `attributeFormTypes`, `metricFamilyFlagCounts`, `hierarchyRelationshipTypes`, `securityFilterQualificationTypes`.
