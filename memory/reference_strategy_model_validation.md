---
name: Strategy model validation
description: Minimum validation suite for Strategy models: comparator strategy, rollup checks, tolerance handling, security smoke tests, and failure triage.
type: reference
---

Every shippable model needs validation against a trusted comparator or an explicit validation-pending note.

## Minimum validation suite

Validate at least:

1. row count or event count at declared grain
2. total of each core additive metric
3. metric by primary time level
4. metric by top business dimension
5. drill-path rollup from child to parent
6. null and orphan key counts
7. many-to-one relationship violations
8. distinct counts for high-risk attributes
9. top-N comparison against a trusted reference
10. security-filter smoke test when security is applied

## Comparator options

Comparator can be:

- trusted Mosaic model
- classic report / model
- direct warehouse SQL
- flat file extract
- saved REST fixture
- external system of record

## Result shape

Recommended durable output shape:

```yaml
validation_result:
  model:
  comparator:
  status: pass | fail | warning
  checks:
    - name:
      model_value:
      reference_value:
      tolerance:
      status:
      issue:
      likely_cause:
```

## Failure triage

Common causes:

- wrong grain
- many-to-many duplication
- orphan foreign keys
- incomplete attribute conformance
- level metric mismatch
- fiscal vs calendar mismatch
- security filter over- or under-constraint

## Shipping rule

Do not call a new build shippable if:

- totals disagree and no cause is documented
- rollup checks fail
- relationship cardinality is unverified
- security behavior is untested where required
