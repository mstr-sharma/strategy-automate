---
name: Mosaic post-build validation recipe
description: The runnable checklist that turns the build-quality rules into a pass/fail gate; uses `build_mosaic.py validate-model` and drops into any build or regression pipeline.
type: reference
---
Every Mosaic build ends with this validation pass before being reported as complete. Codifies the rules in `feedback_mosaic_build_quality.md` and `reference_mosaic_relationship_archetypes.md` into a small set of automatable checks. Run as a subcommand of the build helper:

```bash
python3 skills/build-mosaic-model/scripts/build_mosaic.py validate-model --model-id <dataModelId>
```

Output is human-readable + a JSON payload. Exit code non-zero if any FAIL check trips.

## Check catalog

Each check is classified `FAIL` (build must be rejected) or `WARN` (review before ship).

### F1 — Empty form names (FAIL)
Iterate every attribute in `/api/model/dataModels/{id}/attributes`; for each, assert `forms[i].name` is a non-empty string. Canonical rule, root cause (auto-hierarchy failures, blank UI labels), and the `8004cc63` fix-at-create-time note: `feedback_mosaic_ship_bar.md` § Form naming.

### F2 — Read-back integrity (FAIL)
For every object listed under `/attributes`, `/tables`, `/factMetrics`, `/filters`: issue an individual `GET` by id. Any non-200 is a partial-commit regression (see TPC-H MODEL2's REGION → HTTP 500 while the commit reported success).

### F3 — Missing required top-level fields (FAIL)
Assert `information.name`, `information.description`, `dataServeMode`, `autoJoin`, `enableAutoHierarchyRelationships` are all populated.

### W1 — Orphan attributes on fact/bridge tables (WARN, promote to FAIL if a fact list is provided)
List attributes where `attributeLookupTable.name` matches a known fact/bridge table AND `relationships` is empty. Each should have at least one parent dim relationship. Heuristic for fact/bridge: table name in `{LINEITEM, ORDER_DETAIL, FACT_*, F_*, ORDERS, INVENTORY*, *_FACT, *_DETAIL, REL_*}` OR the table serves as `relationshipTable` in ≥2 rels.

### W2 — Blank descriptions (WARN)
Assert `information.description` non-empty on the model itself and on every attribute and fact-metric. AI-agent grounding and Library discoverability degrade without them.

### W3 — FK coverage vs fact-table FK columns (WARN)
For every fact table (as heuristically detected in W1), count the distinct `parent.objectId` values across its incoming `relationships[].relationshipTable == <factTable>` entries. Compare to the declared/expected FK count. If the count is less than the number of FK columns on the physical table, flag each missing FK by column name.

### W4 — Suspect default aggregation on rate/price metrics (WARN)
Scan every fact metric. If its name or source column matches `*_RATE|*_PCT|*_RATIO|DISCOUNT|TAX|*_PRICE|*_COST|*BALANCE*` and its `function` is `sum`, emit a review line. Summing a rate is almost always wrong; summing a unit price is usually wrong (unless the user explicitly wants the line-item sum in which case AVG-at-dim + derived SUM(qty*price) is the right shape).

### W5 — Duplicate attribute names (WARN)
Within the model, no two attributes should share a `name` unless one is clearly a dim-level descriptor and the other is a fact-level derived; almost always this indicates a conformed-dimension mis-merge.

### W6 — Missing date hierarchies (WARN)
For every date/timestamp column referenced by any attribute, assert that Day/Month/Quarter/Year derivatives exist as separate attributes with a fan-out rel chain. Emit per-missing-level warnings.

## Programmatic output shape

```json
{
  "modelId": "...", "modelName": "...",
  "counts": {"tables": 8, "attributes": 52, "factMetrics": 10, "filters": 0, "relationships": 54},
  "failures": [{"check": "F1", "object": {...}, "message": "..."}, ...],
  "warnings": [{"check": "W3", "object": {...}, "message": "..."}, ...]
}
```

## Regression / diff mode

```bash
python3 skills/build-mosaic-model/scripts/build_mosaic.py validate-model --model-id <new> --diff-against <prev>
```

Prints a side-by-side count table (attributes, relationships, factMetrics) + a list of object names present in `<prev>` but missing in `<new>`. Use on every rebuild against an existing model — treat any count drop as a regression unless explicitly intended.

## When to run

- After every `build` / `build-from-config` commit (before returning success to the user).
- After any single-object write (e.g., `patch-model-object`) that touches attributes or relationships.
- Before publishing or certifying a model.
- After bumping the build helper's code — in case the refactor dropped a step.

## When to skip

- Read-only exploration of a model you did not write (there's nothing to validate; the model is what it is).
- Ad-hoc security-filter / ACL work on a model already validated this session.

## Known heuristic limits

- The fact/bridge detector is name-based; supply `--fact-tables TBL,TBL` to override when your naming conventions don't match the built-in list (e.g., `SALES`, `TRANSACTIONS`, `ACTIVITY_LOG`).
- The rate/price aggregation heuristic matches column name; if your warehouse uses business-friendly names like `LINE_DISCOUNT` you'll need to extend the regex or supply `--rate-columns ...`.
- Compound-FK detection requires physical-column metadata on the table; if `/tables/{id}` returns `columns: []` (observed on some tenants for materialized models), the compound check is skipped with a WARN.
