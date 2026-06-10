---
name: Strategy model + data validation reference
description: Minimum validation suite for any Strategy / Mosaic model — comparator selection, 5-query numeric-correctness suite, 10-check design-time checklist, tolerance rules, and failure triage. Pointer to the strategy-validation skill.
type: reference
tags: [validation, mosaic, classic, build, migration, kimball]
---
Companion to the `strategy-validation` skill (`skills/strategy-validation/SKILL.md`) and the Mosaic ship-bar checklist (`feedback_mosaic_ship_bar.md`).

## When validation is required

- Immediately after any Mosaic model build (new or re-built) — before reporting "done".
- After schema edits, metric-override changes, or relationship changes.
- Before a production publish/refresh.
- During any legacy→Mosaic migration.

A build that hasn't been validated is not shippable. The validator's pass rate is part of the release bar, not an optional polish step. If no trusted comparator is available yet, report `validation_status=not_run` and the exact comparator needed instead of implying the build is done.

Validation is reference-dependent. Existing Mosaic models, legacy/classic reports or semantic models, direct warehouse SQL, exported files, and external systems can all be valid truth sources, but each needs a different adapter and query shape.

## Reference source choice (pluggable — NOT Mosaic-only)

Pick whichever source is closest to trusted ground truth:

| Source | When to pick | How to read |
| --- | --- | --- |
| Another Mosaic model | Clone-and-remap variants, live/in-memory pair, sibling project model | MCP `query` Trino, or REST `/api/v2/cubes/{id}/instances` |
| Classic/legacy project report | Legacy→Mosaic migration, reproducing a known dashboard answer | Classic `/api/reports/{id}/instances` + JSON Data API, or Modeling Service reads per `reference_strategy_legacy_to_mosaic_mining.md` |
| Flat file (CSV/Parquet/JSON) | Auditor gold set, snapshot export, hand-curated fixture | Local DuckDB/Pandas |
| Direct warehouse SQL | "Does the semantic layer math match raw warehouse?" | Snowflake/BigQuery/Oracle driver with service creds |
| External system / REST fixture / prior run | Regression, system-to-system reconciliation, "does today's build still match yesterday's?" | API call, saved JSON diff target, or source-system export |

Do not default to Mosaic-to-Mosaic just because MCP is convenient. Use the most trusted comparator for the business question.

## Design-time 10-check suite (before build + during validation planning)

Every shippable model must be validated against a trusted comparator at least across:

1. Row count or event count at declared grain.
2. Total of each core additive metric.
3. Metric by primary time level.
4. Metric by top business dimension.
5. Drill-path rollup from child to parent (Kimball conformed-dimension proof).
6. Null and orphan key counts.
7. Many-to-one relationship violations (rollup inflation/deflation).
8. Distinct counts for high-risk attributes.
9. Top-N comparison against a trusted reference.
10. Security-filter smoke test when security is applied.

## Runnable 5-query minimum suite

Every validation run executes these shapes at minimum:

1. **Grand-total + row count.** Proves overall additivity and grain.
2. **One-dim descriptor breakdown.** Proves a single conformed dim rolls up correctly.
3. **Two-dim hierarchical rollup.** Proves relationships — the Kimball "facts join dims cleanly" check.
4. **Filtered subset.** Proves filter semantics + security-filter isolation.
5. **Time-based split.** Proves date coercion + timezone handling.

Rotate specific queries each run so regressions in untested corners surface over time.

## Match / tolerance rules

- Numeric tolerance default: `|a - b| / max(|a|, |b|, 1) <= 1e-6`.
- Currency to cents (2dp); rates to 4dp; counts exact.
- Sort both result sets by group-by tuple before compare.
- NULL == NULL for compare; treat missing dim values as `<NULL>` sentinel.
- Report `matched`, `reference_only`, `model_only`, `delta_rows`, `worst_delta_pct`.

## Result shape

Recommended durable output shape:

```yaml
validation_result:
  model:
  comparator:
  status: pass | fail | warning
  checks:
    - name:
      model_value:
      reference_value:
      tolerance:
      status:
      issue:
      likely_cause:
```

## Failure triage — common causes

Cross-reference each failure to the likely Kimball / Strategy-engine root cause:

- **Wrong grain** — fact table joined at the wrong natural key; re-declare grain per `reference_data_modeling_foundations.md`.
- **Many-to-many duplication** — bridge table missing or an implicit cartesian via an unconformed dim.
- **Orphan foreign keys** — fact rows without a matching dim row; reject or quarantine upstream.
- **Incomplete attribute conformance** — the conformed-dim promise is broken; see `feedback_mosaic_relationship_wiring.md`.
- **Level metric mismatch** — `dimty` scope wrong; metric is rolling up at a different grain than the user expects.
- **Fiscal vs calendar mismatch** — wrong date role / transformation; see `reference_data_modeling_foundations.md` → Time modeling.
- **Security filter over- or under-constraint** — qualification doesn't match business intent; verify element IDs vs display values.

## Shipping rule

Do NOT call a new build shippable if:

- Totals disagree and no cause is documented.
- Rollup checks fail.
- Relationship cardinality is unverified.
- Security behavior is untested where required.

## Gotchas observed

- **`ERR001 iServerCode -2147072486` / `8004cb0a`** — fires after ~10 consecutive REST logins. Mitigation: (a) reuse sessions via a single helper process, (b) explicit `DELETE /api/auth/login` on exit, (c) route read validations through MCP `query` which uses a pool. See `feedback_build_mosaic_session_leak.md`. Do not loop-login per-query.
- **Column names over Trino** use `"<attribute name lowercase> (<form name lowercase>)"` — e.g., `"region (region name)"`, `"customer market segment (customer market segment)"`. Entity IDs appear as `"order (order key)"`. Metric columns use just the metric name, lowercase, with spaces preserved (`"order total price"`).
- **Missing expected column** returns Trino `Column 'X' cannot be resolved` — check form-category naming before blaming the model.
- **Connect-live models don't need a publish step.** `POST /api/cubes/{id}` returns "no publish endpoint accepted" for `connect_live` models; that's expected, not an error.

## Helper script

`skills/build-mosaic-model/scripts/strategy_validate_models.py` — pluggable runner.

**File adapter (any comparator — dump rows first).** Compares CSV/JSON result files:

```bash
python3 skills/build-mosaic-model/scripts/strategy_validate_models.py \
  --model-file /tmp/model_rows.json \
  --reference-file /tmp/reference_rows.json \
  --key region,nation \
  --measures revenue,orders \
  --out /tmp/validation.json
```

**Live Mosaic-to-Mosaic adapter (implemented).** Runs the same SQL against two Mosaic models through the Strategy Trino endpoint in one call:

```bash
python3 skills/build-mosaic-model/scripts/strategy_validate_models.py \
  --model "<new_model>" \
  --reference-mosaic "<reference_model>" \
  --query 'SELECT "<attr> (<form>)", SUM("<metric>") FROM %s GROUP BY 1' \
  --key '<attr> (<form>)' \
  --measures '<metric>' \
  --out /tmp/validation.json
```

Trino host defaults to the `MSTR_BASE` host; schema defaults to `MSTR_PROJECT_NAME` lowercased. Basic auth reuses `MSTR_USER` / `MSTR_PASSWORD`. Use `%s` or `{{MODEL}}` as the placeholder for the model-as-table name — it gets replaced per side with the correctly-quoted model name.

**Still-pending adapters** (accepted → honest error, pointed at the file adapter workaround):

- `--reference-sql-file` / `--reference-conn` — raw warehouse SQL
- `--reference-classic-report` — classic/legacy project report
- `--reference-rest-file` — REST/API fixture comparison
- `--query-suite` — named suite (tpch-standard, retail-standard, etc.)

Until a live adapter exists for a source, run ad-hoc through the appropriate source adapter, save both row sets, and feed them into the file adapter.

## Related

- `skills/strategy-validation/SKILL.md` — runnable paired-query validator skill.
- `reference_mosaic_build_validation.md` — runnable post-build gate invoked via `build_mosaic.py validate-model`; F/W checks + diff/regression mode.
- `feedback_mosaic_relationship_wiring.md` — fixes the #1 cause of validation failures (broken conformance).
- `reference_data_modeling_foundations.md` — Kimball grain + conformed-dim principles that underpin every validation check.
- `reference_rollup_consistency_validation.md` — the canonical Trino rollup-consistency pattern.
