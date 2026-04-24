---
name: Data modeling foundations
description: Durable dimensional-modeling principles for Strategy automation: business process, grain, dimensions, facts, metrics, bridge logic, and common anti-patterns.
type: reference
---

Use this as the first modeling lens before touching Strategy objects or REST payloads.

## Core mental model

A Strategy semantic model is a contract between:

1. business questions
2. physical warehouse structures
3. governed semantic objects

Treat the model as three layers:

1. Business logical model: process, grain, dimensions, facts, hierarchies, and time semantics
2. Physical warehouse mapping: tables, keys, joins, bridges, snapshots, and source-system boundaries
3. Strategy semantic objects: attributes, forms, facts, metrics, relationships, hierarchies, transformations, and security rules

Never jump straight from table names to object payloads. Form a modeling plan first.

## Start from a business process

Good starting point:

- "Build an order-line sales model where one row represents one sold product on one order line, analyzable by day, customer, product, store, and channel."

Bad starting point:

- "Build a model from ORDER_HDR, ORDER_LINE, CUSTOMER, PRODUCT."

Facts normally represent a business process or event stream such as orders, shipments, invoices, balances, sessions, support cases, or inventory snapshots.

## Declare grain before dimensions and facts

The grain states what one row means. It is the binding contract for every downstream object.

Examples:

- retail sales: one row per order line
- shipment: one row per shipped package
- inventory snapshot: one row per product-store-day
- web analytics: one row per session
- account balance: one row per account-day snapshot

Rules:

- Do not mix grains in one fact table.
- Do not attach facts that are not true at the declared grain.
- Do not create relationships that imply a lower or higher grain than the source supports.
- Prefer atomic grain for the base truth; use cubes or aggregates for performance.

## Separate dimensions from facts

Facts answer "how much" or "how many." Dimensions answer "by what," "which," "who," "where," "when," or "why."

Examples:

- `Sales Amount` → fact
- `Quantity Sold` → fact
- `Order Count` → usually a metric, not a physical column requirement
- `Customer`, `Product`, `Store`, `Month`, `Fiscal Year` → attributes / dimensions

## Metrics are governed calculations

Facts are usually physical numeric columns. Metrics are the reusable analytical definitions users consume.

Examples:

- `Revenue = Sum(Sales Amount)`
- `Cost = Sum(Cost Amount)`
- `Gross Margin = Revenue - Cost`
- `Gross Margin % = Gross Margin / Revenue`

Agent rule: distinguish raw measurable columns from the governed metrics that should appear in the user-facing model.

## Common fact patterns

- Transaction fact: one row per event
- Periodic snapshot fact: one row per entity per period
- Accumulating snapshot fact: one row updated across lifecycle stages
- Factless fact: one row records occurrence or coverage without a measure

## Common dimension patterns

- Conformed dimension: reused across multiple processes
- Role-playing dimension: same entity appears in multiple roles
- Degenerate dimension: transaction identifier with no lookup table
- Junk dimension: clustered low-cardinality flags
- Slowly changing dimension: descriptors change over time
- Bridge / many-to-many dimension: one fact row maps to multiple members

## Anti-pattern catalog

| Anti-pattern | Symptom | Fix |
| --- | --- | --- |
| No declared grain | totals drift by report level | declare grain and realign facts |
| Mixed-grain fact table | duplicated totals or missing detail | split transaction, snapshot, and aggregate logic |
| Name-only joins | unstable SQL / failed relationships | validate keys and expressions |
| Everything hierarchy | confusing browse paths | split by subject area |
| Many-to-many without bridge | totals multiply | add bridge and allocation logic |
| Ratio of row-level ratios | incorrect percentages | aggregate numerator and denominator first |
| Calendar / fiscal confusion | bad time comparisons | model separate calendars and transformations |
| Mutable descriptions as IDs | duplicate elements / drift | use stable keys and expose descriptions as forms |

## Stopping conditions

Ask for clarification when:

- multiple grains are plausible
- business definitions of core metrics are unclear
- fiscal calendar rules are unknown
- many-to-many relationships affect totals
- security semantics are ambiguous
