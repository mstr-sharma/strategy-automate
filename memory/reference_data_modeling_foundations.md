---
name: Kimball dimensional modeling foundations for Strategy
description: Kimball-first dimensional modeling principles — star and snowflake schemas are the canonical topology for Strategy's SQL engine. Covers grain declaration, conformed dimensions, fact-table patterns (transaction/periodic snapshot/accumulating snapshot/factless), dimension patterns (conformed/role-playing/degenerate/junk/SCD/bridge), the star-vs-snowflake-vs-galaxy decision, and anti-patterns that break Strategy's join inference.
type: reference
tags: [kimball, modeling, grain, conformed-dim, star, snowflake, mosaic, classic]
---

Use this as the first modeling lens before touching Strategy objects or REST payloads. **Strategy's SQL engine is built around Kimball star/snowflake schemas — it assumes one fact grain per query, conformed dims for slicing, and lookup tables per attribute. Non-Kimball shapes (EAV, one-big-table, graph) should be reshaped upstream before modeling, not accommodated in the semantic layer.**

## Why Kimball for Strategy

Strategy (Mosaic + classic) generates SQL by picking a single fact table per metric, joining it to every dimension the user selected, and aggregating. That pattern works cleanly on star/snowflake topologies and degrades on anything else:

- **Star schema** — one fact in the middle, dims on the spokes. Strategy's default. Every metric at one grain, every attribute on one dim, every join is a single FK-to-PK hop.
- **Snowflake schema** — dim rows further normalize into parent dims (Product → Category → Category Group). Strategy handles this natively via attribute parent-child relationships and user hierarchies; the chain becomes a drill path.
- **Galaxy / conformed constellation** — multiple facts sharing the same dims. This is where **conformed dimensions** become load-bearing: the same `Customer` attribute joins Orders, Shipments, and Returns facts. Strategy enforces conformance via multi-table attribute expressions.
- **Bridge (many-to-many)** — an intermediate table with only FKs resolves many-to-many relationships (e.g., one order line → many promotions). Declare explicitly; Strategy does not infer bridges.
- **Non-Kimball** — EAV, key-value, document, graph, one-big-table (OBT). Either reshape upstream or expect the semantic layer to be a thin pass-through with no cross-subject rollups.

## Core mental model — three layers

A Strategy semantic model is a contract between:

1. Business questions
2. Physical warehouse structures
3. Governed semantic objects

Treat the model as three layers:

1. **Business logical model** — process, grain, dimensions, facts, hierarchies, and time semantics.
2. **Physical warehouse mapping** — tables, keys, joins, bridges, snapshots, and source-system boundaries.
3. **Strategy semantic objects** — attributes, forms, facts, metrics, relationships, hierarchies, transformations, and security rules.

Never jump straight from table names to object payloads. Form a modeling plan first.

## Start from a business process

Good starting point:

- "Build an order-line sales model where one row represents one sold product on one order line, analyzable by day, customer, product, store, and channel."

Bad starting point:

- "Build a model from ORDER_HDR, ORDER_LINE, CUSTOMER, PRODUCT."

Facts normally represent a business process or event stream: orders, shipments, invoices, balances, sessions, support cases, or inventory snapshots.

## Declare grain before dimensions and facts

The grain states what one row means. It is the binding contract for every downstream object. This is the single most important decision you make — get it wrong and every metric rollup is off.

Examples:

- Retail sales: one row per order line
- Shipment: one row per shipped package
- Inventory snapshot: one row per product × store × day
- Web analytics: one row per session
- Account balance: one row per account × day snapshot

Rules:

- Do not mix grains in one fact table.
- Do not attach facts that are not true at the declared grain.
- Do not create relationships that imply a lower or higher grain than the source supports.
- Prefer atomic grain for the base truth; use cubes or aggregates for performance.

**Grain-detection signal:** `COUNT(*) == COUNT(DISTINCT <candidate natural key>)` on a warehouse sample. If equal, that's the grain.

## Separate dimensions from facts

Facts answer "how much" or "how many." Dimensions answer "by what," "which," "who," "where," "when," or "why."

Examples:

- `Sales Amount` → fact
- `Quantity Sold` → fact
- `Order Count` → usually a metric (derived), not a stored column
- `Customer`, `Product`, `Store`, `Month`, `Fiscal Year` → attributes / dimensions

**Rule of thumb:** if the column VARIES per fact row in a way a user would GROUP BY, it's an attribute. If a user would SUM / AVG / COUNT it, it's a fact. Numeric columns that are CONSTANT within an entity (e.g., `monthly_commit_usd` on a customer) are attributes, not facts — summing them inflates.

## Metrics are governed calculations

Facts are usually physical numeric columns. Metrics are the reusable analytical definitions users consume.

Examples:

- `Revenue = Sum(Sales Amount)`
- `Cost = Sum(Cost Amount)`
- `Gross Margin = Revenue - Cost`
- `Gross Margin % = Gross Margin / Revenue` (compound — SUM(num) / SUM(denom), never AVG of row-level ratio)

Distinguish raw measurable columns from the governed metrics that appear in the user-facing model.

## Additivity — the aggregation contract

Every fact column has an additivity classification. This drives the metric `function`:

| Type | Examples | Aggregation |
| --- | --- | --- |
| **Additive** | Sales Amount, Units Sold, Jobs Completed | `SUM` along every dimension |
| **Semi-additive** | Inventory On Hand, Account Balance, Reserved Capacity | `SUM` along non-time dims, `AVG` / `LAST` / `FIRST` along time |
| **Non-additive** | Percent, Rate, Utilization, Margin % | Never `SUM`. Either `AVG` (lossy) or recompute as compound metric SUM(num)/SUM(denom) |
| **Derived / ratio** | Same as non-additive | Compound metric over two base metrics |

**Never default to SUM blindly.** Auto-inference from column names alone is the #1 source of semantically wrong models.

## Fact-table patterns (Kimball canonical)

- **Transaction fact** — one row per event. Most common. Additive in every metric.
- **Periodic snapshot fact** — one row per entity per period (day/week/month). Semi-additive across time.
- **Accumulating snapshot fact** — one row per process instance, updated as the process moves through stages (order → ship → deliver → return). Multiple date columns per row (role-playing dims).
- **Factless fact** — one row records occurrence or coverage with no stored measure. Metrics are counts of rows.

## Dimension patterns (Kimball canonical)

- **Conformed dimension** — reused across multiple fact tables at compatible grain. Strategy expresses this as ONE attribute with multi-table expressions (not N separate attributes).
- **Role-playing dimension** — same entity appears in multiple roles (Order Date vs Ship Date → both are Date). Strategy expresses with distinct attribute names sharing the same lookup table via aliases.
- **Degenerate dimension** — transaction identifier with no lookup table (invoice number, order number on the line). The attribute's lookup table = the fact table.
- **Junk dimension** — low-cardinality flags clustered into one dim to avoid dimension explosion.
- **Slowly Changing Dimension (SCD)** — descriptors change over time. Type 1 overwrite, Type 2 history row, Type 3 prior-value column. Choose based on whether history matters for reporting.
- **Bridge / many-to-many dimension** — one fact row maps to multiple members (multi-promotion order, multi-category product). Requires explicit bridge table + allocation logic.

## Schema topology decision

Before building, classify EVERY input table as one of:

- **Fact** — numeric measures at a declared grain, FKs to dims.
- **Dimension** — descriptor rows keyed by a natural key.
- **Bridge** — all-FK table, no descriptors, no measures.
- **Snowflake parent dim** — dim whose PK is referenced by another dim.
- **Degenerate dim** — a code on the fact row with no lookup table.
- **Noise / ETL bookkeeping** — skip (SOURCE_SYSTEM, LOAD_TIMESTAMP).

Then declare the overall topology: `star | snowflake | galaxy | bridge-heavy | non-Kimball`. **Non-Kimball topologies should stop-and-confirm with the user** — they won't map cleanly onto Strategy's join engine.

## Anti-pattern catalog

| Anti-pattern | Symptom in Strategy | Fix |
| --- | --- | --- |
| No declared grain | Totals drift by report level; SUM doubles when you add a dim | Declare grain and realign facts |
| Mixed-grain fact table | Duplicated totals or missing detail | Split into transaction / snapshot / aggregate facts |
| Conformed dim declared as N attributes | Cannot slice a fact across shared dims; "Model has no joins" | Promote to ONE multi-table attribute (see `feedback_mosaic_relationship_wiring.md`) |
| Name-only joins (no relationships) | Unstable SQL, Cartesian inflation, Mosaic UI shows disconnected star | Declare relationships explicitly |
| Everything-hierarchy | Confusing browse paths, irrelevant drill options | Split by subject area into multiple user hierarchies |
| Many-to-many without bridge | Totals multiply by the degree of the M:N | Add bridge table + allocation logic |
| Ratio of row-level ratios (`AVG(pct)`) | Incorrect percentages at any non-lowest grain | Compound metric: `SUM(num) / SUM(denom)` |
| Calendar / fiscal confusion | LY/YoY comparisons off by a quarter | Model separate calendars + transformations (`reference_strategy_time_modeling.md`) |
| Mutable descriptions as IDs | Duplicate elements, element drift across refreshes | Use stable keys; expose descriptions as forms |
| OBT (one big table, everything denormalized) | Strategy cannot reliably pick a fact; GROUP BY explodes; metric rollups are ambiguous | Reshape upstream into facts + dims before modeling |
| Non-conformed dims on related facts | Cannot produce a single report combining both facts by shared dim | Promote to conformed dim; add multi-table expressions |

## Stopping conditions — ask the user before guessing

Ask for clarification when:

- Multiple grains are plausible (compound natural keys, unclear what "one row" means).
- Business definitions of core metrics are unclear (what is "active customer"?).
- Fiscal calendar rules are unknown or differ from calendar year.
- Many-to-many relationships would affect totals materially.
- Security semantics are ambiguous (which attribute is the isolation boundary?).
- Topology is non-Kimball (OBT, EAV, graph) — reshape upstream is usually cheaper than building around it.

## Related

- `reference_strategy_schema_objects.md` — how Kimball concepts map to Strategy object classes.
- `reference_strategy_attribute_design.md` — attribute forms, conformance, role-playing, SCD encoding.
- `reference_strategy_fact_metric_design.md` — metric additivity, ratio safety, governed measures.
- `reference_strategy_relationship_design.md` — cardinality, bridge logic, orphan detection.
- `reference_strategy_hierarchy_design.md` — drill paths, entry points, subject-area separation.
- `reference_strategy_time_modeling.md` — calendar/fiscal roles, transformations.
- `feedback_mosaic_relationship_wiring.md` — conformed-dim encoding in Mosaic + the error codes when it breaks.
