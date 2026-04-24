---
name: Strategy schema object map
description: Strategy semantic object map for modeling work: tables, attributes, forms, facts, metrics, relationships, hierarchies, transformations, and their operational roles.
type: reference
---

Use this file to translate conceptual modeling decisions into Strategy object families.

## Tables

Tables are the physical source of expressions. Common roles:

- lookup tables: dimensional keys and descriptors
- fact tables: measurements at the declared grain
- relationship tables: parent-child or bridge mapping
- transformation tables: comparative period mapping
- aggregate tables: higher-level summaries
- partition tables: horizontally split storage

Agent rule: inspect columns, candidate keys, null rates, row counts, and join cardinalities before object creation.

## Attributes

Attributes represent business entities or levels. They usually contain:

- ID form: stable join / element identity
- description form: user-facing label
- additional forms: code, long description, sort order, status, external key
- expressions: table-column mappings

Rules:

- every attribute needs a stable identifier
- prefer surrogate or business-stable keys over mutable names
- do not use descriptions as IDs unless uniqueness is proven
- add expressions on every table needed for joins or relationship resolution

## Facts

Facts expose measurable columns into the semantic layer.

Rules:

- facts should be numeric or truly measurable
- text context belongs in attributes or forms, not facts
- record additive behavior explicitly
- avoid facts whose meaning changes by row type unless row type is modeled

## Metrics

Metrics are reusable semantic calculations. Common forms:

- base metric
- compound metric
- ratio metric
- count / distinct count metric
- level-aware metric
- transformation metric

Rules:

- expose named governed metrics, not a combinatorial explosion of raw aggregations
- define aggregation, null handling, and display format explicitly
- for ratios, aggregate numerator and denominator first, then divide

## Relationships

Relationships define how attributes constrain and roll up to one another.

Examples:

- Day → Month → Quarter → Year
- Product → Subcategory → Category
- City → State → Country

Rules:

- validate cardinality with data, not just names
- do not create a relationship only because two tables can join
- use a bridge pattern for many-to-many paths

## Hierarchies

Hierarchies organize attributes for browse, drill, and discoverability.

Rules:

- design hierarchies from user navigation, not just physical joins
- not every true relationship belongs in a visible hierarchy
- keep unrelated subject areas separate unless users routinely drill across them

## Transformations

Transformations model governed comparative mappings such as prior month, prior year, or fiscal offsets.

Rules:

- use transformations for reusable comparisons instead of embedding custom offsets in many metrics
- validate transformations with known sample dates
- do not assume fiscal offsets equal Gregorian offsets

## Security-related modeling objects

Security filters and ACLs are governance objects, but they still depend on sound modeling:

- row-level security assumes stable attribute identity and rollup paths
- object ACLs assume the right browse surfaces exist
- security smoke tests belong in the validation suite for shippable models
