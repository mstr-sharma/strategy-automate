---
name: Strategy hierarchy design
description: Hierarchy design rules for Strategy models: user navigation, drill paths, entry points, subject-area separation, and hierarchy anti-patterns.
type: reference
---

Hierarchies are for user navigation and semantic discoverability, not just physical join representation.

## Good hierarchy characteristics

- business-recognizable name
- clear top-to-bottom rollup
- unambiguous parentage
- levels users expect to browse together
- drill-up and drill-down paths that match real analysis workflows

## Common hierarchy examples

- Time: Year > Quarter > Month > Day
- Geography: Country > Region > State > City > Store
- Product: Department > Category > Subcategory > Product
- Customer: Segment > Customer > Account

## Design rules

- start from likely analysis entry points, not just source tables
- keep subject areas separate unless cross-drill is genuinely common
- avoid exposing high-cardinality noisy levels as default entry points
- verify drill behavior after creation

## Anti-patterns

- everything hierarchy containing unrelated attributes
- technical table hierarchy mirroring joins instead of business navigation
- circular drill path
- hidden many-to-many path that duplicates totals
- mixed fiscal and Gregorian levels without clear labeling

## Review questions

- Will users recognize this hierarchy by business name?
- Are the levels in the right browse order?
- Are there ambiguous parents or hidden many-to-many paths?
- Does the hierarchy match common drill behavior?
