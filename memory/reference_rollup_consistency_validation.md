---
name: Rollup-consistency validation pattern for Mosaic models
description: A Trino query pattern that proves a newly built Mosaic model has no cartesian joins, no fan-out, and correct relationship wiring — without needing a classic-report source-of-truth.
type: reference
---

## The pattern

When classic-report execution isn't available for cross-validation (warehouse offline, tenant mismatch, etc.), you can still prove a Mosaic model's relationship + metric wiring is correct by verifying **rollup consistency**: aggregate each fact metric at every attribute level independently, and confirm the totals are identical.

```sql
SELECT 'category_rollup' AS level,
       COUNT(*) AS row_count,
       SUM("revenue") AS total_rev, SUM("cost") AS total_cost
  FROM (SELECT "category (id)", SUM("revenue") AS revenue, SUM("cost") AS cost
          FROM "<model>" GROUP BY "category (id)")
UNION ALL
SELECT 'subcategory_rollup', COUNT(*), SUM("revenue"), SUM("cost")
  FROM (SELECT "subcategory (id)", SUM("revenue") AS revenue, SUM("cost") AS cost
          FROM "<model>" GROUP BY "subcategory (id)")
UNION ALL
SELECT 'item_rollup', COUNT(*), SUM("revenue"), SUM("cost")
  FROM (SELECT "item (id)", SUM("revenue") AS revenue, SUM("cost") AS cost
          FROM "<model>" GROUP BY "item (id)")
UNION ALL
SELECT 'brand_rollup', COUNT(*), SUM("revenue"), SUM("cost")
  FROM (SELECT "brand (id)", SUM("revenue") AS revenue, SUM("cost") AS cost
          FROM "<model>" GROUP BY "brand (id)")
```

Run against the Mosaic Trino schema. Expected output: `total_rev` and `total_cost` **identical** across every `level` row. `row_count` varies (number of distinct elements at that attribute level).

## What it catches

| Symptom | Diagnosis |
|---|---|
| Totals differ between two levels | Fan-out from a relationship without `one_to_many` type set correctly, or a bridge table being used for a non-M:M join. |
| A level returns an **error** | No join path exists — the attribute isn't reachable from the fact table. Usually means the parent attribute's ID-form expression doesn't include the join table. |
| All levels return the same total but it's **0** or **null** | Fact metric expression references a column that doesn't exist on the fact table, or the attribute lookup is wrong. |
| A level returns many more rows than expected (e.g., brand_rollup shows 5,000 rows for a 275-brand dim) | Attribute ID expression is on the wrong table, fanning out. |
| A level shows `total_rev * N` inflation | Cartesian: same root cause as the build-time "cartesian join detected" error, but at query level it may only show up under some slicings. |

## When to skip this pattern

- When you have a working classic-report source-of-truth. Numeric-match comparison is strictly stronger than rollup consistency.
- When the model has zero relationships (single-table model). There's nothing to validate here.

## Limitations

- Does NOT catch formula errors (a metric computing the wrong thing consistently). Need a separate spot-check against a known dimension value.
- Does NOT catch attribute form / descriptor display bugs. Those show up in the Library UI but not in the Trino layer.
- Assumes your warehouse data isn't polluted — inflation could be from dirty data (duplicated ORDER_DETAIL rows) rather than from the model.

## Observed on Products Hierarchy (Mosaic)
- All 4 rollups matched: Revenue=$3,810,481,529.153 / Cost=$4,008,303,459.68
- row_counts: category=4, subcategory=24, item=360, brand=275
- Verdict: relationships wired correctly, fact metric joins clean, no fan-out across Category→Subcategory→Item chain or Brand→Item.
