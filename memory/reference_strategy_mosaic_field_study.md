---
name: mosaic-portfolio-inventory-rules
description: Mosaic portfolio inventory rules + legacy↔Mosaic translation — subType-779 + extType-448 REST discovery, the MCP-shows-certified-only rule, the Mosaic sub-resource map, and the object-by-object classic→Mosaic translation matrix. Load when inspecting, cloning, translating, or converting between classic semantic objects and Mosaic data models.
type: reference
---
Use this when the user asks to inspect, clone, translate, or convert between legacy (classic project) semantic-layer objects and Mosaic data models. Pair with `reference_strategy_tutorial_semantic_field_study.md` (classic) and `reference_strategy_legacy_to_mosaic_mining.md` (discovery helper).

Rules here are durable, grounded in a live REST portfolio sweep. The dated single-tenant snapshot (portfolio totals, distributions, permission stats, tenant dataset/model names, the anomalous model id) lives in `captures/2026-04-21-mosaic-portfolio-field-study/README.md`. Raw inventory output stays in `/tmp`; do not commit raw tenant payloads. Regenerate with:

```bash
cd $REPO
MSTR_PASSWORD=... /usr/bin/python3 skills/build-mosaic-model/scripts/strategy_mosaic_inventory.py \
  --workers 12 --out /tmp/strategy-mosaic-inventory-full.json
```

Anaconda's OpenSSL hangs on `{MSTR_BASE host}` TLS; use `/usr/bin/python3`.

## Discovery

- Mosaic data models surface in classic search as **type `3` (report), subType `779` (`report_emma_cube`) with extType 448**. List via `/api/searches/results?type=3&pattern=4&limit=200&getAncestors=true` and filter `subtype==779` **and** `extType==448` — data-import (MTDI) cubes share subtype 779 (corrected 2026-10-05; mstrio-py's `list_mosaic_models` uses the same subtype + extType pair).
- **MCP shows certified models only (not merely published; corrected 2026-10-05); prefer REST for metadata truth.** In the verified sweep, MCP `get_mosaic_models` (now `get_models`) returned 133 models where REST search returned **156** — the extra 23 were legacy Hyper / MTDI datasets that still carry subType 779 but have no modern `dataServeMode`. Prefer REST when counts need to match metadata truth; MCP is the certified-catalog view.
- Expect the occasional anomaly: a model can search as subType 779 yet return `8004e457 "Given object is not a Mosaic model"` on every `/api/model/dataModels/{id}/*` endpoint (one such model in the verified sweep; concrete id in the capture). Verify with a sub-resource probe before treating a search hit as writable.
- `GET /api/model/dataModels/{id}/securityFilters` returns `8004c738 "User does not have Control access"` whenever the session user did not author the filter — only the owner can list per-model security filters. This is the normal response for the large majority of models when sweeping a tenant (exact stat in the capture); filter these out of inventory rather than treating them as failures.

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

## Durable portfolio patterns (dated stats in `captures/2026-04-21-mosaic-portfolio-field-study/`)

- **`dataServeMode` takes three values in practice:** `in_memory`, `connect_live`, and blank. Blank means a legacy Hyper/MTDI Super Cube surfaced as subType 779 — treat as read-only (see Storage / runtime translation below).
- **Pipeline tables are universal.** Every physical table observed was `physicalTable.type = "pipeline"` — Studio uses the pipeline (build-from-cube) pattern even for `connect_live` models. `warehouse_partition_table` is the documented live shape but was not in active use; `freeform_sql` likewise unused.
- **Custom attribute forms** are almost always extra descriptive columns with category `"<Attr> None"` rather than `DESC`, and `forms[].name` is frequently empty — identify forms by `category`. Expressions stay simple (single-column); complex `Concat`/`ApplySimple(...)` expressions found in classic Tutorial are rare in Mosaic-authored models.
- **Relationship auto-inference bias:** Mosaic defaults every parent/child edge to `one_to_many` unless the user explicitly sets it — the verified portfolio had zero `one_to_one` edges, while classic Tutorial mixes 58 one-to-many / 14 one-to-one / 1 many-to-many. Translation from classic must preserve one-to-one and many-to-many edges deliberately.
- **Metric shapes:** virtually every Mosaic metric carries `dimty|dimensionality|levels` (facts have entry levels, so every metric ships with a level); a minority are conditional (`hasConditionality`). **Zero** `compound`, `transformation`, or `smartMetric` objects — every advanced metric shape is expressed as an inline expression tree rather than object composition.
- **External data models** (model-to-model composition) are in real production use; some models reference 5+ others.

## Attribute anatomy (Mosaic body → classic equivalent)

Mosaic `GET /api/model/dataModels/{mid}/attributes/{aid}?showExpressionAs=tree` returns the **same JSON shape** as classic `GET /api/model/attributes/{aid}?showExpressionAs=tree`. Fields:

- `information.{objectId, subType:"attribute", name, dateCreated, dateModified, acg}` — identical semantics.
- `forms[] = { id, name:"", category:"ID"|"DESC"|"<Custom Label>", type:"system"|"custom", displayFormat, expressions[].{text,tree}, lookupTable, autoMapping }` — in Mosaic, `forms[].name` is frequently empty; identify forms by `category`. Mosaic system forms (`45C11FA478E745FEA08D781CEA190FE5` ID / `CCFBE2A5EADB4F50941FB879CCF1721C` DESC) still use the universal UUIDs from classic. (Corrected 2026-10-05: the DESC GUID was recorded as `516CE79B…`; the REST docs' attribute samples use `CCFBE2A5…`.)
- `keyForm` — same semantics.
- `displays.{reportDisplays, browseDisplays}` — same (each a list of `{id, name}` form refs; earlier text said `reportTextList` / `browseTextList` — corrected 2026-10-05).
- `attributeLookupTable` — in Mosaic always points at the pipeline-materialized table; in classic it points at the warehouse lookup table.
- `relationships[] = { parent:{objectId,name,subType}, child:{...}, relationshipType:"one_to_many"|"one_to_one"|"many_to_many", relationshipTable:{objectId,name} }` — same tuple shape; see note above about auto-inference bias.

**Translation rule:** classic attribute bodies can be cloned into a Mosaic model with only container remapping (model id substitution) IF the lookup tables already exist as physical tables in the target Mosaic model. Custom forms with `ApplySimple(...)` or `Concat(...)` expressions port directly.

## Metric anatomy (Mosaic body → classic equivalent)

`GET /api/model/dataModels/{mid}/factMetrics/{fmid}` and `.../metrics/{mid}` both return the classic metric body shape. Observed expression kinds:

- **Simple aggregate** (dominant): `Sum({Extended Price})`, `Avg({Wait Time Minutes})`. `expression.tree.type = "object_reference"` wrapping a fact/metric ref with a function.
- **Compound expression** (inlined): `Sum({Loans Approved}) / NullToZero(Sum({Applications Submitted}))`. `expression.tree.type = "operator"`, `functions` contain `divide, null_to_zero, sum`.
- **Transformation-style** (inlined, not a separate transformation object): `PreviousYear({Transaction Date}({Transaction Date}),1,{Expense Amount})` and `(Sum({Expense Amount}) - PreviousYear(...)) / PreviousYear(...)` — these would be separate transformation objects in classic but are expressed as function calls in Mosaic.
- **Level/conditional metadata** carried alongside the expression; no separate `conditionality` object in the live bodies we read, but `hasConditionality` keys appear on a minority of metrics.
- **Subtotals / thresholds / smart totals / format** keys all present in the body schema even when not heavily populated.

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
- Auto-inference bias: Mosaic marks almost everything as `one_to_many`. If the classic relationship is `one_to_one` or `many_to_many`, set it explicitly after import — verified portfolios show this is chronically under-modeled.

## Filter, prompt, consolidation, custom group translation

- **Project filter objects** (`type 1`): no direct Mosaic container. Convert to either a security filter on the Mosaic model or a runtime filter at report/dashboard time. Custom-group filters (classic subtype 257) must be rebuilt as consolidations or logical metric conditions.
- **Prompts** (`type 10`): no Mosaic endpoint exists. Prompts are runtime concerns; migrate their semantics into runtime filters, agent questions, or dashboard-level inputs.
- **Security filters**: classic `/api/model/securityFilters/{id}` (definition) + `PATCH /api/securityFilters/{id}/members` is project-scoped; Mosaic `/api/model/dataModels/{mid}/securityFilters/{sfid}` (definition) + `PATCH /api/dataModels/{mid}/securityFilters/{sfid}/members` is model-scoped (member paths drop the `/model` prefix). Expression/qualification JSON is the same shape. Reassign membership per target model.
- **Consolidations / custom groups**: not visible in Mosaic. Express as compound metrics with `case_when` / nested operator expressions, or as model-level filters.

## Governance translation

- **ACL**: classic `GET /api/objects/{id}?type=...` (read `acl[]`) / `PUT /api/objects/{id}?type=...` with an `acl` body is global — there is no `/api/objects/{id}/acl` sub-resource; Mosaic-contained objects **must** use `PATCH /api/model/dataModels/{mid}/objects/{oid}/acl?subType=...` inside a changeset. Rights mask is the same EnumDSSXMLAccessRightFlags on both: browse=1, use_execute=2, read=4, write=8, delete=16, control=32, use=64, execute=128 (view 197, modify 221, full 255). Corrected 2026-10-05 — the old read=1/write=2/delete=4/browse=64/use=512/inherit=1024 table was wrong; see `reference_mosaic_acl.md`.
- **Translations**: classic `/api/objects/{type}/{id}/translations` vs Mosaic `/api/model/dataModels/{mid}/objects/{oid}/translations?subType=...` inside a changeset. Same `name.translationValues` + `description.translationValues` shape keyed by locale.
- **Certification**: `PUT /api/objects/{id}/certify?type=...&certify=true` is the global endpoint (the spec has no `PATCH /api/objects/{id}`; corrected 2026-10-05); the Mosaic model itself is certified through it using its model id.
- **VLDB**: there is no `/api/objects/{id}/vldbProperties` (corrected 2026-10-05). Modeling objects carry VLDB overrides in `advancedProperties` (read with `showAdvancedProperties=true`); the object-level `GET/DELETE /api/objects/{id}/vldb/propertySets` + `PUT …/vldb/propertySets/{name}` paths are internal and described for datasets/documents. Model-scoped VLDB overrides live at data-model level, not per-metric.

## Storage / runtime translation

- **In-memory Mosaic models** back onto the Intelligent Cube family, but publish/refresh goes through the documented data-model flow: `POST /api/dataModels/{id}/instances` → `POST …/publish` with per-table `refreshPolicy` (add / update / upsert / replace / …) → `GET …/publishStatus` → delete the instance (`reference_mosaic_publish_path.md`). Corrected 2026-10-05: `POST /api/cubes/{id}/publish`, `POST /api/cubes/{id}/refresh` and `PATCH /api/cubes/{id}` are not in the spec, and `POST /api/cubes/{id}` (what Studio fired in 2026-04 captures) is internal + deprecated. Scheduled refresh is a subscription (`reference_strategy_subscriptions_and_schedules.md`).
- **Connect-live Mosaic models** skip cube storage but still require a `pipeline` table shape on verified tenants. Direct `warehouse_partition_table` wiring is documented in `reference_mosaic_rest_api.md` but was not observed in production use.
- **Hyper / MTDI Super Cubes** that now appear as subType 779 (`dataServeMode == ""`): treat as read-only. Do not attempt changeset writes; they need an explicit upgrade path that isn't covered by `/api/model/dataModels` writes.

## Things that do NOT cleanly cross the bridge

- Classic **agent/template** attributes (`subtype 3072/1024`) and **system/transformation** attributes — already flagged in the classic field study as `/api/model/attributes/{id}` failures; they are not Mosaic candidates.
- Classic **prompts** — no Mosaic counterpart; migrate to runtime or agent UX.
- Classic **custom groups / consolidations** — recreate as expression-level logic.
- Classic **drill hierarchies (user hierarchies)** — the attribute set ports; the drill definition is lost.
- Classic **dynamic/unmapped metrics** tied to transformation objects without expression equivalents — audit manually.
- Legacy **Hyper datasets** surfaced as subType 779 — don't treat as Mosaic-writable until re-authored.

## Helper usage cheat-sheet

```bash
# Full sweep (writes /tmp/strategy-mosaic-inventory-<stamp>.json)
MSTR_PASSWORD=... /usr/bin/python3 skills/build-mosaic-model/scripts/strategy_mosaic_inventory.py --workers 12

# Narrow by name fragment for iterative analysis
MSTR_PASSWORD=... /usr/bin/python3 skills/build-mosaic-model/scripts/strategy_mosaic_inventory.py \
  --model-name "<name fragment>" --out /tmp/mosaic-subset.json

# Single known model
MSTR_PASSWORD=... /usr/bin/python3 skills/build-mosaic-model/scripts/strategy_mosaic_inventory.py \
  --model-name "<exact model name>" --max-models 1
```

Output fields per model: `counts`, `dataServeMode`, `attributes[]` (forms, relationships, tables), `factMetrics[]`, `customMetrics[]` (with `expressionText`, `expressionKind`, `functions`), `tables[]` (physicalType/columnCount), `hierarchy` (relationshipCount + types), `securityFilters[]`, `externalDataModels[]`, `subresourceStatuses` (ok + error per endpoint).

Portfolio-level rollups: `physicalTableTypes`, `attributeFormTypes`, `metricFamilyFlagCounts`, `hierarchyRelationshipTypes`, `securityFilterQualificationTypes`.
