---
name: Mosaic derived metrics (compound, conditional, level) — verified UI shapes + write paths
description: Exact REST bodies for compound / conditional / level metrics. UI captures (ratio, filter-scoped, level) plus the verified scripted WRITE paths — tree compounds, level tokens with filtering semantics, one-changeset conditional metrics via embeddedObjects — and the verified number_category format enum. Supersedes the earlier tokens-only guess in the build skill.
type: reference
---

Sections 1–3 are real Studio UI saves (read-back shapes). Sections 0, 0b and 0c are the verified scripted WRITE paths — start there when automating. The `/api/model/dataModels/{mid}/metrics` endpoint (**not** `/factMetrics`) is used for derived metrics. Fact metrics keep their `/factMetrics` endpoint.

## Endpoint

```
POST   /api/model/dataModels/{mid}/metrics?showAdvancedProperties=true
PUT    /api/model/dataModels/{mid}/metrics/{metricId}?showAdvancedProperties=true    (full body; PATCH is not a route → 404, see §0)
POST   /api/model/dataModels/{mid}/metrics/{metricId}/embeddedObjects                  (embedded filter of a conditional metric, §0c)
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

**Format rendering gotcha (verified in dashboard KPI grid):** the `number_currency_symbol` field does NOT render in dashboard grids — only the `number_format` PATTERN does (percent `%` in the pattern renders fine). Put the `$` in the pattern as a quoted literal and keep the category/symbol fields set: category `1` + `"$"#,##0.00;"$"-#,##0.00` + symbol `$` renders everywhere (verified 2026-09-29; see "Format tokens" for the category enum — `2` is Date, not Currency).

**Compound metrics at total grain:** with no attribute on a template, compounds evaluate as ratio-of-total-aggregates — NVT collapses to ~0.07, turnover inflates to ~960%, and SUM×AVG cross-terms shift products (year on-chain USD $23.90T at total vs $23.65T summed daily). Expected engine behavior, not a defect: put Date on the template or filter to a single day; for total-level KPI cards define separate day-level-scoped average variants.

## 0b. LEVEL metrics — verified WRITE path (2026-08-19, cross-store level-ratio build)

Section 3 below is a UI *capture*; writing level metrics programmatically hit five
gotchas before a fully validated recipe emerged (65/65 + 111/111 anchor values tied to
source; runnable end-to-end in `captures/20260819-devops-costs-impact/create_level_metrics.py`
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

**Filtering on the level unit (verified 2026-09-29).** For an attribute-only level metric pinned
at a parent attribute and used as a share-of-parent denominator — e.g. `Sum(Total Cost)` at
Customer Segment, with Customer on the report rows — the level unit's `filtering` decides what
report filters do to the parent total:

- `"apply"` — shrinks the parent total to the filtered children: a customer filter makes the
  segment total equal those customers' total (their shares then sum to 100%). Not a benchmark.
- `"absolute"` — keeps the whole parent, but ALSO drops a filter in another hierarchy: a month
  filter no longer restricts the denominator, so a one-month numerator is divided by an
  all-months parent.
- `"ignore"` — keeps the whole parent AND honors the month filter. **The correct choice for
  benchmarks** (share-of-parent, index-vs-peers).

```json
{"dimtyUnitType": "attribute",
 "target": {"objectId": "<parent attr id>", "subType": "attribute", "name": "<Parent Attribute>"},
 "aggregation": "normal", "filtering": "ignore", "groupBy": true}
```

Precondition: the level attribute must be a true **ancestor** of the report rows in the model's
relationship graph (parent → … → row attribute, e.g. Customer Segment → Customer). Check the
chain before trusting a benchmark — `get_attribute_relationships()` in
`skills/build-mosaic-model/scripts/build_mosaic.py` reads an attribute's `relationships`.

Engine behavior worth knowing: a level metric is NULL for parent elements with no rows at
its source (correct sparse semantics — no fabricated zeros), and its presence on a v2
cube-instance grid drops those parents' rows entirely (inner-ish metric join), including
co-requested fact metrics — validate counts on a clean grid.

**`Count` function objectId: `8107C31CDD9911D3B98100C04F2233EA`** (platform constant;
discovered via Quick Search `/api/searches/results?name=Count&type=11`, fits the
`8107C31x` family below).

## 0c. Conditional metrics — verified WRITE path (2026-09-29)

Verified against a live Strategy ONE Cloud tenant with two conditional metrics (e.g. a Burst
Cost metric filtered by a Workload Type attribute): values tied exactly to hand-filtered
totals via MCP `query`, and the metric is NULL (not 0) on non-qualifying elements. This
supersedes the separate-`/filters` note in section 2 and the old `create-conditional-metric`
shape (`/factMetrics`, `?changesetId=`, an invented `conditionality` block). Runnable as
`build_mosaic.py create-conditional-metric` (`cmd_create_conditional_metric()` in
`skills/build-mosaic-model/scripts/build_mosaic.py`).

All three writes go in **ONE changeset** with the identity token ON (`X-MSTR-IdentityToken`;
the changeset rides the `X-MSTR-MS-Changeset` header). Identity ON is what the verified run
used; if Modeling writes 403 with `8004cb09`, see `feedback_mosaic_identity_token_privilege_downgrade.md`.

**(a) Create the unfiltered metric** — `POST /api/model/dataModels/{mid}/metrics?showAdvancedProperties=true`,
tokens for `Sum<UseLookupForAttributes=False>([Fact Metric]){~+}` and a `report_base_level`
dimty. Every token carries a `value`, `end_of_text` included (0b rule 2):

```json
{"information": {"name": "<metric name>", "subType": "metric"},
 "expression": {"tokens": [
   {"type": "function", "value": "Sum", "target": {"objectId": "8107C31BDD9911D3B98100C04F2233EA", "subType": "function", "name": "Sum"}},
   {"type": "character", "value": "<"}, {"type": "identifier", "value": "UseLookupForAttributes"},
   {"type": "function", "value": "="}, {"type": "boolean", "value": "False"}, {"type": "character", "value": ">"},
   {"type": "character", "value": "("},
   {"type": "object_reference", "value": "[<Fact Metric>]", "target": {"objectId": "<fact metric id>", "subType": "fact_metric", "name": "<Fact Metric>"}},
   {"type": "character", "value": ")"},
   {"type": "character", "value": "{"}, {"type": "character", "value": "~"},
   {"type": "character", "value": "+"}, {"type": "character", "value": "}"},
   {"type": "end_of_text", "value": ""}]},
 "dimty": {"dimtyUnits": [{"dimtyUnitType": "report_base_level", "aggregation": "normal", "filtering": "apply", "groupBy": true}],
           "excludeAttribute": false, "allowAddingUnit": true},
 "format": {"header": [], "values": [/* see "Format tokens" below */]}}
```

**(b) Embed the filter in that metric** — `POST /api/model/dataModels/{mid}/metrics/{metricId}/embeddedObjects`
(the verified run also passed `?showExpressionAs=tree`). The response `id` is the embedded filter id:

```json
{"subType": "filter",
 "qualification": {"tree": {"type": "predicate_element_list", "predicateTree": {
   "attribute": {"objectId": "<attribute id>", "subType": "attribute", "name": "<Attribute>"},
   "elements": [{"elementId": "h<ID form value>;<attribute id>", "display": "<value>"}],
   "function": "in"}}}}
```

The element id carries the `;<attribute id>` suffix — unlike the bare `h<value>` of the
security-filter Shape B in `reference_mosaic_security_filter.md`.

**(c) Bind it** — `PUT /api/model/dataModels/{mid}/metrics/{metricId}?showAdvancedProperties=true`
with the full body from (a), its tokens extended by `<`, the embedded-filter reference and `>`
just before `end_of_text`, plus a top-level `conditionality` block:

```json
{"type": "character", "value": "<"},
{"type": "object_reference", "value": "", "target": {"objectId": "<embedded id>", "subType": "filter", "isEmbedded": true}},
{"type": "character", "value": ">"},
{"type": "end_of_text", "value": ""}
```

```json
"conditionality": {"filter": {"objectId": "<embedded id>", "subType": "filter", "isEmbedded": true},
                   "embedMethod": "report_into_metric_filter", "removeElements": true}
```

Then **commit**. On any failure, discard the changeset — the half-built metric and its embedded
filter go with it. The conditional metric composes like any derived metric: a tree `divide` of it
over its unfiltered source (a filtered share of the total) evaluated correctly in the same run.

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

**Building the embedded filter:** superseded by §0c. The filter is created under the metric itself (`POST .../metrics/{metricId}/embeddedObjects`), not through the model's `/filters` endpoint, and create → embed → bind fits in ONE changeset. Do not follow the earlier note here (separate `/filters` POST, then the metric in a second changeset) — it is not the verified path.

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

**`number_category` enum (Modeling service, verified 2026-09-29 against a live tenant):**
`0`=Fixed, `1`=Currency, `2`=Date, `3`=Time, `4`=Percentage, `5`=Fraction, `6`=Scientific,
`7`=Special, `8`=Custom, `9`=General. An earlier version of this file said `2` = Currency and
`5` = Percentage — wrong: writing `2` for money makes the UI render the amounts as dates.

Verified recipes (the currency one renders everywhere, dashboard grids included):

| Kind | `number_category` | `number_format` | Also set |
|---|---|---|---|
| Currency | `1` | `"$"#,##0.00;"$"-#,##0.00` | `number_currency_symbol` = `$`, `number_decimal_places` = `2` |
| Percent (0–1 scale) | `4` | `0.0%` | `number_decimal_places` = `1` |

Currency exactly as the verified run wrote it:

```json
[
  {"type": "number_category", "value": "1"},
  {"type": "number_format", "value": "\"$\"#,##0.00;\"$\"-#,##0.00"},
  {"type": "number_currency_position", "value": "0"},
  {"type": "number_currency_symbol", "value": "$"},
  {"type": "number_decimal_places", "value": "2"},
  {"type": "number_negative_numbers", "value": "1"},
  {"type": "number_thousand_separator", "value": "true"}
]
```

Captured UI example — a ratio saved with category `0` (Fixed) plus the currency fields:

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

When building by script, take the category from the enum above — money written as `2` renders as dates. Plain counts and fixed decimals use `0` (Fixed), percentages `4`, currency `1`, scientific `6`.

## Takeaways for the build helpers

1. Use `/metrics` for compound/conditional/level metrics; keep `/factMetrics` for plain aggregates.
2. Always POST with `?showAdvancedProperties=true`.
3. Emit the `{~+}` trailer on every report-level token list (a level metric pinned at an attribute uses `{[Attr]+}` instead — §0b rule 3).
4. Wrap every aggregate with `<UseLookupForAttributes=False>` unless you know you want lookup-table joins.
5. For conditional metrics, follow §0c: create the metric, `POST .../embeddedObjects` for the filter, `PUT` the metric with the filter-bound tokens + `conditionality` — all in ONE changeset.
6. For level metrics, use an attribute-ONLY dimty plus the `{[Attr]+}` cluster (§0b rule 3); the UI's `report_base_level` + `{~+, [Attr]+}` shape evaluates at report grain. Use `filtering: "ignore"` for benchmarks (§0b).
7. Match the format.values fields to the metric's semantic category (money, percent, fixed decimal, etc.) with the verified `number_category` enum above.
