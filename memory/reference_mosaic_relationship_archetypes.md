---
name: Mosaic relationship archetypes
description: The 6 canonical relationship patterns in Mosaic (star, snowflake, bridge, composite-FK, descriptive, date-hierarchy), how to encode each, and what breaks if you skip one.
type: reference
---
Every Mosaic model is a composition of these 6 patterns. Before declaring relationships for a new schema, classify each FK by archetype. Complements `reference_mosaic_modeling_concepts.md` (payload shapes) with the decision map from ERD → Mosaic relationships.

All payloads go through `PUT /api/model/dataModels/{modelId}/attributes/{childId}/relationships?changesetId=…` with one entry in `relationships[]` per archetype instance. `relationshipTable` is where the join physically occurs.

## A — Star (dim → fact, single-column FK)

**Shape:** `DIM (1) → FACT (N)`; e.g., `CUSTOMER → ORDERS`, `ORDERS → LINEITEM`.

**Encoding:** parent = dim's primary attribute; child = a grain attribute on the fact table (the fact's own ID or line-number attribute); relationshipType = `one_to_many`; relationshipTable = fact table. The dim's primary attribute must have an `expression` on the fact table as well as on the dim table — otherwise Mosaic rejects with `8004ccc7 "Table cannot be used as the join table"`.

**What breaks if skipped:** queries joining dim to fact will have no path, fail at SQL generation or detour through another dim, producing Cartesian bursts.

**Required count:** one per FK column on the fact table. A fact with 3 FKs to different dims needs 3 star relationships, not 1.

## B — Snowflake (dim → sub-dim → fact)

**Shape:** `REGION → NATION → CUSTOMER → ORDERS`; the dim hierarchy is normalized across multiple tables.

**Encoding:** two separate star relationships. `REGION → NATION via NATION` (parent's expression is on both tables), then `NATION → CUSTOMER via CUSTOMER`. Never collapse into a single rel with `relationshipTable = NATION` pointing at CUSTOMER — the intermediate level gets skipped.

**What breaks if skipped:** drill paths lose levels; users can pick Region or Customer but can't see Nation in between.

## C — Bridge / associative (M:N via junction table)

**Shape:** `PART ↔ PARTSUPP ↔ SUPPLIER`; the junction's PK is `(PARTKEY, SUPPKEY)` and it carries its own facts.

**Encoding:** create one bridge-grain attribute on the junction table (name it after the junction, e.g., "Part Supplier" or one of its descriptive columns like "Part Supplier Comment"). Make that attribute the child of both parent dims in two separate `one_to_many` relationships, with `relationshipTable` = the junction table on both sides. If the junction has facts that descend to another fact table (junction → LINEITEM on (PARTKEY, SUPPKEY)), handle via archetype D.

**What breaks if skipped:** M:N joins collapse to N (over-counting) or get broken across the two dims, producing mismatched row counts depending on which dim is queried first.

## D — Composite-FK (fact keyed on ≥2 columns from a parent)

**Shape:** `PARTSUPP → LINEITEM` on `(PARTKEY, SUPPKEY)` together; inventory snapshots keyed on (date, location, sku); audit tables keyed on (entity, effective_date).

**Encoding:** compound attribute on the parent (PARTSUPP) whose key is a concatenation or compound of both columns. Emit it with either (a) one ID form whose expression is `CONCAT(PARTKEY, '_', SUPPKEY)` or (b) multiple `category:"ID"` forms that Mosaic treats as a compound key. Declare one relationship from this compound attribute to the fact's grain via the fact table.

**Never:** declare two independent single-key `one_to_many` rels (Part → LineItem on PARTKEY, Supplier → LineItem on SUPPKEY). Each row in LINEITEM matches every row in PARTSUPP sharing *either* key, producing a Cartesian burst; metrics are wrong by a factor of N.

**What breaks if skipped:** if you model it as two stars, sums and counts are multiplied by the average parent-side fanout; if you skip entirely, Strategy can't join PARTSUPP to LINEITEM for metrics that need both sides.

## E — Descriptive (attribute on same lookup table as its parent key)

**Shape:** `Customer Address → Customer`, `Part Brand → Part`, `Order Clerk → Order Key`. The child lives on the same lookup table as the parent ID.

**Encoding:** child's `attributeLookupTable` = parent's lookup table; one `one_to_many` relationship child → parent with `relationshipTable` = that shared table. `enableAutoHierarchyRelationships: true` will auto-emit these IF form names and categories are populated (see `feedback_mosaic_build_quality.md` R1).

**What breaks if skipped:** report drills from Customer to Customer Address work in SQL (same table) but don't appear in the hierarchy UI; AI agents can't describe the 1:1 relationship; some query optimizers fail to fold the join and emit an extra self-join.

**Count sanity-check:** every non-key descriptor attribute on a dim lookup table should produce exactly one descriptive rel. If a dim has 8 descriptive attrs but only 3 descriptive rels, R1 or auto-hierarchy failed.

## F — Date hierarchy (temporal derived attrs)

**Shape:** `Order Date Day → Order Date Month → Order Date Quarter → Order Date Year`.

**Encoding:** for each date column, generate 4 derived attributes with `forms[].expressions[].expression.tokens` wrapping the base column in `DAYOFMONTH`, `MONTH`, `QUARTER`, `YEAR` (or tenant-appropriate function). Lookup table = same as the base date's fact/dim. Relationships form a fan-out chain: Day → Month via base table, Month → Quarter, Quarter → Year. Apply `sorts` so Month renders in calendar order (Jan … Dec), not alphabetic.

**What breaks if skipped:** users can't group by month/quarter/year without writing derived expressions in every report. Dashboards cannot drill temporal hierarchies. Date-driven metrics (YoY, QoQ) either can't exist or need ad-hoc date math.

**Apply to:** every column whose `dataType.type` is `date` or `timestamp`; skip only with an explicit `--no-date-hierarchies` opt-out.

## Archetype decision table (ingest-time classifier)

| FK shape | Archetype | Output per FK |
|---|---|---|
| Single-column, parent is dim, child is fact | A — Star | 1 relationship |
| Single-column, parent is dim, child is another dim with its own FKs | B — Snowflake | 1 relationship; recurse into child |
| ≥2 FKs in same table pointing at different dims, child PK = union of those FKs | C — Bridge | 1 bridge-grain attr + 2 relationships |
| ≥2-column FK where parent supplies both columns | D — Composite | 1 compound parent attr + 1 relationship |
| Non-key column on same lookup as a parent key | E — Descriptive | 1 relationship (auto if metadata clean) |
| Date/timestamp column on any table | F — Date hierarchy | 4 derived attrs + 3 relationships |

Before shipping a build, for every FK in the source ERD, identify the archetype and confirm the expected `relationships[]` count matches what was declared. Gap > 0 = missing join path = bad model.
