---
name: Strategy relationship design
description: Relationship design rules for Strategy models: cardinality, bridge logic, orphan checks, hierarchy fit, and Mosaic relationship write safety.
type: reference
---

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

## Standard patterns

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
