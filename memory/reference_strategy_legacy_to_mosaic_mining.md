---
name: Legacy → Mosaic migration hub + semantic mining
description: Start-here hub for classic-to-Mosaic migrations. Sequences the four related memories (mining → field study → blueprint → clone-and-remap) and documents the read-only discovery lane for classic attributes, facts, metrics, filters, prompts, reports, documents, and tables.
type: reference
tags: [mosaic, classic, migration, kimball]
---

## Start here — the 4-step classic → Mosaic workflow

Legacy-to-Mosaic work always flows through these four memory files in order. Load them as needed; do not skip.

1. **Inspect the classic project** — THIS file (`reference_strategy_legacy_to_mosaic_mining.md`). Run `strategy_semantic_mine.py` top-down from reports/documents or reverse from tables to discover the attributes / facts / metrics / filters / prompts / hierarchies already in play.
2. **Read the live classic inventory** — [`reference_strategy_tutorial_semantic_field_study.md`](reference_strategy_tutorial_semantic_field_study.md). Captures actual REST payload shapes for every object class; use as a Rosetta Stone when translating to Mosaic.
3. **Pick the migration pattern** — [`feedback_mosaic_legacy_as_blueprint.md`](feedback_mosaic_legacy_as_blueprint.md) (blueprint-driven: mirror the classic shape into a new Mosaic model) OR [`reference_mosaic_clone_pattern.md`](reference_mosaic_clone_pattern.md) (clone-and-remap: copy an existing Mosaic model as a starting point). Blueprint-driven is correct when the classic project has meaningful semantics worth preserving; clone-and-remap is correct when a similar Mosaic model already exists in the tenant.
4. **Build the Mosaic target** — route through `strategy-data-modeling/SKILL.md` (planning, Kimball-first) and `skill/SKILL.md` (execution). Validate with `strategy-validation/SKILL.md` against the original classic reports as the comparator.

Related: [`reference_strategy_design_transition.md`](reference_strategy_design_transition.md) covers conceptual differences between classic and Mosaic; read it when a 1:1 mapping breaks down (e.g., compound metrics, fact extensions, consolidations).

## When to use this file

Use this when the user asks to modernize a legacy project into Mosaic, find the warehouse tables behind important reports/documents, clone legacy semantics into a new model, or start from a table and discover which attributes/facts/metrics/reports depend on it.

This is a read-only discovery lane until the user approves an actual Mosaic build.

For live examples of the object payloads this lane mines, read `reference_strategy_tutorial_semantic_field_study.md`. It documents the actual Tutorial REST bodies for multi-form attributes, relationship tuples, facts with multiple expressions and fact extensions, nested/level/conditional/transformation metrics, filter qualification trees, object/element prompts, system hierarchy, and user hierarchies.

## Helper

Script:
```bash
python3 skill/scripts/strategy_semantic_mine.py --mode top-down --report "Revenue Report"
python3 skill/scripts/strategy_semantic_mine.py --mode top-down --document "Executive Dashboard"
python3 skill/scripts/strategy_semantic_mine.py --mode reverse --table "LU_PRODUCT"
python3 skill/scripts/strategy_semantic_mine.py --mode reverse --seed TABLE_OBJECT_ID;15
python3 skill/scripts/strategy_semantic_inventory.py --workers 8 --out /tmp/strategy-semantic-inventory.json
```

Outputs:
- `candidateTables`: scored table IDs/names with reasons.
- `semanticObjects`: discovered legacy attributes, facts, metrics, filters, prompts, reports, and documents.
- `mosaicSeedPlan`: table IDs/names plus candidate legacy attributes/metrics/facts to recreate or validate in Mosaic.

The script uses runtime credentials only and does not store tokens or data exports.

Verified on `a verified Strategy Cloud tenant`:
- Top-down report mining for `Historical Product Revenue Analysis No Prompt` resolved attributes (`Category`, `Subcategory`, `Year`), metrics (`Revenue`, `Profit`, `Cost`, `Units Sold`), and scored candidate tables including `F_TUTORIAL_TARGETS`, `LU_SUBCATEG`, `YR_CATEGORY_SLS`, `LU_CATEGORY`, and date/product lookup tables.
- Metadata component search returned empty for that report, so the helper used a read-only report instance/JSON Data API fallback to mine `availableObjects`, then read Modeling Service definitions for table references.
- Reverse table lineage can also be sparse. The helper falls back to a bounded visible attribute/fact definition scan (`--scan-limit`, default `40`) and records warnings when lineage/scan returns no downstream objects.

## Endpoint semantics

Legacy dependency discovery is mostly a Browsing/metadata-search concern:

- Quick object lookup: `GET /api/searches/results`.
- Stored metadata search: `POST /api/metadataSearches/results`, then optional `GET /api/metadataSearches/results`.
- Component/dependency search: `usedByObject=<objectId;objectType>` means "return objects used by this object." Example: report -> attributes/metrics/filters/tables.
- Dependent/impact search: `usesObject=<objectId;objectType>` means "return objects that use this object." Example: table -> attributes/facts -> reports/documents.
- Quick Search reverse fallback: `GET /api/searches/results?usesObjectId=<id>&usesObjectProjectId=<projectId>&type=<targetType>`.
- Recursive flags: `usedByRecursive=true` and `usesRecursive=true` expand beyond direct edges when supported.
- Dedicated relationship endpoint visible in OpenAPI: `POST /api/searches/dependents/relationships/query` ("Get Used By Relationship"). Use it when metadata search does not expose enough path detail.

Common classic object types:

- Filter: `1`
- Report: `3`
- Metric: `4`
- Template: `5`
- Prompt: `10`
- Attribute: `12`
- Fact: `13`
- Table: `15`
- Document/dashboard/document-style dossier: `55`

Confirm object type from search results before running lineage; subtype alone is not enough.

## Top-down report/document path

Use when the user says "turn this dashboard/report pack into a Mosaic model" or names business content first.

1. Resolve seed reports/documents by exact name and type.
2. Run metadata search with `usedByObject=<reportOrDocumentId;type>` for attributes, metrics, facts, filters, prompts, and tables.
3. If metadata search returns no components, create a read-only runtime instance and mine JSON Data API `availableObjects` / definition payloads for attributes and metrics.
4. For each discovered semantic object, read its Modeling Service definition when possible:
   - `/api/model/attributes/{id}?showExpressionAs=tree`
   - `/api/model/metrics/{id}?showExpressionAs=tree`
   - `/api/model/facts/{id}?showExpressionAs=tree`
   - `/api/model/filters/{id}?showExpressionAs=tree`
   - `/api/model/prompts/{id}?showExpressionAs=tree`
   - `/api/model/systemHierarchy/attributes/{attributeId}/relationships`
   - `/api/model/hierarchies` and `/api/model/hierarchies/{id}`
5. Parse table references from expression trees and object definitions.
6. Score table candidates:
   - direct table dependency from report/document: high confidence.
   - table referenced by attribute/fact definition: high confidence.
   - table inferred only from metric/filter expression: medium confidence.
7. Produce a Mosaic seed plan: source tables, attributes to recreate, metrics to clone/remap, filters/security filters to evaluate, and unresolved objects needing manual review.

## Reverse table path

Use when the user gives one or more warehouse tables and asks what existing semantic layer depends on them.

1. Resolve table object IDs from names or accept `TABLE_ID;15`.
2. Run `usesObject=<tableId;15>` for attributes, facts, metrics, filters, prompts, reports, and documents.
3. If lineage search is empty, run a bounded scan over visible attribute/fact definitions and match table IDs in Modeling Service JSON. Keep `--scan-limit` modest unless the user explicitly wants exhaustive mining.
4. For discovered attributes/facts, run another dependent search to find reports/documents that use them.
5. Read metric/filter definitions to find additional facts, prompts, transformations, or embedded objects.
6. Score Mosaic candidates by table centrality:
   - tables directly supplied by the user: seed score.
   - tables repeatedly referenced by high-value reports/documents: higher score.
   - lookup tables attached to high-cardinality attributes: include, but mark grain/relationship review.
   - bridge tables or many-to-many helpers: include only if relationship semantics are clear.

## What to carry into Mosaic

Create the Mosaic model from physical tables first, then preserve legacy business semantics deliberately:

- Attributes: names, forms, display forms, key forms, lookup tables, parent/child relationships.
- Facts: source expressions and table mappings.
- Metrics: expression tree/tokens, nested metric references, dimensionality/level, condition, transformation, subtotal/format.
- Filters: distinguish runtime report filters, project filter objects, and security filters.
- Prompts: decide whether to keep as runtime content behavior, convert to filters, or leave outside the model.
- Reports/documents: use as validation fixtures after the model is built, not as Mosaic source objects.

## Safety and quality gates

- Never build directly from one report without checking whether it is a narrow analytic view; use multiple reports/documents when the user wants a domain model.
- Do not include every dependent table blindly. Exclude administrative/noise tables unless they carry real analytic grain.
- Check grain before relationships: entity lookup, fact table, bridge, snapshot, transaction, slowly changing dimension, or calendar table.
- Preserve metric formulas as candidate derived metrics, but verify equivalent fact/attribute IDs in the Mosaic model before creating them.
- Treat prompts and filters as workflow semantics; they may not belong inside the Mosaic model unless the user asks for default filters/security behavior.
- When endpoint results differ from OpenAPI, prefer tenant-verified behavior and record it in this reference or the gotchas file.
