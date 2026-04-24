---
name: Strategy legacy semantic modeling
description: Classic Strategy semantic-layer modeling and migration guidance: inventory, object interpretation, migration mapping, and report-driven preservation rules.
type: reference
---

Use this file when the source of truth is the classic / project semantic layer.

## Inventory first

Before migrating or modifying a classic project, inventory:

- attributes and forms
- facts and fact expressions
- metrics and dependencies
- hierarchies
- transformations
- tables and keys
- reports / dossiers using the objects
- security filters and ACLs

## Migration mapping

| Classic object | Mosaic / modern concern |
| --- | --- |
| Attribute | attribute with forms and expressions |
| Fact | fact column or measure source |
| Metric | governed calculation |
| Hierarchy | browse / drill path |
| Transformation | time comparison rule |
| Logical table | physical dataset / table mapping |
| Security filter | row-level security concern |
| Report | validation target and usage evidence |

## Do not migrate blindly

A legacy object may encode years of business logic.

Before simplifying:

- mine report usage
- inspect metric definitions
- identify level metrics and transformations
- compare outputs with trusted reports
- preserve names users recognize unless there is a deliberate cleanup plan

## Operational rule

For legacy-to-Mosaic work, the classic semantic layer is usually the blueprint. Do not treat migration as a greenfield shared-column inference exercise unless no reliable semantic source exists.
