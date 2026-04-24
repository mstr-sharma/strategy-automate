---
name: Strategy Mosaic automation — modeling playbook (apply BEFORE writing any REST payload)
description: Mandatory design pass before `build_mosaic.py build` runs. Ties the durable modeling memories (foundations, attribute design, fact/metric design, relationship design, hierarchy design) to the concrete automation steps so auto-inference never ships a semantically wrong model. Use as a pre-build checklist — do not skip.
type: reference
---

The goal: stop shipping models with zero relationships, wrong aggregations, or mis-joined facts. Follow this playbook before `build_mosaic.py build` or any Modeling Service POSTs. **Kimball-first:** Strategy's engine is built for star/snowflake schemas and conformed dimensions; every step below enforces a Kimball invariant.

## 0. Before you start — topology + inputs

- [ ] Confirm you have the inputs for every table: instance, schema, table name, full column list + datatypes. Use `list-datasources`, `list-namespaces`, `list-tables`, `describe-tables` (plural) to batch.
- [ ] Confirm the validation artifact (trusted CSV / SQL / reference model) exists. If not, ask the user — per `reference_data_modeling_foundations.md` stopping conditions.
- [ ] Decide data-serve mode up front: multi-DB inputs → `in_memory` (see `feedback_mosaic_multi_db_connect_live.md`). Single-DB → `connect_live` is fine.
- [ ] **Classify every table as fact / dim / bridge / snowflake-parent-dim / degenerate-dim / noise.** Then declare the overall topology: `star | snowflake | galaxy | bridge-heavy | non-Kimball`. If non-Kimball, STOP and confirm with the user — Strategy's join engine does not degrade gracefully on EAV / OBT / graph shapes. See `reference_data_modeling_foundations.md`.
- [ ] **Enumerate conformed dimensions.** Any entity that appears in ≥2 fact tables is a conformed dim candidate; it MUST be modeled as ONE attribute with multi-table expressions, not N attributes with the same name. This is the Kimball invariant that Strategy enforces via `8004ccdb` / `8004e409` when violated.

## 1. Business-process + grain pass (`reference_data_modeling_foundations.md`)

For each input table, write down in one sentence:

- the business process ("hourly service utilization", "support events", "customer master")
- the grain ("one row per customer-resource-hour", "one row per event", "one row per customer")
- the additive behavior of every numeric column (additive / semi-additive / non-additive / ratio — see `reference_strategy_fact_metric_design.md`)

Stop and ask the user if:
- grain is ambiguous (e.g., "hourly" but multiple keys could be the compound key)
- a metric is non-additive (ratio, percentage, balance) — confirm whether AVG, SUM-of-parts, or level metric is the business definition
- SCD or time-variance may apply

## 2. Attribute plan (`reference_strategy_attribute_design.md` + `reference_strategy_schema_objects.md`)

For every column, classify it and assign a business name BEFORE generating payloads:

- **Entity key** — primary-key ID for the table's dimension. One per table. Key form = `45C11FA478E745FEA08D781CEA190FE5` if you want Mosaic universality.
- **Descriptor form** — display name / description that lives on the SAME table as the entity key. Attach as an additional form, not a separate attribute. Set as the default reportDisplay + browseDisplay.
- **Dimensional rollup** — low-cardinality descriptor that MANY entities share (Segment, Tier, Category). Becomes its own attribute; relates to the entity as parent (many entities → one bucket).
- **Row-level attribute** — descriptor that varies per fact row and does NOT roll up under the entity (a per-hour status code, a per-row flag). Leave as a flat attribute on the fact table; do not force it into a hierarchy.
- **Fact column** — numeric that belongs in the metric plan, not the attribute plan.
- **Noise column** — ETL bookkeeping (SOURCE_SYSTEM, LOAD_TIMESTAMP). Skip.

When the same logical entity appears in multiple tables (e.g., `<Entity>` in a dim table + 2–3 fact tables): it is ONE Mosaic attribute with multi-table form expressions, NOT N different attributes with the same name. `build_mosaic.py build` will reject duplicate names (8004e409) — if you hit this, the PATCH pattern in this session (see `memory/reference_mosaic_clone_pattern.md` + surgery script in tasks) is the fix. Better: pre-compute conformance intent before building and pass via dictionary.

**Case-sensitivity trap** (from `feedback_mosaic_relationship_wiring.md`): `<entity>_id` (lowercase, typical for Postgres) and `<ENTITY>_ID` (uppercase, typical for Snowflake/Oracle) DO NOT auto-conform in `build_mosaic.py`. You must either (a) feed the dictionary with consistent `name` values AND accept that conformance will only pick up same-case columns, then PATCH the attribute afterwards to add the remaining-case tables' expressions; or (b) pass an explicit ERD.

## 3. Fact + metric plan (`reference_strategy_fact_metric_design.md`)

For every numeric column, pick the aggregation function explicitly:

- **Counts / amounts / quantities / revenue / cost** → `sum`. Always additive at the source grain.
- **Percentages / rates / scores / averages already in source column names (AVG_*, P95_*)** → `avg` is the safe default for display, BUT flag as "ratio-safety candidate": if the business definition is weighted (time-weighted, volume-weighted), rebuild as a compound metric (SUM(num) / SUM(denom)) or as a level metric in a follow-up pass. Never let auto-inference emit `sum` on a `pct` or `avg` column.
- **Snapshot / balance / as-of measures (inventory on hand, contracted commitment amount, reserved capacity count)** → semi-additive. `sum` across entities at the snapshot grain is the portfolio roll-up; `sum` across time double-counts. Flag for the user: do they want a level metric "at <Entity> level"? Default to `sum` but document.
- **P95 / P99 / median columns** → auto `avg` of percentiles is wrong (average of percentiles is not a percentile) but often the only computationally available answer in-memory. Document this limitation; if precise p95 is required, fall back to warehouse-SQL view, not a Mosaic fact metric.

Emit metric descriptions that explain WHAT aggregates and AT WHAT GRAIN (Kimball discipline), e.g., "Units Sold — SUM of hourly units; additive across Customer, Product, hour."

## 4. Relationship plan (`reference_strategy_relationship_design.md`)

Enumerate every relationship using the decision tree in that doc. Group by *relationship_table* (the fact/bridge where the FK lives):

```
parent             child            relationship_table      type
-----------------  ---------------  ----------------------  ------------
Segment            Customer         CUSTOMER                one_to_many
Country            Customer         CUSTOMER                one_to_many
... (all CUSTOMER descriptors rolling up to Customer)
Event Type         Event            EVENT_FACT              one_to_many
Severity           Event            EVENT_FACT              one_to_many
... (all EVENT_FACT descriptors rolling up to Event)
Customer           Event            EVENT_FACT              one_to_many   # dim → fact
Resource           Event            EVENT_FACT              one_to_many   # dim → fact
```

Rules enforced by this plan:
- **Dim descriptor → entity on the same table** for every rollup attribute.
- **Entity (dim) → fact-table entity via the fact table** for every cross-table join (Customer → Event via EVENT_FACT, Resource → Event via EVENT_FACT).
- **Never declare a relationship that makes an attribute a child of itself** — that's how `build_mosaic.py` hit 8004ccdb in a prior multi-DB build. The guard: a conformed attribute should NOT be both parent and child of itself via different rel tables.
- **Each `PUT /attributes/{child}/relationships` replaces the child's entire relationship list.** If a child has multiple parents, send them all in one PUT (one relationships array), not one PUT per parent.
- **Conformed attributes do not need relationships between the tables they span** — the shared attribute IS the join. Do need relationships for the dim → fact direction where the child is a DIFFERENT attribute.

## 5. Security + access plan

- If the user asks for a row-level filter by a name (e.g., "Region = EMEA" or "Customer = Acme Corp"):
  - Use `predicate_element_list` (Shape B per `reference_mosaic_security_filter.md`) with `elementId = "h<display value>"`. This works without needing to resolve IDs or form subTypes.
  - `predicate_form_qualification` on a CUSTOM DESC form fails with `attribute_form_custom` (8004c767 "not found in metadata"). Use Shape B instead.
- User resolution: `/api/users?nameBegins=…` or `?abbreviationBegins=…` — `searchTerm` is broken.
- Member assignment path is `/api/dataModels/{id}/securityFilters/{sfId}/members` with `path: "/Members"` (leading slash, capital M).

## 6. Publish readiness gate (`feedback_mosaic_publishable_datatypes.md`)

Before `publish`: every column in `physicalTable.columns[i].dataType` AND every column inside the pipeline JSON must carry UI-clean types, not warehouse-catalog sentinels.

Fast check: run `GET /api/model/dataModels/{id}/tables/{tid}?showColumns=true` and look for any of: `variable_length_string`, `fixed_length_string`, `precision=-1`, `scale=-2147483648`, `binary`, `unsigned`, `decimal` with warehouse precision (38). Any of these → publish will stall with `-2147212544` (parallel-mode stall) and never materialize.

**Fix**: remap per the table in `feedback_mosaic_publishable_datatypes.md`. Either via a dedicated dataType-cleanup pass on the existing tables, or by cloning from a known-good REF model (the memory's recommended pattern).

This gate is the difference between "Mosaic accepts the POST" and "the cube actually materializes and Trino can query it." Do not declare a build done until the published cube appears in `get_mosaic_models` for the Shared Studio (or equivalent) catalog.

## 7. Validation plan (`reference_strategy_data_validation.md`)

Minimum: compare at least 3 aggregates between the validation artifact and the model, at the grain the artifact implies:
- grand totals (sum / avg) for every primary metric
- by entity rollup (e.g., by `<Entity>` for an entity-scoped CSV)
- spot-check one or two specific dimensional cells (e.g., `<Entity>` × `<Category>` row)

Keep the comparator scripted and repeatable. See `reference_strategy_data_validation.md` for the paired-query pattern.

## 8. Durable artifacts

Save the dictionary JSON, the ERD / relationship plan, and the dataType-cleanup output under `captures/<run-date>/` so a future rebuild can re-apply the exact modeling plan. These live outside durable memory (which should stay tenant-agnostic).

---

## Anti-patterns that this playbook prevents

- Zero-relationship models with "22 attributes, 33 metrics, 0 relationships" — the opposite of what's wanted. Fix: step 4 is not optional.
- SUM on a PCT column, AVG on a revenue column, COUNT on a snapshot measure. Fix: step 3 is not optional.
- A conformed entity (e.g. `<Entity>`) duplicated 3–4 times because the build script couldn't reconcile mixed-case FKs. Fix: step 2's conformance pre-pass + PATCH follow-up.
- Publish stalls silently and validation runs against an empty cube. Fix: step 6 gate is mandatory.
