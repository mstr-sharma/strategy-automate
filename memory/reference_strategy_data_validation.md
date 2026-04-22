---
name: Strategy data validation reference
description: How to validate a Mosaic/Strategy model's numeric correctness against a trusted reference source (other Mosaic, legacy report, flat file, warehouse SQL, REST fixture). Pointer to the strategy-validation skill.
type: reference
---
Companion to the `strategy-validation` skill (`strategy-validation/SKILL.md`) and the consumer-grade naming checklist (`feedback_consumer_grade_naming.md`).

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
| Another Mosaic model | Clone-and-remap variants, live/in-memory pair, sibling project model | MCP MCP `query` Trino, or REST `/api/v2/cubes/{id}/instances` |
| Classic/legacy project report | Legacy→Mosaic migration, reproducing a known dashboard answer | Classic `/api/reports/{id}/instances` + JSON Data API, or Modeling Service reads per `reference_strategy_legacy_to_mosaic_mining.md` |
| Flat file (CSV/Parquet/JSON) | Auditor gold set, snapshot export, hand-curated fixture | Local DuckDB/Pandas |
| Direct warehouse SQL | "Does the semantic layer math match raw warehouse?" | Snowflake/BigQuery/Oracle driver with service creds |
| External system / REST fixture / prior run | Regression, system-to-system reconciliation, "does today's build still match yesterday's?" | API call, saved JSON diff target, or source-system export |

Do not default to Mosaic-to-Mosaic just because MCP is convenient. Use the most trusted comparator for the business question.

## Minimum 5-query suite

Every validation runs these shapes at minimum:

1. Grand-total + row count.
2. One-dim descriptor breakdown.
3. Two-dim hierarchical rollup (proves relationships).
4. Filtered subset (proves filter semantics + SF isolation).
5. Time-based split (proves date coercion + timezone).

Rotate specific queries each run so regressions in untested corners surface over time.

## Match / tolerance rules

- Numeric tolerance default: `|a - b| / max(|a|, |b|, 1) <= 1e-6`.
- Currency to cents (2dp); rates to 4dp; counts exact.
- Sort both result sets by group-by tuple before compare.
- NULL == NULL for compare; treat missing dim values as `<NULL>` sentinel.
- Report `matched`, `reference_only`, `model_only`, `delta_rows`, `worst_delta_pct`.

## Verified run (TPC-H, 2026-04-21)

Validated `Snowflake TPCH-Built_By_Claude-20260421T2305Z` against live reference `Snowflake TPCH_SF1` via Mosaic MCP Trino. All 5 queries matched byte-for-byte:

- Q1 grand total: 1,500,000 orders, $226,829,306,447.46 ✓
- Q2 market-segment breakdown (5 rows) ✓
- Q3 Region × Nation revenue (10 rows) ✓
- Q4 Europe supplier rollup (5 nations) ✓
- Q5 Year × Ship-mode (14 rows across 1995-1996) ✓

Both models trace to the same Snowflake `TPCH_SF1` source — matching proves the clone-and-remap faithfully reproduced the reference semantics.

## Gotchas observed

- **`ERR001 "Maximum number of interactive session per user for project exceeded"`** — fired after ~10 consecutive REST logins on {MSTR_BASE host}. Mitigation: (a) reuse sessions via a single helper process, (b) explicit `DELETE /api/auth/login` on exit, (c) route read validations through MCP `query` which uses a pool. Do not loop-login per-query.
- **Column names over Trino use `"<attribute name lowercase> (<form name lowercase>)"`** — e.g., `"region (region name)"`, `"customer market segment (customer market segment)"`. Entity IDs appear as `"order (order key)"`. Metric columns use just the metric name, lowercase, with spaces preserved (`"order total price"`).
- **Missing expected column** returns Trino `Column 'X' cannot be resolved` — check form-category naming before blaming the model.
- **Connect-live models don't need a publish step.** `POST /api/cubes/{id}` returns "no publish endpoint accepted" for `connect_live` models; that's expected, not an error.

## Helper script (planned / extend)

`skill/scripts/strategy_validate_models.py` — pluggable runner. The implemented core compares CSV/JSON result files:

```bash
python3 skill/scripts/strategy_validate_models.py \
  --model-file /tmp/model_rows.json \
  --reference-file /tmp/reference_rows.json \
  --key region,nation \
  --measures revenue,orders \
  --out /tmp/validation.json
```

Live adapters are intentionally incremental. They should accept:

- `--model <name>` — the model under test (Mosaic by name; resolves via MCP or REST search)
- `--reference-mosaic <name>` — another Mosaic model
- `--reference-sql-file <path> --reference-conn <dsn>` — raw warehouse SQL
- `--reference-file <path> --key cols --measures cols` — flat-file gold set
- `--reference-classic-report <name>` — classic/legacy project report
- `--reference-rest-file <path>` or external-system adapter options — REST/API fixture comparison
- `--query-suite <name>` — named suite (tpch-standard, retail-standard, etc.)
- `--tolerance <float>` — numeric tolerance (default 1e-6)
- `--out <json>` — structured validation result

Until a live adapter exists for a source, run ad-hoc through the appropriate source adapter, save both row sets, and feed them into `strategy_validate_models.py`. The TPC-H validation above used MCP `query` because the trusted comparator was another Mosaic model; a legacy migration or external reconciliation should use the legacy report/API/warehouse adapter instead.
