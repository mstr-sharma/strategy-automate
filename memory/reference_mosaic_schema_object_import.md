---
name: Schema-object-to-Mosaic import pipeline
description: How to build a Mosaic data model from existing classic schema object IDs (attributes, facts, metrics) using build_mosaic.py build-from-schema-objects — covers the translation pipeline, changeset sequencing, batch API usage, known limitations, and the review-file format.
type: reference
---

## When to use

Use when a classic project already has a well-governed semantic layer and the goal is to stand up an equivalent Mosaic model without re-authoring object definitions from scratch. Prefer this over `build` + legacy-as-blueprint when you want to skip the intermediate manual translation step.

Do NOT use when the classic project has many `ApplySimple(...)` expressions or custom SQL facts — those will be flagged in the review file and require manual remediation.

## Entry command

```bash
python3 skills/build-mosaic-model/scripts/build_mosaic.py build-from-schema-objects \
  --name "Sales Model" \
  --attribute-ids A1,A2,A3 \
  --fact-ids F1,F2 \
  --metric-ids M1,M2,M3 \
  --data-serve-mode in_memory \
  --publish \
  --review-file /tmp/sales_model_review.json
```

For larger classic projects, pass IDs from files using the `@filepath` syntax:

```bash
python3 skills/build-mosaic-model/scripts/strategy_semantic_mine.py \
  --mode top-down --report "Revenue Report" \
  --out /tmp/mine.json

# Extract IDs from the mine output, then:
python3 skills/build-mosaic-model/scripts/build_mosaic.py build-from-schema-objects \
  --name "Revenue Model" \
  --attribute-ids @/tmp/attr_ids.txt \
  --fact-ids @/tmp/fact_ids.txt \
  --metric-ids @/tmp/metric_ids.txt \
  --publish
```

## Changeset sequencing

Three changesets are used to respect object-reference ordering:

- **CS1**: tables + attributes + factMetrics (committed together; relationships need committed objects to reference).
- **CS2**: relationships (attributes must be committed before relationships can reference them).
- **CS3**: derived metrics (factMetrics must be committed before compound metrics can reference their IDs).

If any step fails, the open changeset is discarded so the model is left in a consistent state.

## Batch API

Attributes and factMetrics are written via `POST /api/model/batch` for performance. If the tenant returns 404 on the batch endpoint, the script automatically falls back to individual POST calls. Run with `-v` to confirm which path was used.

## Known limitations

1. **No batch read.** Classic object definitions are fetched one at a time. For projects with >200 objects the script applies a 50ms rate delay per call. Expect ~30–60 seconds of read time for large projects.

2. **Session cap.** The entire pipeline runs in one session. The ~5-session cap on Strategy ONE Cloud tenants should not be reached for single-model builds. If you see error 8004cb0a, check that no other terminals have open sessions on this user/project combination — see `feedback_build_mosaic_session_leak.md`.

3. **ApplySimple expressions.** Facts whose token list contains `apply_simple`, `custom_expression`, or `raw_sql` are included verbatim and flagged in the review file. They may fail at query time if the Mosaic SQL engine does not accept the syntax. Review and remediate manually after the build.

4. **Conditional metric filters.** Conditional metrics carry `conditionality.filter` references that point to classic project filter object IDs. These IDs do not exist in the Mosaic model, so the filter reference will be broken. Recreate the filter inside the Mosaic model and patch the metric post-build.

5. **Level/dimensionality metrics.** The `dimty.dimensions` attribute IDs are translated through the mosaic attribute ID map when possible. Attributes not in the translated set retain their classic IDs and will not resolve in Mosaic.

6. **Relationship table ID.** Each classic relationship's `relationshipTable.objectId` is mapped through the logical-table map. If the classic relationship references a table that wasn't created in the new model, the relationship is still created but without a relationshipTable, and a warning is recorded.

## Review file format

```json
{
  "model_id": "<mosaic model object ID>",
  "model_url": "<base>/app/library#/model/<id>",
  "translated": {
    "attributes": 12,
    "factMetrics": 4,
    "metrics": 8,
    "relationships": 18
  },
  "warnings": [
    "[attr A1] form 'ID' references table T99 not found in logical_table_map — skipped",
    "[fact F1] expression contains unsupported token type 'apply_simple' — manual review required"
  ]
}
```

## Integration with the mine pipeline

Run `strategy_semantic_mine.py` first to discover object IDs from a report or table. The `mosaicSeedPlan.candidateAttributes`, `.candidateFacts`, and `.candidateMetrics` arrays in the mine output contain the IDs to pass here.

## Error codes

- `8004cb0a` / iServerCode `-2147072486`: session cap. See `feedback_build_mosaic_session_leak.md`.
- `8004ccdb`: relationship self-reference — a parent and child attribute resolve to the same Mosaic object. Means the classic relationship was circular; remove it.
- `-2147212544`: publish stall — typically a column datatype that wasn't normalized before writing. The `normalize_datatype()` step in `schema_object_translator.py` should prevent this; if you still see it, check the review file for tables that were skipped during table creation and re-fetch them.
