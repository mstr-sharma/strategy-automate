---
name: Strategy fact and metric design
description: Fact and metric modeling rules for Strategy: additive behavior, count patterns, ratio safety, level-aware calculations, and review guidance.
type: reference
---

Facts expose measurable columns. Metrics encode the governed analytical definitions users consume.

## Fact design rules

- facts should be numeric, measurable, and true at the declared grain
- document additive behavior: additive, semi-additive, or non-additive
- capture the fact level from the table's dimensional keys
- avoid exposing columns whose meaning changes by row type unless that row type is modeled

## Additivity patterns

- additive: sums correctly across all analysis dimensions
- semi-additive: sums across some dimensions but not time
- non-additive: cannot be summed safely; often ratios, percentages, or balances without careful handling

Examples:

- Sales Amount → additive
- Inventory On Hand → semi-additive across time
- Margin % → non-additive

## Metric design rules

Prefer governed reusable metrics such as:

- Revenue = Sum(Sales Amount)
- Units Sold = Sum(Quantity Sold)
- Gross Margin = Revenue - Cost
- Gross Margin % = Gross Margin / Revenue

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

Use governed transformations for:

- last year
- last quarter
- last month
- same week last year
- prior fiscal period

Prefer reusable named transformations instead of duplicating date-offset logic inside many metrics.

## Review checks

- Does each fact belong at the declared grain?
- Is additive behavior documented?
- Are key metrics governed rather than raw?
- Are ratios defined safely?
- Are display formats business-appropriate?
