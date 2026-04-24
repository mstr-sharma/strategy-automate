---
name: Business-logic translation into a Mosaic model
description: How to turn business intent (entities, dimensions, measures, aggregation, relationships) into a correct Mosaic data-model spec. Covers both supplied-context and inspection-only inference paths, with the decision rules for each object type. Kimball-first — classifies every table as fact/dim/bridge and declares the star/snowflake/galaxy topology before picking functions or relationships.
type: reference
tags: [mosaic, modeling, kimball, grain, build, translation]
---

This memory sits upstream of `build-mosaic-model`, `reference_mosaic_modeling_concepts.md`, `reference_mosaic_relationship_archetypes.md`, and `feedback_mosaic_forms_and_formats.md`. Those documents describe *what Mosaic supports*. This one describes *how to decide what the model should contain* before writing a single changeset.

## Output of a translation pass

Produce a single `build-plan.json` (or a dictionary + ERD pair) that answers, for every table:

- **Topology** — `star | snowflake | galaxy | bridge-heavy | non-Kimball`. One-line declaration of the overall schema shape, chosen before individual-table decisions. Non-Kimball stops the build.
- **Table role** — `fact | dim | bridge | snowflake_parent_dim | degenerate_dim | noise` per input table.
- **Grain** — the natural unique row-key combination for each fact, written as `[cols]`.
- **Entities** — which business nouns does this table represent (customer, product, order, event, hour-of-service…).
- **Conformed dims** — any entity that appears in ≥2 tables. Modeled as ONE attribute with multi-table expressions.
- **Attribute list** — for each non-measure column: key form, descriptor forms, display format, and whether it is a per-row descriptor or a dimension-table attribute surfaced on this table.
- **Metric list** — for each measure: function (`sum/avg/min/max/count/count_distinct/stdev/median/p95…`), additivity class (`additive | semi-additive | non-additive | derived`), format token, and a one-line business definition.
- **Relationships** — parent→child pairs with the relationship table and type (`one_to_many`, `many_to_many`, `one_to_one`), plus the reason (shared FK, compound FK, bridge).
- **Derived metrics** — compound/conditional/level/transformation, each with the formula in business terms + the referenced base metrics.
- **Assumptions log** — every inference not explicitly given by the user, so the validation pass can target those assumptions specifically.

The assumptions log is the single most important artifact when context is thin. Every entry is a hypothesis to test in validation.

## Intake ladder — use the strongest signal available

Work top-down; stop at the first tier that answers the question, but always record which tier was used for each decision.

1. **Stakeholder narrative** — "each row of `<fact-table>` is one (`<entity-a>`, `<entity-b>`, hour) triple; `<measure-A>` is a billable count; `<rate-column>` is a percent". Binding and wins over everything else.
2. **Data dictionary / ERD** — column-level business names, descriptions, types, keys, FK relationships. Apply as dictionary JSON (`reference_mosaic_config_schema.md`). ERD overrides inferred joins.
3. **Classic / reference semantic model** — if a legacy project or a Mosaic REF model already covers these tables, mirror its shape (see `feedback_mosaic_legacy_as_blueprint.md`).
4. **Reference query / report output** — a validation CSV, a canonical report, or a saved dashboard. Treat its column names as the *business* names and its aggregate totals as the ground truth to hit.
5. **Sample rows + column statistics** — `describe-tables` output plus a `SELECT … LIMIT 50` per table. Lowest tier; inference only. Every decision made at this tier is an assumption and MUST be logged.

## Entity vs descriptor vs measure — the decision matrix

For each column, walk this table in order. First match wins.

| Signal | Decision |
| --- | --- |
| Column is the table's natural key (alone or compound) | **Entity attribute** on this table (ID form); key form. Name = business noun, not code. |
| Column is a foreign key to another table's natural key (same or acronym-derived name; cardinality confirms) | Expression on the **referenced entity attribute** (multi-table); drives a `one_to_many` relationship via this table. |
| Column is a code/ID that does not match any known key (e.g. `region_preference = 'us-central'`) | **Entity attribute** with DESC form = the code itself (or a paired name column if present). Often a conformed dimension across facts. |
| Column is a human-readable label tied to an ID column in the same table (`tenant_id` + `tenant_name`) | **DESC form** on the ID's attribute. Not a separate attribute. |
| Column is a timestamp or date | **Date/time attribute**; consider hierarchy (Year > Quarter > Month > Day > Hour). Multiple timestamps on the same row = multiple time attributes with distinct roles. |
| Column is boolean / 0-1 flag | **Attribute** (dim) when used for filtering; **metric with `sum`** when used for counting ("# of SLA breaches"). Often both — create attribute, and a derived `SUM(flag)` metric with integer format. |
| Column is numeric and the value varies per row within the same entity-grain | **Metric.** Choose function per section below. |
| Column is numeric but constant across all rows for an entity (e.g. `monthly_commit_usd` per tenant) | **Attribute**, not a metric. It is a dimension attribute that happens to be numeric. Forcing SUM inflates it. |
| Column is free-text narrative | DESC form on the owning attribute; do **not** create a separate attribute. |
| Column is an audit / ingestion column (`load_ts`, `etl_batch_id`, `dw_updated_at`) | Skip entirely. |

### Aggregation function by column semantics

Never default to SUM blindly. Use the column name + sample distribution:

| Pattern / semantic | Function | Format | Notes |
| --- | --- | --- | --- |
| `*_count`, `*_qty`, `jobs_*`, `*_opened`, `*_impacted`, `*_submitted`, `*_completed`, `*_failed` | `sum` | integer / thousands | Counts are additive. Verify: `SUM(x)` at lowest grain equals `SUM(x)` at any rollup. |
| `*_usd`, `*_revenue`, `*_cost`, `*_commit`, `*_impact` (currency-valued) | `sum` if transactional; **`avg`** or treated as attribute if it's a stated rate on a dimension row | currency | `monthly_commit_usd` on a tenant row is an attribute. `estimated_impact_usd` on an incident row is a sum-able incident cost. |
| `*_hours`, `*_minutes`, `*_gb`, `*_tb` (additive quantity) | `sum` | fixed + unit suffix | Storage / compute volumes. |
| `avg_*`, `average_*`, `mean_*` | `avg` (of a pre-averaged column) | percent or fixed | Pre-aggregated. Cannot recover SUM-level truth from row-level data. Accept as AVG and document the limitation. |
| `*_pct`, `*_percentage`, `*_rate`, `*_share`, `utilization_*` | `avg` | percent | Percentage row-values are averages, not sums. |
| `p50_*`, `p95_*`, `p99_*`, `median_*` | `avg` (weighted if a weight column exists; otherwise plain avg) | fixed | Percentiles cannot be re-aggregated. Document the fidelity loss. |
| `max_*`, `min_*` | `max` / `min` | fixed | Propagate up as min/max rather than sum. |
| `*_score`, `*_index`, `risk_*`, `*_health` | `avg` | fixed | Scores are levels, not flows. |
| `*_ts`, `*_at`, `*_date` | not a metric | — | Time attributes only. |
| `*_flag`, `*_reported_*` (0/1) | `sum` (creates a count metric) + the attribute form on same column | integer | Name the metric `<Event> Count` not `<Flag> Sum`. |
| Derived ratios that appear in reference output (`success_rate`, `sla_uptime_pct`) | **compound metric** from two base metrics, not a stored column's AVG | percent | Computing `SUM(success)/SUM(total)` at each rollup is correct; AVG of the stored % is wrong at any non-lowest grain. |

## Grain detection

If the user didn't tell you the grain, infer it:

1. Pick the columns that look like natural keys (PK-ish names, high cardinality, non-null).
2. Sample `COUNT(*)` vs `COUNT(DISTINCT <candidate key combo>)`. Equal → grain found.
3. Confirm with a known reference number (row count of a reference report, known tenant × hour product).

Knowing the grain unlocks: (a) which columns are *attributes replicated down to grain* (and therefore belong on the dimension table, not this one, semantically), (b) which columns are true measures at this grain, (c) the correct join cardinality.

Common grain mistakes to catch before build:
- Treating a dimension-leaked column as a metric (per-hour `monthly_commit_usd`).
- Treating a compound-grain fact (tenant × hour × cluster) as if it were tenant-grained — leads to SUM inflation.
- Missing a latent grain column (e.g. `job_class`) that blows up cardinality after a join.

## Relationship inference

See `reference_mosaic_relationship_archetypes.md` for the 6 canonical shapes. The translation pass adds:

- **Cardinality probe.** For each candidate FK pair `(parent.key, child.fk)`, confirm `COUNT(DISTINCT parent.key) ≤ COUNT(DISTINCT child.fk)` and `each child.fk value appears in parent`. If the second fails, the relationship is not 1:many — usually a bridge or a missing parent row.
- **Conformed dimensions.** If a column name (e.g. `region`) appears in ≥2 fact tables as a descriptor, promote it to a single conformed attribute rather than per-fact duplicates.
- **Degenerate dimensions.** A code that lives only on the fact row with no lookup table (e.g. `severity = 'low|med|high'` on `incidents`) is still an attribute — just with its lookup table = the fact table.
- **Bridges.** An all-FK table (no descriptors, no measures) between two entities is a many-to-many. Declare explicitly; the auto-build heuristic will not infer it.
- **Cross-DB joins.** Mosaic in-memory materialization happily joins tables across distinct DB instances on a shared attribute key (e.g. `<entity>_id` lowercase on one instance vs `<ENTITY>_ID` uppercase on another). Declare the shared attribute explicitly; column-name case mismatches break auto-conformance (see `feedback_mosaic_relationship_wiring.md`). Applies to any pair of supported engines — Postgres, Snowflake, Oracle, BigQuery, SQL Server, Redshift, Databricks, Teradata.

## Inspection-only inference (no business context at all)

When the user provides no ERD, no narrative, no reference query — only `(instance, schema, tables)`:

1. Run `describe-tables` for every table in one login.
2. For each table: sample `SELECT * FROM t LIMIT 50` and `SELECT COUNT(*), COUNT(DISTINCT <each candidate key>)` via Trino / MCP `query`.
3. Classify every column with the matrix above using column name + sample distribution.
4. Infer grain; log the inferred natural key.
5. Infer FKs by shared column names across tables (case-insensitive, acronym-aware: `tenant_id` matches `TENANT_ID` and `TENANTID`). Confirm with a cardinality probe query before treating it as a relationship.
6. For every metric, pick the function via the semantic table. When two functions are plausible (`count` vs `sum` for a flag, `sum` vs `avg` for a currency), log both as alternatives in the assumptions log.
7. Write a structured `build-plan.json` + an assumptions log. Only then call `build`.

### Heuristic red flags

If any of these fire, pause and ask the user before building:

- A column's mean is 4–6 orders of magnitude larger than its median → likely an amount/rate misread; verify.
- A "fact" table has fewer rows than the dimension it supposedly hangs off → roles probably reversed.
- Two columns with the same business meaning but different types across tables (`tenant_id` BIGINT vs `TENANT_ID` VARCHAR) → conformance will fail silently.
- A timestamp column whose distinct count equals the row count → dimension-only table, no real time grain.
- Negative values in a column named like a count or duration → data-quality issue or wrong semantic; do not SUM until clarified (a previous validation CSV contained a negative count broadcast across tens of thousands of rows, which would have summed to a misleading value had it been treated as a plain additive measure).

## Validation hooks — prove the translation was right

Every build plan produces three categories of validation queries for `strategy-validation/SKILL.md`:

1. **Grain check.** `COUNT(*)` and `COUNT(DISTINCT <natural key>)` on each table — match against warehouse truth.
2. **Dimension rollup.** For each conformed attribute, `SUM(metric) GROUP BY attribute` compared against reference total. Catches under-joined relationships — rollup inflation / deflation.
3. **Aggregation sanity.** For each metric, verify its chosen function matches the reference: `SUM` metrics should equal the reference's column sum; `AVG` metrics should equal the reference's column mean (weighted by count if the CSV has grain duplication).

A build plan is not shippable until all three pass or every failure is mapped to a documented data-quality caveat.

## Artifact template

```json
{
  "model": {"name": "<model name>", "data_serve_mode": "in_memory"},
  "sources": [
    {"instance": "<db-instance-1 name>", "schema": "<schema-1>", "tables": ["<fact-table>", "<lookup-table>"]},
    {"instance": "<db-instance-2 name>", "schema": "<schema-2>", "tables": ["<dim-table>", "<other-fact-table>"]}
  ],
  "tables": {
    "<schema-1>.<fact-table>": {
      "grain": ["<natural-key-col>"],
      "entities": ["<BusinessEntity>"],
      "attributes": [{"name": "<Business Entity>", "columns": ["<id-col>"], "display_forms": ["<desc-col>"]}],
      "metrics": [{"name": "<Measure>", "column": "<numeric-col>", "function": "sum", "format": "integer"}]
    },
    "<schema-2>.<other-fact-table>": {
      "grain": ["<dim-fk>", "<secondary-fk>", "<time-col>"],
      "entities": ["<Dim> x <Secondary> x <TimeGrain>"],
      "attributes": [],
      "metrics": []
    }
  },
  "relationships": [
    {"parent": "<Parent Dim>", "child": "<Child Entity>", "type": "one_to_many",
     "relationship_table": "<schema>.<fact-table>",
     "reason": "<shared-fk-col> shared FK"}
  ],
  "derived_metrics": [],
  "assumptions": [
    {"scope": "<schema>.<table>.<col>", "assumption": "<what was inferred>",
     "signal": "<why — column pattern, sample stats, etc.>", "tier": "inspection-only"}
  ]
}
```

Hand this to `build_mosaic.py build-from-config` plus a dictionary JSON derived from the attributes/metrics sections; do not pass raw column lists.
