---
name: Kimball dimensional modeling foundations for Strategy
description: The single Kimball design file — dimensional modeling principles (grain, conformed dims, fact/dimension patterns, star-vs-snowflake-vs-galaxy, additivity, anti-patterns) PLUS the Strategy design sections built on them (Kimball→object-class map, attribute design, fact/metric design, relationship design, hierarchy design, time modeling). Load whole for any modeling task.
type: reference
tags: [kimball, modeling, grain, conformed-dim, star, snowflake, mosaic, classic]
---

Use this as the first modeling lens before touching Strategy objects or REST payloads. **Strategy's SQL engine is built around Kimball star/snowflake schemas — it assumes one fact grain per query, conformed dims for slicing, and lookup tables per attribute. Non-Kimball shapes (EAV, one-big-table, graph) should be reshaped upstream before modeling, not accommodated in the semantic layer.**

## Contents

1. Kimball principles — why Kimball, three-layer mental model, business process, grain, facts vs dims, governed metrics, additivity, fact-table patterns, dimension patterns, topology decision, anti-pattern catalog, stopping conditions.
2. **Strategy schema objects (Kimball → object-class map)** — tables, attributes, facts, metrics, relationships, hierarchies, transformations, security objects.
3. **Attribute design** — forms, conformance, role-playing, degenerate dims, SCDs, naming, review checks.
4. **Fact and metric design** — fact rules, count patterns, ratio safety, level-aware and transformation metrics, review checks.
5. **Relationship design** — decision tree, cardinality/orphan SQL probes, many-to-many safety, Mosaic write safety.
6. **Hierarchy design** — drill paths, entry points, anti-patterns, review questions.
7. **Time modeling** — calendar/fiscal decisions, date roles, transformations, review checks.

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
- `Units Sold = Sum(Quantity Sold)`
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
| Calendar / fiscal confusion | LY/YoY comparisons off by a quarter | Model separate calendars + transformations (see "Time modeling" section below) |
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

---

# Strategy schema objects (Kimball → object-class map)

Use this section to translate conceptual modeling decisions into Strategy object families.

## Tables

Tables are the physical source of expressions. Common roles:

- lookup tables: dimensional keys and descriptors
- fact tables: measurements at the declared grain
- relationship tables: parent-child or bridge mapping
- transformation tables: comparative period mapping
- aggregate tables: higher-level summaries
- partition tables: horizontally split storage

Agent rule: inspect columns, candidate keys, null rates, row counts, and join cardinalities before object creation.

## Attributes (object class)

Attributes represent business entities or levels. They usually contain:

- ID form: stable join / element identity
- description form: user-facing label
- additional forms: code, long description, sort order, status, external key
- expressions: table-column mappings

Rules:

- every attribute needs a stable identifier
- prefer surrogate or business-stable keys over mutable names
- do not use descriptions as IDs unless uniqueness is proven
- add expressions on every table needed for joins or relationship resolution

## Facts (object class)

Facts expose measurable columns into the semantic layer.

Rules:

- facts should be numeric or truly measurable
- text context belongs in attributes or forms, not facts
- record additive behavior explicitly
- avoid facts whose meaning changes by row type unless row type is modeled

## Metrics (object class)

Metrics are reusable semantic calculations. Common forms:

- base metric
- compound metric
- ratio metric
- count / distinct count metric
- level-aware metric
- transformation metric

Rules:

- expose named governed metrics, not a combinatorial explosion of raw aggregations
- define aggregation, null handling, and display format explicitly
- for ratios, aggregate numerator and denominator first, then divide

## Relationships (object class)

Relationships define how attributes constrain and roll up to one another.

Examples:

- Day → Month → Quarter → Year
- Product → Subcategory → Category
- City → State → Country

Rules:

- validate cardinality with data, not just names
- do not create a relationship only because two tables can join
- use a bridge pattern for many-to-many paths

## Hierarchies (object class)

Hierarchies organize attributes for browse, drill, and discoverability.

Rules:

- design hierarchies from user navigation, not just physical joins
- not every true relationship belongs in a visible hierarchy
- keep unrelated subject areas separate unless users routinely drill across them

## Transformations (object class)

Transformations model governed comparative mappings such as prior month, prior year, or fiscal offsets.

Rules:

- use transformations for reusable comparisons instead of embedding custom offsets in many metrics
- validate transformations with known sample dates
- do not assume fiscal offsets equal Gregorian offsets

## Security-related modeling objects

Security filters and ACLs are governance objects, but they still depend on sound modeling:

- row-level security assumes stable attribute identity and rollup paths
- object ACLs assume the right browse surfaces exist
- security smoke tests belong in the validation suite for shippable models

---

# Attribute design

Attributes are the backbone of filtering, grouping, drilling, element identity, and row-level security.

## Minimum attribute contract

Every attribute should define:

- business name
- business definition
- stable ID form
- user-facing description form when available
- lookup table or source table
- expressions on all required tables

## Form design

Typical forms:

- `ID`
- `DESC`
- code / SKU / external key
- long description
- sort form
- status or type form

Rules:

- keep `ID` stable and non-display-oriented
- keep `DESC` user-friendly
- add sort forms when alphabetical display is not the business order
- keep form names business-readable for consumer-grade output

## Conformed dimensions (attribute encoding)

Use one semantic attribute when the same entity is shared across processes such as:

- Customer across orders, invoices, and support
- Product across sales, returns, and inventory
- Date across nearly all facts

Rules:

- use one semantic name
- ensure compatible key definitions
- add the required expressions on each relevant table
- resolve case mismatch and source naming drift before relationship creation

## Role-playing dimensions (attribute encoding)

Use separate roles when the same entity appears multiple times in one process.

Examples:

- Order Date, Ship Date, Delivery Date
- Billing Customer, Shipping Customer
- Origin Airport, Destination Airport

Rules:

- separate roles when filter semantics would otherwise be ambiguous
- use explicit business role names

## Degenerate dimensions (attribute encoding)

Use when a transaction identifier has analytical value but no separate lookup table.

Examples:

- Order Number
- Invoice Number
- Ticket Number

Rules:

- model as an attribute if users filter, browse, or count by it
- avoid making high-cardinality transaction IDs default browse entry points

## Slowly changing dimensions (attribute encoding)

Choose deliberately:

- Type 1: overwrite history
- Type 2: preserve history with effective dating and surrogate keys
- Type 3: limited alternate-history columns

Rules:

- decide whether users need current view, historical view, or both
- use surrogate keys for Type 2 joins when facts must bind to historical versions
- expose current and historical descriptors deliberately

## Naming rules

- use business names, not raw column names
- avoid cryptic abbreviations unless users already rely on them
- keep role-playing names explicit
- avoid ID-as-display output

## Attribute review checks

- Does the attribute have a stable ID?
- Does the display form match business language?
- Are all needed table expressions present?
- Is this truly one attribute, or are there multiple roles?
- Will this attribute behave correctly in rollups and security filters?

---

# Fact and metric design

Facts expose measurable columns. Metrics encode the governed analytical definitions users consume.

## Fact design rules

- facts should be numeric, measurable, and true at the declared grain
- document additive behavior: additive, semi-additive, or non-additive (classes and examples in "Additivity — the aggregation contract" above)
- capture the fact level from the table's dimensional keys
- avoid exposing columns whose meaning changes by row type unless that row type is modeled

## Metric design rules

Prefer governed reusable metrics (canonical examples in "Metrics are governed calculations" above: Revenue, Units Sold, Gross Margin, Gross Margin %).

Rules:

- define null handling explicitly when material
- assign user-facing number / currency / percent formats
- expose business names instead of many raw aggregation variants

## Count patterns

- row count metrics are valid for factless facts and event tables
- distinct counts need explicit business intent
- do not assume `Count(Attribute)` and `Count(Distinct Attribute)` are interchangeable

## Ratio safety

For ratios:

- aggregate numerator and denominator first
- divide after aggregation
- do not average row-level ratios unless that is the business definition

## Level-aware metrics

Use level-aware definitions when the business meaning is fixed at a specific dimensional level.

Examples:

- average revenue per customer
- inventory balance as-of period
- account-level metrics shown under higher rollups

## Transformation metrics

Use governed transformations for last year, last quarter, last month, same week last year, prior fiscal period (full transformation catalog + validation rules in "Time modeling" below).

Prefer reusable named transformations instead of duplicating date-offset logic inside many metrics.

## Fact + metric review checks

- Does each fact belong at the declared grain?
- Is additive behavior documented?
- Are key metrics governed rather than raw?
- Are ratios defined safely?
- Are display formats business-appropriate?

---

# Relationship design

Relationships drive rollups, filter propagation, drill paths, security behavior, and SQL stability.

## Relationship decision tree

1. Are the two attributes levels in the same business dimension?
   - Yes: candidate relationship.
   - No: avoid unless there is a clear analytical path.
2. Does each child value map to exactly one parent at a point in time?
   - Yes: many-to-one candidate.
   - No: consider bridge, effective dating, or role separation.
3. Is the relationship stored in reliable source data?
   - Yes: map it there.
   - No: derive only if deterministic and validated.
4. Does the relationship create a cycle or ambiguous path?
   - Yes: redesign or isolate the hierarchy.
5. Could the relationship affect metric rollup correctness?
   - Yes: add explicit validation checks.

## Standard relationship patterns

- many-to-one rollup
- one-to-one identity extension
- many-to-many via bridge
- recursive hierarchy only when the platform pattern truly supports it
- time-variant relationship with effective dating when needed

## Cardinality validation query

Use a query like:

```sql
select child_id, count(distinct parent_id) as parent_count
from relationship_source
where child_id is not null
  and parent_id is not null
group by child_id
having count(distinct parent_id) > 1;
```

Expected result for many-to-one: zero rows unless time-variance is part of the key.

## Orphan detection query

```sql
select f.child_id
from fact_or_child_table f
left join lookup_parent p
  on f.parent_id = p.parent_id
where f.parent_id is not null
  and p.parent_id is null;
```

Expected result: zero rows or documented exceptions.

## Many-to-many safety

Use a bridge when:

- one fact row maps to multiple dimension members
- a child can roll to multiple parents
- allocation or coverage logic is required

Rules:

- define allocation weights when totals must be distributed
- validate that totals do not duplicate
- offer allocated and unallocated metric definitions when both are useful

## Mosaic relationship safety

Before relationship writes in Mosaic:

- confirm child and parent attributes exist
- confirm both have ID forms
- confirm required expressions exist on relevant tables
- confirm conformed attributes use consistent semantic names where applicable
- confirm the relationship is not already implied by co-resident mappings
- verify rollup output after commit

See also `feedback_mosaic_relationship_wiring.md` for tenant-verified failure avoidance.

---

# Hierarchy design

Hierarchies are for user navigation and semantic discoverability, not just physical join representation.

## Good hierarchy characteristics

- business-recognizable name
- clear top-to-bottom rollup
- unambiguous parentage
- levels users expect to browse together
- drill-up and drill-down paths that match real analysis workflows

## Common hierarchy examples

- Time: Year > Quarter > Month > Day
- Geography: Country > Region > State > City > Store
- Product: Department > Category > Subcategory > Product
- Customer: Segment > Customer > Account

## Hierarchy design rules

- start from likely analysis entry points, not just source tables
- keep subject areas separate unless cross-drill is genuinely common
- avoid exposing high-cardinality noisy levels as default entry points
- verify drill behavior after creation

## Hierarchy anti-patterns

- everything hierarchy containing unrelated attributes
- technical table hierarchy mirroring joins instead of business navigation
- circular drill path
- hidden many-to-many path that duplicates totals
- mixed fiscal and Gregorian levels without clear labeling

## Hierarchy review questions

- Will users recognize this hierarchy by business name?
- Are the levels in the right browse order?
- Are there ambiguous parents or hidden many-to-many paths?
- Does the hierarchy match common drill behavior?

---

# Time modeling

Time semantics should be designed explicitly, never inferred casually.

## Required design decisions

- Gregorian, fiscal, or custom calendar?
- Week starts on Sunday, Monday, or business-specific day?
- Standard months or 4-4-5 / 4-5-4 / 5-4-4?
- Which levels are required: day, week, month, quarter, year, time of day?
- Are holiday, business day, selling day, trading day, or payroll periods required?
- Are multiple date roles needed?

## Standard time hierarchy examples

Calendar:

- Year
- Quarter
- Month
- Day

Fiscal Calendar:

- Fiscal Year
- Fiscal Quarter
- Fiscal Period
- Fiscal Week
- Fiscal Day

## Role-playing time dimensions

Common roles:

- Order Date
- Ship Date
- Delivery Date
- Invoice Date
- Snapshot Date

Do not collapse distinct roles into one attribute if that makes filters ambiguous.

## Transformation examples

- Last Year
- Last Quarter
- Last Month
- Same Week Last Year
- Prior Fiscal Period
- Year-to-Date
- Quarter-to-Date
- Month-to-Date

Rules:

- validate transformations with real sample dates
- never assume fiscal year equals calendar year
- prefer named transformations over ad hoc metric offsets

## Time review checks

- Is the correct calendar declared?
- Are fiscal and Gregorian paths kept distinct?
- Are all required date roles modeled?
- Are comparative metrics validated with known examples?

---

## Related

- `feedback_mosaic_relationship_wiring.md` — conformed-dim encoding in Mosaic + the error codes when it breaks.
