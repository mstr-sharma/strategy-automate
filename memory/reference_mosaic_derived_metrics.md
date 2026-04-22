---
name: Mosaic derived metrics (compound, conditional, level) — verified UI shapes
description: Exact REST bodies for compound / conditional / level / transformation metrics as produced by the Studio UI. Three worked examples captured live: ratio of two metrics, filter-scoped metric, level-metric aggregated at a specific attribute. Supersedes the earlier tokens-only guess in the build skill.
type: reference
---

All three examples are from a real Studio UI save. The `/api/model/dataModels/{mid}/metrics` endpoint (**not** `/factMetrics`) is used for derived metrics. Fact metrics keep their `/factMetrics` endpoint.

## Endpoint

```
POST   /api/model/dataModels/{mid}/metrics?showAdvancedProperties=true
PATCH  /api/model/dataModels/{mid}/metrics/{metricId}?showAdvancedProperties=true
GET    /api/model/dataModels/{mid}/metrics/{metricId}?showExpressionAs=tokens&showAdvancedProperties=true
```

`showAdvancedProperties=true` returns the full `advancedProperties` block (VLDB overrides, dimty, conditionality) — our helpers should always pass this.

## 1. Compound metric — ratio of two metrics

User example: `Avg({Competitor Lowest Price USD}) / Avg({Market Average Price USD})`.

Shape:
- No `fact` block, no top-level `function`.
- `expression.text` is the human formula; `expression.tokens` is the parsed tree.
- Every aggregate wraps its argument with an inline VLDB property `<UseLookupForAttributes=False>` — the UI injects this automatically. Our helpers currently don't.
- Dimty has the `{~+}` report-base-level marker only; no extra dimensions.
- `function` is `null` at the metric level — aggregation is inside the tokenized expression.

Key token sequence:
```
function:"Avg" → character:"<" → identifier:"UseLookupForAttributes" → function:"=" → boolean:"False" → character:">" →
character:"(" → object_reference:{Competitor Lowest Price USD, subType:"fact_metric"} → character:")" →
character:"{" character:"~" character:"+" character:"}"   ← the "report base level" end-of-metric marker
→ character:"/"   ← operator
→ function:"Avg" → ... → object_reference:{Market Average Price USD} → ... → "{~+}"
→ end_of_text
```

Full body (abbreviated):
```json
{
  "information": {"name": "Competitor to Market Price Ratio", "subType": "metric"},
  "expression": {
    "text": "Avg({Competitor Lowest Price USD}) / Avg({Market Average Price USD})",
    "tokens": [
      {"type": "function", "value": "Avg", "target": {"objectId": "8107C31DDD9911D3B98100C04F2233EA", "subType": "function", "name": "Avg"}},
      {"type": "character", "value": "<"},
      {"type": "identifier", "value": "UseLookupForAttributes"},
      {"type": "function", "value": "="},
      {"type": "boolean", "value": "False"},
      {"type": "character", "value": ">"},
      {"type": "character", "value": "("},
      {"type": "object_reference", "value": "[Competitor Lowest Price USD]", "target": {"objectId": "<metric id>", "subType": "fact_metric"}},
      {"type": "character", "value": ")"},
      {"type": "character", "value": "{"}, {"type": "character", "value": "~"},
      {"type": "character", "value": "+"}, {"type": "character", "value": "}"},
      {"type": "character", "value": "/", "target": {"objectId": "8107C313DD9911D3B98100C04F2233EA", "subType": "function", "name": "/"}},
      {"type": "function", "value": "Avg", "target": {"...": "..."}},
      {"type": "character", "value": "("},
      {"type": "object_reference", "value": "[Market Average Price USD]", "target": {"objectId": "<metric id>", "subType": "fact_metric"}},
      {"type": "character", "value": ")"},
      {"type": "character", "value": "{"}, {"type": "character", "value": "~"},
      {"type": "character", "value": "+"}, {"type": "character", "value": "}"},
      {"type": "end_of_text", "value": ""}
    ]
  },
  "dimty": {"dimtyUnits": [{"dimtyUnitType": "report_base_level", "aggregation": "normal", "filtering": "apply", "groupBy": true}], "excludeAttribute": false, "allowAddingUnit": true},
  "format": {"values": [
    {"type": "number_category", "value": "0"},
    {"type": "number_format", "value": "#,##0.0000;(#,##0.0000)"},
    {"type": "number_currency_position", "value": "0"},
    {"type": "number_currency_symbol", "value": "$"},
    {"type": "number_decimal_places", "value": "4"},
    {"type": "number_negative_numbers", "value": "3"},
    {"type": "number_thousand_separator", "value": "true"}
  ]}
}
```

### Well-known function objectIds (useful for building tokens)

| Function | objectId (verified) |
|---|---|
| Sum | `8107C31BDD9911D3B98100C04F2233EA` |
| Avg | `8107C31DDD9911D3B98100C04F2233EA` |
| `/` | `8107C313DD9911D3B98100C04F2233EA` |
| Concat | `6F7DF5FF449111D5BEA300B0D01A55EF` |
| ApplySimple | `8107C340DD9911D3B98100C04F2233EA` |

These are platform-wide constants (same across tenants, verified earlier in the tutorial env).

## 2. Conditional metric — fact metric with embedded filter

User example: `Sum({ESG Score})` scoped to `Product Category IN (Region A, Region B, Region C)`.

Shape:
- `expression.text` = just the unfiltered aggregate (`Sum({ESG Score})`).
- The filter lives in a separate `conditionality` block AND is inlined into the expression tokens as an `object_reference` with `isEmbedded:true`.
- `expression.tokens` appends `< <embedded-filter-ref> >` at the end to show the filter binding.

```json
{
  "information": {"name": "ESG Score (Region A)", "subType": "metric"},
  "expression": {
    "text": "Sum({ESG Score})",
    "tokens": [
      {"type": "function", "value": "Sum", "target": {"objectId": "8107C31BDD9911D3B98100C04F2233EA", "subType": "function"}},
      /* <UseLookupForAttributes=False> property tokens */
      {"type": "character", "value": "("},
      {"type": "object_reference", "value": "[ESG Score]", "target": {"objectId": "<fact metric id>", "subType": "fact_metric"}},
      {"type": "character", "value": ")"},
      /* {~+} report-base-level marker */
      {"type": "character", "value": "<"},
      {"type": "object_reference", "value": "", "target": {"objectId": "<embedded-filter-id>", "subType": "filter", "isEmbedded": true}},
      {"type": "character", "value": ">"},
      {"type": "end_of_text"}
    ]
  },
  "dimty": {"dimtyUnits": [{"dimtyUnitType": "report_base_level", ...}]},
  "conditionality": {
    "filter": {"objectId": "<embedded-filter-id>", "subType": "filter", "isEmbedded": true},
    "embedMethod": "report_into_metric_filter",
    "removeElements": true
  },
  "format": {"values": [...]}
}
```

- `conditionality.filter.isEmbedded:true` means the filter is scoped to this metric only (not a reusable top-level filter object).
- `embedMethod:"report_into_metric_filter"` is the UI default; other values exist (`report_intersect_metric_filter`, `replace`) — check the UI affordance when porting.
- `removeElements:true` means "ignore attribute qualifications from the report context when this filter applies" — removes outer report filters on the qualified attribute.

**Building the embedded filter:** the UI creates the filter object first (separate POST to the model's `/filters` endpoint), captures its objectId, then references it in both `conditionality.filter` and the expression `object_reference`. Cannot be inlined in a single call — need two changeset steps.

## 3. Level metric — aggregate at a specific attribute level

User example: `Sum({Patent Count})` aggregated at Product Category level (total patents per category, independent of the report grain).

Shape:
- `expression.text` is the aggregate (`Sum({Patent Count})`).
- The level attribute appears INSIDE the `{~, <attr>+}` marker in the tokens — not as a separate dimty entry.
- `dimty.dimtyUnits[]` has TWO entries: `report_base_level` PLUS an `attribute` unit pointing at Product Category.

```json
{
  "information": {"name": "Product Category Patent Count", "subType": "metric"},
  "expression": {
    "text": "Sum({Patent Count})",
    "tokens": [
      {"type": "function", "value": "Sum", "target": {"...Sum..."}},
      /* <UseLookupForAttributes=False> */
      {"type": "character", "value": "("},
      {"type": "object_reference", "value": "[Patent Count]", "target": {"objectId": "<fact metric id>", "subType": "fact_metric"}},
      {"type": "character", "value": ")"},
      {"type": "character", "value": "{"},
      {"type": "character", "value": "~"},
      {"type": "character", "value": "+"},
      {"type": "character", "value": ","},
      {"type": "object_reference", "value": "[Product Category]", "target": {"objectId": "<attr id>", "subType": "attribute"}},
      {"type": "character", "value": "+"},
      {"type": "character", "value": "}"},
      {"type": "end_of_text"}
    ]
  },
  "dimty": {
    "dimtyUnits": [
      {"dimtyUnitType": "report_base_level", "aggregation": "normal", "filtering": "apply", "groupBy": true},
      {"dimtyUnitType": "attribute",
       "target": {"objectId": "<attr id>", "subType": "attribute", "name": "Product Category"},
       "aggregation": "normal", "filtering": "apply", "groupBy": true}
    ],
    "excludeAttribute": false,
    "allowAddingUnit": true
  }
}
```

- The `+` marker on the Product Category unit means "group by this attribute level".
- `aggregation:"normal"` is the default "sum rows at this level"; `"group_by"` / `"none"` exist for more exotic behaviors.
- `filtering:"apply" | "absolute" | "ignore" | "none" | "ignore_warehouse"` controls whether report filters restrict this metric's scope.

## The `{~+}` "report-base-level" token sequence

Every derived metric ends with a 4-char marker: `{` `~` `+` `}` (as four separate `character` tokens). This is the internal representation of "apply at report base level". Our helpers must emit this after the metric's main expression or the server rejects the tokens as incomplete.

Level metrics extend the sequence with `,` + attribute_ref + `+` before the closing `}`.

Transformation metrics would add a transformation_ref via the same pattern (to be captured).

## VLDB property inline marker: `<UseLookupForAttributes=False>`

The UI automatically wraps every aggregate function call (Sum, Avg, etc.) with this VLDB override. It tells the SQL engine "don't join through the attribute's lookup table just to aggregate this fact". For warehouse-efficient SQL this should usually be `False`.

Token sequence: `<` → `identifier:UseLookupForAttributes` → `function:=` → `boolean:False` → `>`. Six tokens, always in this order. Skipping this is probably fine for simple automation but will produce suboptimal SQL.

## Format tokens (fuller than the earlier memory)

Currency example from the captured ratio metric:

```json
[
  {"type": "number_category", "value": "0"},
  {"type": "number_format", "value": "#,##0.0000;(#,##0.0000)"},
  {"type": "number_currency_position", "value": "0"},
  {"type": "number_currency_symbol", "value": "$"},
  {"type": "number_decimal_places", "value": "4"},
  {"type": "number_negative_numbers", "value": "3"},
  {"type": "number_thousand_separator", "value": "true"}
]
```

Additional format fields observed beyond the earlier memory:
- `number_currency_position` (0 = prefix, 1 = suffix)
- `number_currency_symbol` (the symbol string)
- `number_negative_numbers` (enum: 1 = minus sign, 2 = red, 3 = parens, 4 = red parens)
- `number_thousand_separator` (`"true"`/`"false"`)

Category `0` is "Fixed" (used for ratios with currency symbol); category `2` is Currency (bundle); category `5` is Percentage. When building by script, pick the right category or decimals + currency fields get ignored.

## Takeaways for the build helpers

1. Use `/metrics` for compound/conditional/level metrics; keep `/factMetrics` for plain aggregates.
2. Always POST with `?showAdvancedProperties=true`.
3. Emit the `{~+}` trailer on every token list.
4. Wrap every aggregate with `<UseLookupForAttributes=False>` unless you know you want lookup-table joins.
5. For conditional metrics, create the filter object in one changeset, then the metric in the next changeset that references it with `isEmbedded:true`.
6. For level metrics, ADD the attribute to `dimty.dimtyUnits[]` AND include it inside the `{~, <attr>+}` token cluster.
7. Match the format.values fields to the metric's semantic category (money, percent, fixed decimal, etc.).
