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

## 0. Tree format — RECOMMENDED for scripted writes (verified 2026-07-21)

For programmatic creation, build **`expression.tree`** (a nested node object), NOT `expression.text` and NOT hand-rolled `tokens`. **`text` is `readOnly` — the service ignores it on input** (POSTing only `text` → `8004d717 "metric expression is empty"`). The tree is far simpler than tokens: no `{~+}` markers, no operator objectIds, no `<UseLookupForAttributes>` wrapper tokens.

Node shapes (discriminator = `type`):
- **Operator**: `{"type":"operator","function":"<EnumFunction>","children":[<node>,...]}` — functions are by NAME: arithmetic = `plus`/`minus`/`times`/`divide`/`unary_minus`; aggregates = `sum`/`avg`/`count`/`min`/`max`.
- **Object reference** (inlines another metric WITH its own aggregation): `{"type":"object_reference","target":{"objectId":"<metricId>","subType":"fact_metric","name":"..."}}`.
- **Constant**: `{"type":"constant","variant":{"type":"int64","value":"100000000"}}` (EnumVariantType: int32/int64/date/time/boolean).

Rules that bit us:
- **`dimty` must be `null`** for a compound expression (anything not a bare aggMetric object-reference) → else `8004d711 "...dimty should be null"`. Bare fact/aggMetrics DO take the `report_base_level` dimty.
- Changeset goes in the **`X-MSTR-MS-Changeset` header**, not `?changesetId=` (→ `8004cc03`).
- No top-level `function` on a compound metric. identity-token OFF on studio ([[feedback_mosaic_identity_token_privilege_downgrade]]).

Worked example — cross-source ratio `MktCap / ((OutputSat/1e8) * Close)`:
```json
{"information":{"name":"NVT Ratio","subType":"metric"},
 "expression":{"tree":{"type":"operator","function":"divide","children":[
   {"type":"object_reference","target":{"objectId":"<mktcap>","subType":"fact_metric","name":"Market Capitalization USD"}},
   {"type":"operator","function":"times","children":[
     {"type":"operator","function":"divide","children":[
       {"type":"object_reference","target":{"objectId":"<outsat>","subType":"fact_metric","name":"Output Value Satoshis"}},
       {"type":"constant","variant":{"type":"int64","value":"100000000"}}]},
     {"type":"object_reference","target":{"objectId":"<close>","subType":"fact_metric","name":"Closing Price USD"}}]}]}},
 "dimty": null,
 "format": {"header":[],"values":[{"type":"number_category","value":"0"},{"type":"number_format","value":"#,##0.0"},{"type":"number_decimal_places","value":"1"}]}}
```
On GET, the service round-trips `expression.text`, e.g. `{Market Capitalization USD} / (({Output Value Satoshis} / 100000000) * {Closing Price USD})`. The CLI `create-compound-metric` (superseded `{type:operator/metric_reference}` guess, forces identity-on) does NOT produce this shape — POST the tree directly instead.

**Updating a compound metric (verified 2026-07-21):** `PATCH /metrics/{id}` is NOT a registered route (404 8004cc04), and the helper's `patch-model-object --kind metric` wrongly routes to `/factMetrics/{id}` (500 8004d706 subtype mismatch). Use **PUT `/api/model/dataModels/{id}/metrics/{mid}`** with a FULL body `{information, expression:{tree}, dimty: null, format}` in a changeset. GET returns the expression as read-only `text` only — you must supply the `tree` again on PUT (rebuild it; stripping text and sending an empty expression → 400 8004d718 "expression could not be set to empty").

**Format rendering gotcha (verified in dashboard KPI grid):** the `number_currency_symbol` field does NOT render in dashboard grids — only the `number_format` PATTERN does (percent `%` in the pattern renders fine). Put the literal `$` in the pattern (`$#,##0.00`), keep category/symbol fields set for semantics.

**Compound metrics at total grain:** with no attribute on a template, compounds evaluate as ratio-of-total-aggregates — NVT collapses to ~0.07, turnover inflates to ~960%, and SUM×AVG cross-terms shift products (year on-chain USD $23.90T at total vs $23.65T summed daily). Expected engine behavior, not a defect: put Date on the template or filter to a single day; for total-level KPI cards define separate day-level-scoped average variants.

## 0b. LEVEL metrics — verified WRITE path (2026-08-19, cross-store level-ratio build)

Section 3 below is a UI *capture*; writing level metrics programmatically hit five
gotchas before a fully validated recipe emerged (65/65 + 111/111 anchor values tied to
source; runnable end-to-end in `captures/20260819-dai-costs-impact/create_level_metrics.py`
+ `validate_level_metrics.py`):

1. **Tokens only — the tree format cannot express levels.** A tree whose root is a bare
   `object_reference` + non-null `dimty` → `8004d711` (the service does not classify a
   tree bare-reference as an "aggMetric reference"). Any operator root also requires
   `dimty: null`. So: compounds → tree; level metrics → tokens.
2. **EVERY token needs a `value` key — `end_of_text` included** (`{"type":"end_of_text",
   "value":""}`). Omitting it → `8004cb04` "Missing attribute v in element tkn" (gateway
   XML layer), a bodyless-looking 500 unless you print the errors array.
3. **Level pinning that actually pins: attribute-ONLY dimty + `{[Attr]+}` cluster.**
   The UI-captured shape (dimty `[report_base_level, attribute]`, cluster `{~+, [Attr]+}`)
   POSTs fine but evaluates at REPORT grain whenever the report is finer than the pin —
   values vary per child row (verified on a Team×Application grid). Dropping
   `report_base_level` from dimty AND the `~ +` from the cluster gives the true
   fixed-level benchmark (constant across child rows).
4. **`Sum()` over a count-function fact metric evaluates to NULL silently** (2xx create,
   null at query time). Re-aggregate counts as **`Count({attribute})`** instead — element
   count of the grain-anchor attribute == row count when it is the table PK. A bare
   metric-ref + level cluster without a function wrapper is rejected (`8004cd15` Invalid
   Expression), so the function wrapper is mandatory.
5. **Fact metrics cannot carry level dimty**: an `attribute` dimtyUnit on `/factMetrics`
   accepts only semi-additive aggregations (`DssAggregationFirstInFact/LastInFact/
   FirstInRelationship/LastInRelationship`) → `8004d716` for `normal`. Level pinning is a
   derived-metric (`/metrics`) concept only.

Composition that works: level intermediates via tokens (attr-only dimty), then a final
**tree `divide` of the two derived intermediates** (`object_reference` with
`subType:"metric"`, `dimty:null`) — derived-over-derived nesting evaluates fine, and the
finals are pure query-time formulas (no republish; only new FACT metrics need one).

Engine behavior worth knowing: a level metric is NULL for parent elements with no rows at
its source (correct sparse semantics — no fabricated zeros), and its presence on a v2
cube-instance grid drops those parents' rows entirely (inner-ish metric join), including
co-requested fact metrics — validate counts on a clean grid.

**`Count` function objectId: `8107C31CDD9911D3B98100C04F2233EA`** (platform constant;
discovered via Quick Search `/api/searches/results?name=Count&type=11`, fits the
`8107C31x` family below).

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
| Count | `8107C31CDD9911D3B98100C04F2233EA` |
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
