---
name: Strategy time modeling
description: Calendar and fiscal modeling guidance for Strategy: date roles, hierarchies, transformations, and comparative-period validation.
type: reference
---

Time semantics should be designed explicitly, never inferred casually.

## Required design decisions

- Gregorian, fiscal, or custom calendar?
- Week starts on Sunday, Monday, or business-specific day?
- Standard months or 4-4-5 / 4-5-4 / 5-4-4?
- Which levels are required: day, week, month, quarter, year, time of day?
- Are holiday, business day, selling day, trading day, or payroll periods required?
- Are multiple date roles needed?

## Standard hierarchy examples

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

## Review checks

- Is the correct calendar declared?
- Are fiscal and Gregorian paths kept distinct?
- Are all required date roles modeled?
- Are comparative metrics validated with known examples?
