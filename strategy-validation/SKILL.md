---
name: strategy-validation
description: Validate a Strategy Mosaic (or any Strategy) model against a trusted reference — another Mosaic model, a classic/legacy semantic-layer query, a flat file (CSV/Parquet/JSON), a direct warehouse SQL query, or a REST report output. Run a suite of paired queries, compare aggregates row-by-row with numeric tolerance, report matches/mismatches/missing rows.
---

# Strategy Data Validation

Use this skill whenever a model (especially a freshly built or modified Mosaic model) needs to be proven data-correct before it's marked shippable. **Every build should close with validation.** The reference source can be whatever trusted artifact is closest to ground truth — this skill is not Mosaic-only.

## When to invoke

- Right after a new Mosaic build completes (before reporting "done").
- After a schema change (added/removed tables, attribute re-mapping, metric override, relationship edit).
- Before a production publish or refresh.
- During a legacy → Mosaic migration, to prove the Mosaic model reproduces classic report answers.
- On demand when a user doubts a number they saw in a dashboard.

## Reference sources (pluggable)

Pick the reference based on what's available and trusted:

1. **Another Mosaic model** — clone-reference pattern. Query via MCP Trino (MCP `query`) with `schema="{your project name lowercased}"`. Best when validating a clone-and-remap or an alternate live/in-memory variant of the same source.
2. **Classic/legacy semantic-layer report** — run the classic report via `/api/reports/{id}/instances` + JSON Data API, or query the classic project attributes/metrics through the Modeling Service. Best during legacy-to-Mosaic migrations; see `memory/reference_strategy_legacy_to_mosaic_mining.md`.
3. **Flat file** (CSV / Parquet / JSON) — a snapshot export, hand-curated gold set, or auditor-supplied file. Load locally with `csv` / `json` / DuckDB / Pandas. Best when the warehouse is read-once (compliance exports, audit reconciliation).
4. **Direct warehouse SQL** — bypass the semantic layer entirely and query Snowflake / BigQuery / Oracle / etc. with raw SQL. Best for "does the semantic-layer math match the raw warehouse?" checks.
5. **REST output** — saved output from a prior run (canary fixture), an externally-hosted reference API, or a previous inventory snapshot. Best for regression: "does today's build still match yesterday's numbers?"

Every source adapter reduces to `run_query(q) -> list[dict]`. The skill diffs structured rows regardless of source.

## Minimum validation suite (5 paired queries)

A shippable validation covers these 5 shapes at minimum. Expand to 10+ for critical / production-bound models.

1. **Totals + cardinality** — `SELECT COUNT(*), SUM(<primary measure>) FROM <model>`. Catches empty models, wrong fact table, fact-table double-joins.
2. **One-dim breakdown** — group by a high-cardinality descriptor (market segment, brand, ship mode). Catches attribute→fact join breaks.
3. **Two-dim rollup across the relationship chain** — e.g., Region × Nation revenue with hierarchical joins. Catches missing or mis-directed relationships (this is how the TPC-H Line-Number-overwritten bug surfaces).
4. **Filtered subset** — group by a descriptor inside a narrow filter (e.g., WHERE region = 'EUROPE'). Catches filter semantics + security-filter bleed-through.
5. **Time-based split** — YEAR() × a descriptor. Catches date-type coercions, timezone shifts, and the common "quarter truncation" bug.

Pick random / domain-appropriate variants; do not always run the same 5 — rotate queries so regressions in untested corners of the model surface.

## Comparison semantics

- **Numeric tolerance:** default `|a - b| / max(|a|, |b|, 1) <= 1e-6`. Decimal/currency columns should match to cents; rates to 4 decimal places. Raise tolerance only when a known reason exists (e.g., reference file was truncated to 2dp).
- **Row-set matching:** join both result sets on the dimension tuple (group-by columns). Report: `matched`, `reference_only` (rows in reference but missing from model), `model_only` (rows in model not in reference), `deltas` (rows present both sides but with differing metric values).
- **Ordering insensitivity:** always sort both sides by the dim tuple before compare; don't rely on the query's `ORDER BY` matching.
- **Null handling:** `NULL == NULL` for compare purposes (do not let Snowflake-style `NULL != NULL` silently fail rows); treat missing dimension values as `<NULL>` sentinel in the key tuple.

## Result format

The validator returns a structured result for each paired query:

```json
{
  "query_name": "region_nation_revenue",
  "status": "ok" | "mismatch" | "error",
  "row_count_model": 25,
  "row_count_reference": 25,
  "matched_rows": 25,
  "reference_only_rows": [],
  "model_only_rows": [],
  "delta_rows": [],
  "worst_delta_pct": 0.0,
  "metric_columns": ["revenue", "units"],
  "elapsed_model_ms": 812,
  "elapsed_reference_ms": 745
}
```

Final report: `N/N passed` plus a table of any failures with the smallest reproduction query on the left and the delta on the right.

## Helper script

`skill/scripts/strategy_validate_models.py` (planned — reuse `strategy_validate.py` scaffolding):

```bash
# Validate a new Mosaic model against another Mosaic model (default via MCP Trino).
python3 skill/scripts/strategy_validate_models.py \
  --model "snowflake tpch-built_by_claude-20260421t2305z" \
  --reference-mosaic "snowflake tpch_sf1" \
  --query-suite tpch-standard \
  --out /tmp/validation.json

# Validate against a warehouse query (Snowflake direct) — raw SQL reference.
python3 skill/scripts/strategy_validate_models.py \
  --model "new-retail-model" \
  --reference-sql-file /tmp/ref_queries.sql \
  --reference-conn snowflake://... \
  --query-suite retail-standard

# Validate against a flat file baseline.
python3 skill/scripts/strategy_validate_models.py \
  --model "new-retail-model" \
  --reference-file /path/to/gold.parquet \
  --key customer_id,month \
  --measures revenue,units

# Validate against a classic/legacy project report.
python3 skill/scripts/strategy_validate_models.py \
  --model "mosaic-replacement" \
  --reference-classic-report "Historical Product Revenue Analysis" \
  --project-id {MSTR_PROJECT_ID}
```

Until the helper is written, the equivalent ad-hoc flow is: run each query twice (once per source), diff in Python/Pandas, report. The `strategy_validate.py` file in `skill/scripts/` already has the tenant-auth scaffolding and the paired-run harness from the non-Mosaic validation suite — extend that rather than start from scratch.

## Integration with build workflows

Every build-mosaic-model invocation should append a validation step:

1. Build completes with `model_id` + canonical name.
2. Validator auto-selects a reference: (a) if the user supplied one, use it; (b) else if a sibling model of the same source is live, use it; (c) else prompt the user.
3. Run the 5-query minimum suite.
4. Report aligns with the build report: `✓ model built, 5/5 validation queries match reference <name>`.
5. If any query fails: mark the build as **incomplete**, surface the delta rows prominently, and do not tell the user "done" until failures are explained or fixed.

The consumer-grade naming checklist (`memory/feedback_consumer_grade_naming.md`) item 8 requires validation — treat this skill as part of the ship bar.

## Non-goals

- This is not a performance benchmark. For latency/throughput comparisons of semantic-layer alternatives, use `<sibling harness dir>/benchmark_*.py`.
- This is not a schema validator. For "does the shape look right" (attribute count, form categories, relationship graph) use `skill/scripts/strategy_mosaic_inventory.py`.
- This is not a SQL linter or a metric-lineage tool — it checks numeric correctness only.
- Security-filter effectiveness is a separate validation (confirm the right rows are *hidden*, not just that aggregates match); route that through `memory/reference_strategy_validation_workflows.md`.
