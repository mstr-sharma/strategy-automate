---
name: Strategy Mosaic modeling
description: Mosaic-specific modeling guidance: build sequence, attribute conformance, relationship sequencing, changesets, publish flow, and validation expectations.
type: reference
---

Use this file when the target surface is a Mosaic data model.

## Mosaic build sequence

1. Discover datasources, schemas, tables, and columns.
2. Profile candidate keys, nulls, row counts, and join cardinalities.
3. Draft business process and grain.
4. Draft attribute plan.
5. Draft fact and metric plan.
6. Draft relationship plan.
7. Draft hierarchy plan.
8. Build the initial model through a changeset.
9. Patch missing expressions or conformance issues.
10. Add relationships only after attribute expressions are verified.
11. Apply consumer-grade naming.
12. Publish.
13. Validate numbers and drill behavior.
14. Record durable findings in memory.

## Attribute conformance rule

Relationship creation is safest when attributes representing the same entity share the same semantic name and compatible forms / expressions across relevant tables.

Before relationship writes:

- verify `forms[*].expressions[*].tables` covers needed tables
- patch missing expressions before relationship PUTs
- avoid redundant explicit relationships between attributes already co-resident unless the surface requires it
- validate with a post-commit rollup query

## Relationship failure triage

When relationship creation fails:

1. confirm child and parent attributes exist
2. confirm both have ID forms
3. confirm expressions exist on the tables used by the relationship
4. check case sensitivity and cross-database naming differences
5. check whether the relationship already exists implicitly
6. confirm relationship writes are occurring in the right changeset phase
7. retry with a minimal payload on a safe test pair
8. record endpoint behavior in memory

## Mosaic-specific safety

- always classify subtype before using cube vs data-model endpoints
- use changesets for modeling writes
- do not trust first-2xx publish heuristics; follow the verified publish path
- close every build with validation or an explicit pending note

## Related references

- `reference_mosaic_rest_api.md`
- `reference_mosaic_modeling_concepts.md`
- `feedback_mosaic_relationship_wiring.md`
- `feedback_consumer_grade_naming.md`
