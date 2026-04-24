---
name: Strategy model design checklist
description: Pre-build design checklist for Strategy semantic models: business fit, grain, dimensions, facts, metrics, relationships, time, and governance.
type: reference
---

Use before any metadata writes.

## Business fit

- Business process is named.
- Grain is declared in one sentence.
- Core user questions are listed.
- Metric definitions match business language.

## Attribute quality

- Every attribute has an ID form.
- Descriptions are user-friendly.
- Forms are mapped on required tables.
- Conformed attributes use consistent names and compatible keys.

## Fact and metric quality

- Facts match the declared grain.
- Additive / semi-additive / non-additive behavior is documented.
- Ratios aggregate numerator and denominator first.
- Counts and distinct counts are explicitly defined.

## Relationship quality

- Each relationship has source evidence.
- Cardinality has been profiled.
- Orphans have been checked.
- Many-to-many paths use bridge / allocation logic.

## Hierarchy and time quality

- Hierarchies match user navigation.
- Drill paths are unambiguous.
- Calendar and fiscal paths are deliberate.
- Required time roles are identified.

## Governance

- Security requirements are known.
- Consumer-grade naming plan exists.
- Comparator for validation is chosen or explicitly pending.
