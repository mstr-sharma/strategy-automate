---
name: Role-playing dimensions need explicit handling, not first-occurrence-wins
description: Multi-FK-to-same-dim patterns (e.g. WS_SOLD_DATE_SK + WS_SHIP_DATE_SK → DATE_DIM) need alias attributes per role; the default "first (parent, table) wins" wiring silently drops every other role.
type: feedback
---

## The pattern

A TPC-DS-style fact table often has multiple FK columns pointing to the same
dimension. Each FK plays a different role:

- `WEB_SALES.WS_SOLD_DATE_SK` → `DATE_DIM` (role: "Sold Date")
- `WEB_SALES.WS_SHIP_DATE_SK` → `DATE_DIM` (role: "Ship Date")
- `WEB_SALES.WS_BILL_CUSTOMER_SK` → `CUSTOMER` (role: "Bill-to Customer")
- `WEB_SALES.WS_SHIP_CUSTOMER_SK` → `CUSTOMER` (role: "Ship-to Customer")

The Kimball term is **role-playing dimension**. TPC-DS has 18+ of these.

## What goes wrong with naive wiring

If the relationship-hint file is fed straight into a wire script, and the
script groups by `(parent_attribute, relationship_table)`, the first row for
each pair wins silently. Every subsequent role ends up as a Level-B-only
attribute with no Level-A parent → it's effectively isolated.

In our TPC-DS build this produced 241 isolated attributes that all looked
unrelated until we plotted them by role.

## The repo's defensive contract

`mosaic_safety.detect_role_playing_secondaries(rels)` returns
`(primaries, secondaries)` so any script can:

1. Wire the primaries (first occurrence per `(parent, table)`).
2. Log every secondary with its full identity (`parent → child via table`).
3. Decide what to do with secondaries — DO NOT silently drop them.

`cmd_wire_relationships` calls this helper and prints a `ROLE-PLAY skip` line
for every secondary so the gap is visible in the build log.

## Correct handling (per role)

Two options:

### Option A — alias attribute per role (preferred)

For each role, create a separate Mosaic attribute that shares the dim's
lookup table but binds to the role-specific FK column:

```
attribute: "Sold Date"  → expression on WEB_SALES.WS_SOLD_DATE_SK
attribute: "Ship Date"  → expression on WEB_SALES.WS_SHIP_DATE_SK
```

Both attributes resolve to the same conformed dim ("Date") via the lookup
table, but the relationship table (WEB_SALES) joins each role to its own
FK column. Use `mosaic_safety.make_expression()` to build the form expression
in the writable `tokens` format.

### Option B — single attribute, multiple form expressions

Create one "Date" attribute with form expressions on every FK column. Strategy
will pick the right expression based on which fact table is in the query. Less
self-documenting than Option A, and breaks down in galaxy schemas where two
fact tables both have multiple roles to the same dim.

## Pre-wiring inventory check

```python
import mosaic_safety as ms
primaries, secondaries = ms.detect_role_playing_secondaries(hints)
if secondaries:
    # Either build alias attributes, or document the skip explicitly.
    for rel in secondaries:
        print(f"ROLE-PLAY: {rel['parent_attribute']} → "
              f"{rel['child_attribute']} via {rel['relationship_table']}")
```

## Related

- `feedback_mosaic_relationship_wiring.md` — six-step Kimball recipe.
- `feedback_mosaic_relationship_put_wipes.md` — sibling gotcha on the PUT semantics.
- `mosaic_safety.ROLE_PLAYING_DOC` — same pattern, embedded in the source.
