---
name: Mosaic modeling concepts and payload shapes
description: Every Mosaic modeling construct (attribute forms, relationships, metric kinds, filters, transformations, hierarchies, consolidations, prompts) with the JSON body shape expected by the Modeling Service.
type: reference
originSessionId: initial-session
---
Applied to endpoints under `/api/model/dataModels/{id}/...`. When in doubt, `GET` an existing object of the same kind, capture the JSON, generate fresh UUIDs for inner `id`s, remap `objectId`s, and `POST` it back (the clone-and-remap pattern).

## Attributes

Body keys: `information, forms[], keyForm.id, attributeLookupTable, relationships?, displays?, childAttributes?, hidden?, hierarchyInfo?`

- Form: `{id?, category:"ID"|"DESC"|"<custom>", type:"system"|"custom", displayFormat:"text"|"number"|"date"|"picture"|"url"|"email"|"symbol"|"html_tag", expressions:[{expression:{tokens:[...]}, tables:[{objectId,subType:"logical_table",name}]}], lookupTable, alias?}`.
- **Key form** system id is the universal ID form `45C11FA478E745FEA08D781CEA190FE5` when the first form is a system ID; otherwise omit `id` on a custom form and point `keyForm.id` at the form's newly-minted id post-create.
- **Multi-form attribute (ID + DESC + display forms):** one entry in `forms[]` per physical column; `keyForm.id` references the ID form; `displays.reportDisplays` / `browseDisplays` select which forms render in reports and browse prompts (set via `PATCH` after create).
- **Compound keys:** multiple forms with `category:"ID"`; the compound is a synthetic form whose expression references all key columns.

## Attribute relationships
`PUT /api/model/dataModels/{id}/attributes/{childId}/relationships?changesetId=…`
```json
{"relationships":[{
  "parent":{"objectId":"<parentAttrId>","subType":"attribute"},
  "child":{"objectId":"<childAttrId>","subType":"attribute"},
  "relationshipType":"one_to_many"|"many_to_many"|"one_to_one",
  "relationshipTable":{"objectId":"<factOrBridgeTableId>","subType":"logical_table"}
}]}
```
- `relationshipTable` is where the join actually occurs — use the fact or bridge table that contains both keys.

## Facts (reusable column bindings — optional; fact metrics can embed directly)
```json
{"information":{"name":"Revenue"},
 "dataType":"number",
 "expressions":[{"expression":{"tokens":[{"type":"column_reference","value":"REVENUE"}]},
                 "tables":[{"objectId":"<tblId>","subType":"logical_table","name":"SALES"}]}],
 "entryLevel":[]}
```

## Fact metrics — simple (SUM/AVG/…)
```json
{"information":{"name":"Sum Revenue"},
 "fact":{"dataType":"number",
         "expressions":[{"expression":{"tokens":[{"type":"column_reference","value":"REVENUE"}]},
                         "tables":[{"objectId":"<tblId>","subType":"logical_table","name":"SALES"}]}],
         "extensions":[],"entryLevel":[]},
 "function":"sum",           // sum|avg|min|max|count|count_distinct|stdev|var|median|product|geo_mean|first|last
 "functionProperties":[],
 "dimty":{},
 "format":{"header":[],"values":[...]}}
```

## Compound metrics (derived)
Drop the `fact` block; the top-level `expression.tokens` references other metric IDs:
```json
{"information":{"name":"Profit"},
 "expression":{"tokens":[
   {"type":"metric_reference","value":"<revenueMetricId>"},
   {"type":"operator","value":"-"},
   {"type":"metric_reference","value":"<costMetricId>"}
 ]},
 "dimty":{},"format":{...}}
```
Use parentheses via `{"type":"operator","value":"("|")"}` tokens. Ratio/margin/CAGR all fit here. Posted to the same `/factMetrics` endpoint.

## Conditional metrics (filter-scoped)
Layer a `conditionality` block on top of any fact/compound metric:
```json
{"information":{"name":"Revenue (EMEA)"},
 "fact":{...}, "function":"sum", "dimty":{}, "format":{...},
 "conditionality":{"filter":{"objectId":"<filterId>","subType":"filter"},
                   "embed":true,             // inline (true) vs reference (false)
                   "removeAttrQualifications":false}}
```
Filter must exist first (via `/filters`).

## Level (dimensionality-override) metrics
Control aggregation level independent of the report template via `dimty`:
```json
"dimty": {
  "dimensions":[{"objectId":"<attrId>","subType":"attribute",
                 "aggregation":"none"|"group_by"}],
  "filtering":"standard"|"absolute"|"ignore"|"none"|"ignore_warehouse",
  "grouping":"standard"|"absolute"|"ignore"|"none",
  "allowAddedDimension":true
}
```
- "Share of parent" / "per-customer avg": set the target attribute with `aggregation:"group_by"` and `grouping:"absolute"`.
- `filtering:"ignore"` ignores the report filter for that metric.

## Transformations (time-shift / YoY / prior period)
Standalone object — create first, then attach to metrics.

Create:
```json
POST /api/model/dataModels/{id}/transformations
{"information":{"name":"Last Year"},
 "members":[{"attribute":{"objectId":"<dateAttrId>","subType":"attribute"},
             "offset":-12,
             "mappingTable":{"objectId":"<calendarTableId>","subType":"logical_table"}}]}
```

Attach (creates a new time-shifted metric):
```json
POST /api/model/dataModels/{id}/factMetrics
{"information":{"name":"Revenue LY"},
 "fact":{...},"function":"sum","dimty":{},"format":{...},
 "transformation":{"objectId":"<transformationId>","subType":"transformation"}}
```

## Filters
`POST /api/model/dataModels/{id}/filters`
```json
{"information":{"name":"EMEA"},
 "qualification":{"tree":{
    "type":"predicate_form_qualification",
    "predicateTree":{
       "function":"in",
       "attribute":{"objectId":"<regionAttrId>"},
       "form":{"objectId":"45C11FA478E745FEA08D781CEA190FE5"},
       "constant":{"type":"string","value":"EMEA"}
    }
 }}}
```
Predicate types: `predicate_form_qualification`, `predicate_metric_qualification`, `predicate_joint_element_list`, `predicate_element_list`, `predicate_false`.
Compose via `{"type":"operator","operator":"and"|"or"|"not","children":[…]}`.

## Hierarchies (user-defined drill paths)
`POST /api/model/dataModels/{id}/hierarchies`
```json
{"information":{"name":"Geography"},
 "attributes":[{"id":"<regionId>","filters":[]},{"id":"<countryId>"},{"id":"<cityId>"}],
 "relationships":[{"parent":"<regionId>","child":"<countryId>"},
                  {"parent":"<countryId>","child":"<cityId>"}]}
```

## Consolidations (enumerated virtual elements)
`POST /api/model/dataModels/{id}/consolidations`
```json
{"information":{"name":"Top Regions"},
 "elements":[{"name":"Americas","expression":"Region@ID IN ('US','CA','MX')"},
             {"name":"Europe","expression":"Region@ID IN ('DE','FR','UK')"}]}
```

## Custom groups (dynamic banded buckets)
`POST /api/model/dataModels/{id}/customGroups` — list of elements where each element is a filter expression + optional sub-banding (equal_count/equal_range/custom breaks).

## Prompts
`POST /api/model/dataModels/{id}/prompts`
Types: `attribute_element` (pick specific elements), `attribute_qualification` (user writes predicate), `hierarchy_qualification`, `value` (number/date/text/bigDecimal), `object` (pick metadata object).

## Security filters
Create — `POST /api/model/dataModels/{id}/securityFilters` with `qualification.tree`.
Assign — prefer `PATCH /api/dataModels/{dataModelId}/securityFilters/{sfId}/members` with `{operationList:[{op:"addElements",path:"/members",value:[ids...]}]}`; older tenant variants may accept `POST /api/model/dataModels/{id}/securityFilters/{sfId}/members` body `{users:[{id}], userGroups:[{id}]}`.
Top/bottom level override how the filter is applied vs report filter.

## Translations
Data-model object translations: `PATCH /api/model/dataModels/{modelId}/objects/{objectId}/translations?subType=<objectSubType>` with body `{name:{translationValues:{locale:{translation:"Client"}}}}` and/or `description`.

## ACL / object security
Data-model object ACL: `PATCH /api/model/dataModels/{modelId}/objects/{objectId}/acl?subType=<objectSubType>` with body `{acl:{trusteeId:{granted:<mask>,denied:<mask>,subType:"user"|"user_group"}}}` inside a changeset.
Rights: read=1, write=2, delete=4, control=32, execute=128, browse=64, use=512, inherit=1024, full=255.

## Certification
`PATCH /api/objects/{id}` with `{"certifiedInfo":{"certified":true}}` — Library marks with the certified badge.

## VLDB properties (SQL generation behavior)
`GET/PATCH /api/objects/{id}/vldbProperties?type=<objectType>` — per-metric / per-table / per-report overrides controlling join type, GROUP BY strategy, count(*) behavior, etc. Use when the auto-generated SQL needs to match a specific warehouse's quirks.
