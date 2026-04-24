---
name: Strategy attribute design
description: Attribute design rules for Strategy models: forms, conformance, role-playing dimensions, SCDs, degenerate dimensions, and naming guidance.
type: reference
---

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

## Conformed dimensions

Use one semantic attribute when the same entity is shared across processes such as:

- Customer across orders, invoices, and support
- Product across sales, returns, and inventory
- Date across nearly all facts

Rules:

- use one semantic name
- ensure compatible key definitions
- add the required expressions on each relevant table
- resolve case mismatch and source naming drift before relationship creation

## Role-playing dimensions

Use separate roles when the same entity appears multiple times in one process.

Examples:

- Order Date, Ship Date, Delivery Date
- Billing Customer, Shipping Customer
- Origin Airport, Destination Airport

Rules:

- separate roles when filter semantics would otherwise be ambiguous
- use explicit business role names

## Degenerate dimensions

Use when a transaction identifier has analytical value but no separate lookup table.

Examples:

- Order Number
- Invoice Number
- Ticket Number

Rules:

- model as an attribute if users filter, browse, or count by it
- avoid making high-cardinality transaction IDs default browse entry points

## Slowly changing dimensions

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
