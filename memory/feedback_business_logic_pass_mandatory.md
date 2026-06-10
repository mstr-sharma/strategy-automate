---
name: Business-logic translation pass is mandatory before every Mosaic build
description: Never run build_mosaic.py build without first producing the business-logic translation artifact (entities, grain, metrics with aggregation, relationships, assumptions). Auto-inference from column names alone produces under-joined or inflation-prone models even when the helper completes successfully.
type: feedback
---

**Rule.** Before calling `build_mosaic.py build` (or any equivalent flow) on a set of warehouse tables, produce the `build-plan.json` + assumptions log described in `reference_mosaic_business_logic_translation.md`. If the user provided no business context at all, the inspection-only inference path is still required — it is not optional.

**Why:** the helper's built-in inference (friendly-title column names, SUM per numeric column, shared-column relationships) ships models that look complete but are semantically wrong in common ways:

- Percent and rate columns get SUMmed, so any rollup of a percentage or utilization column is off by factors of the rollup size.
- Per-dimension constants that happen to be numeric (e.g., a contract amount on a customer row replicated to every hourly fact) become sum-metrics and grow linearly with row count.
- Pre-aggregated statistics (`p95_*`, `median_*`) are SUMmed, producing meaningless totals that still numerically "look like" metrics.
- Flag columns end up both as attributes (good) and SUM-aggregated metrics named `Total <Flag Name> (<Table>)` (bad naming, unclear semantic).
- Shared column names across DBs with different casing (`<entity>_id` vs `<ENTITY>_ID`) silently fail to conform, so the model under-joins and totals are wrong — but the build helper reports success.
- Conformed dimensions (region, severity) get duplicated across tables instead of promoted to a single attribute, fragmenting slicing.

Each of these failure modes completes the build with 2xx status codes. The first time anyone queries the model, the numbers disagree with the reference source by amounts that are hard to debug after the fact.

**How to apply:**

1. Run `describe-tables` (plural, one login) for every source table.
2. If the user supplied any business artifact (narrative, ERD, dictionary, classic model, reference CSV/report), parse it first and write it into the plan. Use the intake ladder in `reference_mosaic_business_logic_translation.md`.
3. If no artifact was supplied, do the inspection-only pass — for every column, classify with the decision matrix; for every metric, pick `sum/avg/min/max/count` per the semantic table; for every candidate relationship, run a cardinality probe via Trino / MCP `query` before declaring it.
4. Write an assumptions log listing every non-trivial inference. At minimum: grain of each table, aggregation function of each metric that isn't an obvious additive count, every inferred relationship, every conformed attribute.
5. Only then invoke `build`. Pass the dictionary and (if needed) ERD files derived from the plan.
6. After build, the validation pass targets the assumptions log specifically — grain checks, dimension rollups, aggregation-sanity comparisons against the reference source. Do not call the build shippable until every assumption is validated or its failure is documented.

**Red-flag gate.** If any of these are present, stop and confirm with the user before building rather than guessing:

- Row counts that don't match an obvious `entities × hours` product.
- Negative values in count / duration / quantity columns.
- Percent-formatted columns that are stored numerically without a rate denominator.
- Tables from multiple DB instances with column-name case or type mismatches on the candidate join key.
- A validation CSV whose row count differs from the natural `fact × dim` cardinality (suggests a broadcast / cartesian in how it was produced — the model must reproduce that same broadcast to match).

**Do not skip the assumptions log even when the user gave full business context.** Explicit context covers entities, grain, and measures, but rarely covers every aggregation-function choice or every relationship cardinality. Log what the user said vs what was inferred, separately.

**Related:**
- `reference_mosaic_business_logic_translation.md` — the playbook this rule enforces.
- `feedback_mosaic_build_quality.md` — 11 ship-bar rules that apply after the plan is built.
- `feedback_mosaic_legacy_as_blueprint.md` — when a classic model exists, mirror it instead of inferring.
- `reference_mosaic_relationship_archetypes.md` — the 6 canonical join shapes the plan must pick from.
- `feedback_mosaic_ship_bar.md` — per-attribute / per-metric form & format defaults (plus the full ship-bar checklist), applied post-plan.
