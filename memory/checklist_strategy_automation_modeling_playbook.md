---
name: Strategy Mosaic automation — modeling playbook (apply BEFORE writing any REST payload)
description: Mandatory design pass before `build_mosaic.py build` runs. Ties the durable modeling memories (foundations, attribute design, fact/metric design, relationship design, hierarchy design) to the concrete automation steps so auto-inference never ships a semantically wrong model. Use as a pre-build checklist — do not skip.
type: reference
---

The goal: stop shipping models with zero relationships, wrong aggregations, or mis-joined facts. Follow this playbook before `build_mosaic.py build` or any Modeling Service POSTs.

## 0. Before you start

- [ ] Confirm you have the inputs for every table: instance, schema, table name, full column list + datatypes. Use `list-datasources`, `list-namespaces`, `list-tables`, `describe-tables` (plural) to batch.
- [ ] Confirm the validation artifact (trusted CSV / SQL / reference model) exists. If not, ask the user — per `reference_data_modeling_foundations.md` stopping conditions.
- [ ] Decide data-serve mode up front: multi-DB inputs → `in_memory` (see `feedback_mosaic_multi_db_connect_live.md`). Single-DB → `connect_live` is fine.

## 1. Business-process + grain pass (`reference_data_modeling_foundations.md`)

For each input table, write down in one sentence:

- the business process ("hourly tenant GPU utilization", "cluster incidents", "tenant master")
- the grain ("one row per tenant-cluster-hour", "one row per incident", "one row per tenant")
- the additive behavior of every numeric column (additive / semi-additive / non-additive / ratio — see `reference_strategy_fact_metric_design.md`)

Stop and ask the user if:
- grain is ambiguous (e.g., "hourly" but multiple keys could be the compound key)
- a metric is non-additive (ratio, percentage, balance) — confirm whether AVG, SUM-of-parts, or level metric is the business definition
- SCD or time-variance may apply

## 2. Attribute plan (`reference_strategy_attribute_design.md` + `reference_strategy_schema_objects.md`)

For every column, classify it and assign a business name BEFORE generating payloads:

- **Entity key** — primary-key ID for the table's dimension. One per table. Key form = `45C11FA478E745FEA08D781CEA190FE5` if you want Mosaic universality.
- **Descriptor form** — display name / description that lives on the SAME table as the entity key. Attach as an additional form, not a separate attribute. Set as the default reportDisplay + browseDisplay.
- **Dimensional rollup** — low-cardinality descriptor that MANY entities share (Growth Tier, Segment, SLA Tier). Becomes its own attribute; relates to the entity as parent (many entities → one bucket).
- **Row-level attribute** — descriptor that varies per fact row and does NOT roll up under the entity (Capacity Mode at the hourly grain, Customer Reported Issue Flag per hourly row). Leave as a flat attribute on the fact table; do not force it into a hierarchy.
- **Fact column** — numeric that belongs in the metric plan, not the attribute plan.
- **Noise column** — ETL bookkeeping (SOURCE_SYSTEM, LOAD_TIMESTAMP). Skip.

When the same logical entity appears in multiple tables (Tenant in TENANTS + USAGE_HOURLY + tenant_service_hourly + incidents): it is ONE Mosaic attribute with multi-table form expressions, NOT four different attributes with the same name. `build_mosaic.py build` will reject duplicate names (8004e409) — if you hit this, the PATCH pattern in this session (see `memory/reference_mosaic_clone_pattern.md` + surgery script in tasks) is the fix. Better: pre-compute conformance intent before building and pass via dictionary.

**Case-sensitivity trap** (from `feedback_build_mosaic_conforming_attr_rules.md`): `tenant_id` (Neon lowercase) and `TENANT_ID` (Snowflake uppercase) DO NOT auto-conform in `build_mosaic.py`. You must either (a) feed the dictionary with consistent `name` values AND accept that conformance will only pick up same-case columns, then PATCH the attribute afterwards to add the remaining-case tables' expressions; or (b) pass an explicit ERD.

## 3. Fact + metric plan (`reference_strategy_fact_metric_design.md`)

For every numeric column, pick the aggregation function explicitly:

- **Counts / amounts / hours consumed / revenue / cost** → `sum`. Always additive at the source grain.
- **Percentages / rates / health scores / averages already in source column names (AVG_*, P95_*)** → `avg` is the safe default for display, BUT flag as "ratio-safety candidate": if the business definition is "time-weighted" or "job-weighted", rebuild as a compound metric (SUM(num) / SUM(denom)) or as a level metric in a follow-up pass. Never let auto-inference emit `sum` on a `pct` or `avg` column.
- **Snapshot / balance / as-of measures (Reserved GPU Count, Monthly Commit USD)** → semi-additive. `sum` across tenants is the portfolio roll-up; across time it double-counts. Flag for the user: do they want a level metric "at Tenant level"? Default to `sum` but document.
- **P95 / P99 / median columns** → auto `avg` of percentiles is wrong (average of percentiles is not a percentile) but often the only computationally available answer in-memory. Document this limitation; if precise p95 is required, fall back to warehouse-SQL view, not a Mosaic fact metric.

Emit metric descriptions that explain WHAT aggregates and AT WHAT GRAIN (Kimball discipline), e.g., "GPU Hours Consumed — SUM of hourly GPU hours; additive across tenant, cluster, hour."

## 4. Relationship plan (`reference_strategy_relationship_design.md`)

Enumerate every relationship using the decision tree in that doc. Group by *relationship_table* (the fact/bridge where the FK lives):

```
parent           child            relationship_table    type
---------------  ---------------  --------------------  ------------
Growth Tier      Tenant           TENANTS               one_to_many
Industry         Tenant           TENANTS               one_to_many
... (all TENANTS descriptors rolling up to Tenant)
Incident Type    Incident         incidents             one_to_many
Severity         Incident         incidents             one_to_many
... (all incidents descriptors rolling up to Incident)
Tenant           Incident         incidents             one_to_many   # dim → fact
Cluster          Incident         incidents             one_to_many   # dim → fact
```

Rules enforced by this plan:
- **Dim descriptor → entity on the same table** for every rollup attribute.
- **Entity (dim) → fact-table entity via the fact table** for every cross-table join (Tenant → Incident via incidents, Cluster → Incident via incidents).
- **Never declare a relationship that makes an attribute a child of itself** — that's how `build_mosaic.py` hit 8004ccdb in the initial build. The guard: a Tenant-conformed attribute should NOT be both parent and child of itself via different rel tables.
- **Each `PUT /attributes/{child}/relationships` replaces the child's entire relationship list.** If a child has multiple parents, send them all in one PUT (one relationships array), not one PUT per parent.
- **Conformed attributes do not need relationships between the tables they span** — the shared attribute IS the join. Do need relationships for the dim → fact direction where the child is a DIFFERENT attribute.

## 5. Security + access plan

- If the user asks for a row-level filter by a name (e.g., "Tenant = NovaForge AI"):
  - Use `predicate_element_list` (Shape B per `reference_mosaic_security_filter.md`) with `elementId = "h<display value>"`. This works without needing to resolve IDs or form subTypes.
  - `predicate_form_qualification` on a CUSTOM DESC form fails with `attribute_form_custom` (8004c767 "not found in metadata"). Use Shape B instead.
- User resolution: `/api/users?nameBegins=…` or `?abbreviationBegins=…` — `searchTerm` is broken.
- Member assignment path is `/api/dataModels/{id}/securityFilters/{sfId}/members` with `path: "/Members"` (leading slash, capital M).

## 6. Publish readiness gate (`feedback_mosaic_publishable_datatypes.md`)

Before `publish`: every column in `physicalTable.columns[i].dataType` AND every column inside the pipeline JSON must carry UI-clean types, not warehouse-catalog sentinels.

Fast check: run `GET /api/model/dataModels/{id}/tables/{tid}?showColumns=true` and look for any of: `variable_length_string`, `fixed_length_string`, `precision=-1`, `scale=-2147483648`, `binary`, `unsigned`, `decimal` with warehouse precision (38). Any of these → publish will stall with `-2147212544` (parallel-mode stall) and never materialize.

**Fix**: remap per the table in `feedback_mosaic_publishable_datatypes.md`. Either via a dedicated dataType-cleanup pass on the existing tables, or by cloning from a known-good REF model (the memory's recommended pattern).

This gate is the difference between "Mosaic accepts the POST" and "the cube actually materializes and Trino can query it." Do not declare a build done until the published cube appears in `get_mosaic_models` for the Shared Studio (or equivalent) catalog.

## 7. Validation plan (`reference_strategy_model_validation.md`)

Minimum: compare at least 3 aggregates between the validation artifact and the model, at the grain the artifact implies:
- grand totals (sum / avg) for every primary metric
- by entity rollup (e.g., by Tenant for a tenant-scoped CSV)
- spot-check one or two specific dimensional cells (e.g., Tenant × Severity row)

Keep the comparator scripted and repeatable. See `reference_strategy_data_validation.md` for the paired-query pattern.

## 8. Durable artifacts

Save the dictionary JSON, the ERD / relationship plan, and the dataType-cleanup output under `captures/<run-date>/` so a future rebuild can re-apply the exact modeling plan. These live outside durable memory (which should stay tenant-agnostic).

---

## Anti-patterns that this playbook prevents

- Zero-relationship models with "22 attributes, 33 metrics, 0 relationships" — the opposite of what's wanted. Fix: step 4 is not optional.
- SUM on a PCT column, AVG on a revenue column, COUNT on a snapshot measure. Fix: step 3 is not optional.
- "Tenant" duplicated 3–4 times because the build script couldn't reconcile mixed-case FKs. Fix: step 2's conformance pre-pass + PATCH follow-up.
- Publish stalls silently and validation runs against an empty cube. Fix: step 6 gate is mandatory.
