---
name: Strategy model review checklist
description: Post-build review checklist for Strategy semantic models: business fit, object quality, rollups, hierarchy behavior, validation, and documented risks.
type: reference
---

Use before calling a model done.

## Business fit

- Business process and grain still match the delivered model.
- User-facing names are business-readable.
- Core questions can be answered cleanly.

## Object quality

- Attributes expose the right forms.
- Facts and metrics align with declared behavior.
- Relationships reflect real business rollups.
- Hierarchies support expected browse and drill paths.

## Validation

- Totals match the comparator within tolerance.
- Rollups preserve totals.
- Cardinality and orphan checks are clean or documented.
- Security smoke tests pass when applicable.

## Risks and documentation

- Known differences are documented.
- Assumptions are captured.
- Tenant-verified gotchas discovered during the build are written to memory.
