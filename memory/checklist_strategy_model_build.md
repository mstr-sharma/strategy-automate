---
name: Strategy model build checklist
description: Build-execution checklist for Strategy models: discovery, profiling, plan confirmation, changeset sequencing, publish, and validation handoff.
type: reference
---

Use during execution.

## Discovery and profiling

- Datasource / project / folder context is confirmed.
- Tables and columns are described.
- Candidate keys, nulls, and cardinality are profiled.
- The structured model plan is current.

## Write sequencing

- Correct surface is chosen: Mosaic vs classic vs runtime vs admin.
- Changeset is opened before modeling writes.
- Attributes are created before dependent relationships.
- Missing expressions are patched before relationship writes.
- ACL / translations / security are sequenced after base objects when required.

## Naming and publication

- Business-friendly names and descriptions are applied.
- Metric formats are reviewed.
- Publish path matches the target surface.

## Validation handoff

- Comparator is ready.
- Validation checks are listed.
- Known assumptions are recorded.
- Failure path includes discard / rollback behavior where possible.
