---
name: Strategy Tutorial semantic field study
description: Live REST inventory of MicroStrategy Tutorial classic semantic objects, including attributes, facts, metrics, filters, prompts, hierarchies, and translation cues for Mosaic.
type: reference
originSessionId: codex-session
---
Use this when the user asks to inspect, clone, modify, modernize, or mine a legacy/classic Strategy semantic layer. This is grounded in live REST reads from the `MicroStrategy Tutorial` project on `a verified Strategy Cloud tenant` on 2026-04-21.

Raw field-study output was written to `/tmp/strategy-tutorial-semantic-inventory-full.json`, with supplemental hierarchy verification at `/tmp/strategy-tutorial-hierarchies.json`; do not commit raw tenant payloads. Regenerate with:

```bash
cd "$REPO"
python3 skill/scripts/strategy_semantic_inventory.py \
  --workers 12 \
  --include-definition-bodies \
  --out /tmp/strategy-tutorial-semantic-inventory-full.json
```

The helper is read-only. It searches classic objects, reads Modeling Service definitions, records failures, and keeps successful raw bodies in `/tmp` only when `--include-definition-bodies` is passed.

## Auth and session nuance

For classic/project Modeling Service reads on this tenant:

- Use `X-MSTR-AuthToken` plus `X-MSTR-ProjectID`.
- Do not add `X-MSTR-IdentityToken` unless a specific classic endpoint proves it needs it; identity token previously caused false project errors.
- Preserve Strategy session cookies when doing threaded reads. Headers alone can return false `ERR009` session-expired responses.
- `showExpressionAs=tree` is best for analysis. Use `showFilterTokens=true` only for filters/security filters; sending filter-only params to attributes can produce misleading 400s.

## Inventory outcome

Classic object search found:

| Family | Search count | Definition reads OK | Definition reads failed | Main lesson |
| --- | ---: | ---: | ---: | --- |
| Attributes | 149 | 100 | 49 | Search returns real schema attributes plus Agent object-template attributes and transformation attributes. Filter by ancestor/subtype before editing. |
| Facts | 36 | 36 | 0 | Fact bodies are very complete: expressions, table mappings, entry level, and fact extensions. |
| Filters | 166 | 157 | 9 | Normal filter bodies read well; custom groups appeared in search as filter subtype `257` but are not supported by `/api/model/filters/{id}`. |
| Metrics | 715 | 692 | 23 | Metric bodies expose expression trees, nested metrics, dimty, conditionality, transformations, subtotals, smart totals, thresholds, and formatting. Managed/training/system-subtotal variants can fail. |
| Prompts | 189 | 91 | 98 | User-created prompts read; system prompts return an explicit "system prompt" error and should not be edited. |
| User hierarchies | 6 | 6 | 0 | Hierarchy bodies expose drill/browse attributes and parent/child paths; combine with system hierarchy for relationship tables. |

The system hierarchy read returned 73 relationships and 3 isolated attributes:

- Relationship types: 58 one-to-many, 14 one-to-one, 1 many-to-many.
- Top relationship tables: `LU_CUSTOMER`, `LU_SUPPLIER`, `LU_EMPLOYEE`, `LU_ITEM`, `LU_STORE`, `ORDER_FACT`.
- Useful examples: `Catalog -> Item` many-to-many via `REL_CAT_ITEM`; `Category -> Subcategory` via `LU_SUBCATEG`; `Subcategory -> Item` via `LU_ITEM`; `Customer -> Order` via `ORDER_FACT`.

Top table signals from definitions:

- Attributes: `LU_CUSTOMER`, `LU_EMPLOYEE`, `LU_SUPPLIER`, `ORDER_FACT`, `ORDER_DETAIL`, `F_TUTORIAL_TARGETS`, `LU_ITEM`, `LU_STORE`, `LU_CALL_CTR`.
- Facts: `ORDER_DETAIL`, `ORDER_FACT`, `CUSTOMER_SLS`, `F_TUTORIAL_REGION_TARGETS`, `INVENTORY_CURR`, `CITY_CTR_SLS`, `CITY_MNTH_SLS`, `CITY_SUBCATEG_SLS`.
- Filters usually reference semantic objects/elements rather than directly listing warehouse tables; follow their referenced attributes/metrics to tables.
- Metrics usually reference facts/metrics/filters, not tables directly; follow nested object references and fact definitions for warehouse table selection.

## Endpoint map

Search/browse first:

- `GET /api/searches/results?name=&type=<type>&pattern=4&limit=...&offset=...&getAncestors=true`
- Classic object types used in this study: filter `1`, metric `4`, prompt `10`, attribute `12`, fact `13`.

Read object definitions:

- `GET /api/model/attributes/{attributeId}?showExpressionAs=tree`
- `GET /api/model/facts/{factId}?showExpressionAs=tree`
- `GET /api/model/metrics/{metricId}?showExpressionAs=tree`
- `GET /api/model/filters/{filterId}?showExpressionAs=tree&showFilterTokens=true`
- `GET /api/model/prompts/{promptId}?showExpressionAs=tree`

Read relationships and hierarchies:

- `GET /api/model/systemHierarchy` returns all project attribute relationships and isolated attributes.
- `GET /api/model/systemHierarchy/attributes/{attributeId}/relationships` returns the relationship tuples for one attribute.
- `GET /api/model/hierarchies` lists user hierarchies.
- `GET /api/model/hierarchies/{hierarchyId}` returns a hierarchy definition with `information`, `useAsDrillHierarchy`, `attributes`, and `relationships`.
- Legacy element/drill helper: `GET /api/hierarchies/{hierarchyId}/attributes` is the runtime hierarchy-attributes path.

Create/update endpoints require Modeling Service changesets. Use `schemaEdit=true` for schema objects such as attributes, facts, relationships, hierarchies, transformations, partitions, and functions.

## Attribute anatomy

A normal classic attribute body contains:

- `information`: id, subtype `attribute`, name, dates, locale, ACG.
- `forms[]`: ID, DESC, and custom forms. Each form has `id`, `name`, `category`, `type`, `displayFormat`, `expressions[]`, table mappings, and `autoMapping`.
- `attributeLookupTable`: the primary lookup logical table.
- `keyForm`: the form used as the key.
- `displays`: default report/browse display forms.
- `relationships`: parent/child relationship tuples.
- Additional behavior flags: sorts, nonaggregatable, element caching, security-filter behavior, element display option.

Example product-chain findings:

- `Category` uses lookup table `LU_CATEGORY`.
- Its ID form expression is `category_id`, mapped to `LU_CATEGORY` and aggregate/fact tables such as `F_TUTORIAL_TARGETS`, `LU_SUBCATEG`, `MNTH_CATEGORY_SLS`, `QTR_CATEGORY_SLS`, and `YR_CATEGORY_SLS`.
- Its DESC form expression is `category_desc`, mapped to `LU_CATEGORY`.
- It has a custom picture form: `Concat("images/demo/s",category_id,".png")`.
- Relationship tuple: `Category -> Subcategory`, type `one_to_many`, relationship table `LU_SUBCATEG`.
- `Subcategory -> Item` is `one_to_many` via `LU_ITEM`.
- `Item` also shows many richer forms: long description, foreign name, price, image, barcode, barcode image, including `ApplySimple(...)` and `Concat(...)` expressions.
- `Item` has many parents, including `Subcategory`, `Supplier`, `Brand`, and a many-to-many `Catalog -> Item` relationship through `REL_CAT_ITEM`.

Important search gotchas:

- Exact names such as `Category`, `Day`, `Month`, and `Revenue` can appear under `Object Templates > Agents`. These read as subtype `3072`/`1024` but `/api/model/attributes/{id}` or `/api/model/metrics/{id}` can fail because they are agent/template metadata, not normal schema definitions.
- Transformation attributes under `System Objects > Transformation Attributes` fail through the normal attribute endpoint with "attribute_transformation is not supported yet." Read actual transformations through the transformation endpoint when needed.
- Always resolve by name + ancestor path + subtype before editing.

## Hierarchy anatomy

Two classic hierarchy concepts matter:

- **System hierarchy**: the global attribute relationship graph. It is the source of parent/child joins such as `Region -> Call Center`, `Category -> Subcategory`, `Subcategory -> Item`.
- **User hierarchy**: named drill/browse hierarchy objects. In Tutorial, `/api/model/hierarchies` returned six: `Geography`, `Customers`, `Time`, `Products`, `Product Hierarchy`, and `User-Defined Time Hierarchy`.

`GET /api/model/hierarchies/{id}` for `Geography` returned:

- `information.subType`: `dimension_user`.
- `useAsDrillHierarchy`: `true`.
- `attributes[]`: entries with `objectId`, `name`, `entryPoint`, and `elementDisplayOption`.
- `relationships[]`: parent/child pairs without always repeating relationship-table detail; combine with `systemHierarchy` if the join table is needed.

For Mosaic translation, system hierarchy relationships are the stronger source for physical relationship tables; user hierarchies are a curated navigation/drill experience.

## Fact anatomy

A classic fact body contains:

- `information`
- `dataType`
- `expressions[]`: each expression has text/tree, table mappings, and `autoMapping`.
- `extensions[]`: degradation/allocation/extension rules.
- `entryLevel[]`: attributes defining the fact grain.
- `alias`

Examples:

- `Revenue` has three expressions:
  - `tot_dollar_sales` mapped to aggregate sales tables such as `MNTH_CATEGORY_SLS`, `QTR_CATEGORY_SLS`, `CUSTOMER_SLS`, and `YR_CATEGORY_SLS`.
  - `qty_sold * (unit_price - discount)` mapped to `ORDER_DETAIL`.
  - `order_amt` mapped to `ORDER_FACT`.
- `Revenue` entry level includes `Day`, `Days to Ship`, `Employee`, `Item`, `Order`, and `Phone Usage`.
- `Profit` similarly maps to `order_amt - order_cost`, `qty_sold * ((unit_price - discount) - unit_cost)`, and `tot_dollar_sales - tot_cost`.
- `Revenue Target` maps `revenue_target` to both `F_TUTORIAL_TARGETS` and `F_TUTORIAL_REGION_TARGETS`, with entry level `Call Center`, `Month`, `Subcategory`.

Fact extensions are first-class:

- `Units Received`: `extensionMethod:"lower"` to `Day`, with allocation expression `{Units Received} / {Month Duration}`.
- `Freight`: `extensionMethod:"table"` to `Item`, guided by `ORDER_DETAIL`, allocating `(Freight * {Item-level Units Sold}) / {Order-level Units Sold}`.
- `Item inventory`: lower to `Day` with a constant/degradation extension.

For Mosaic candidate generation, fact expression tables are usually the strongest table signal. Preserve multiple fact expressions as candidate mappings; do not collapse them to one warehouse column until grain is reviewed.

## Metric anatomy

A classic metric body contains:

- `information`
- `expression`: text and tree. Trees are usually `object_reference`, `operator`, or `constant`.
- `dimty`: metric dimensionality/level and transformations.
- `conditionality`: filter embedding/reference behavior.
- `metricSubtotals`: system subtotals and possible subtotal implementation overrides.
- `smartTotal`
- `aggregateFromBase`, `subtotalFromBase`
- `dataType`
- `format`
- `thresholds`
- optional `columnNameAlias`

Patterns seen in Tutorial:

- Simple metrics often point at embedded aggregate metrics or facts through `expression.tree.type:"object_reference"`.
- Compound/nested metrics are operator trees. `Profit Margin` is `divide` with nested metric references to `Profit` and `Revenue`.
- Level metrics use `dimty.dimtyUnits`. `Category Revenue Abs.` adds the `Category` attribute with `filtering:"absolute"`; `Category Revenue Filt.` uses `filtering:"apply"`.
- Transformation metrics use `dimtyUnitType:"role"` with target subtype `role_transformation`, e.g. `Last Year's`, `Last Month's`, `Month to Date`, `Year to Date`, `Quarter to Date`.
- Conditional metrics use `conditionality.filter`. Examples include `Cost of Books` referencing the `Books` filter, and many "Top 50", "current year", and "web sales" filtered metrics.
- Metric formatting is tokenized in `format.header[]` and `format.values[]`; currency/percent/integer formatting lives there, not only in the expression.
- `smartTotal` and `metricSubtotals` are important behavior, especially for ratios like `Profit Margin`, where subtotal implementation can differ from row formula behavior.

Top metric functions seen across successful reads included `divide`, `minus`, `custom`, `times`, `plus`, `equals`, `case`, `running_sum`, `rank`, `if`, `olap_sum`, `lag`, `moving_avg`, `days_between`, and `apply_simple`.

Unsupported/noisy metric reads:

- Agent template metrics can appear in search and fail normal metric reads.
- Managed metrics returned "We do not support managed metric."
- Some system-subtotal related metric reads failed because the endpoint expected metric subtypes rather than `system_subtotal`.
- DMX/training metrics often search successfully; some read, some need data-mining-specific handling before cloning.

## Filter anatomy

A normal filter body contains:

- `information`
- `qualification.text`
- `qualification.tree`
- `qualification.tokens` when `showFilterTokens=true`

Qualification tree types observed:

- `predicate_element_list`
- `predicate_metric_qualification`
- `predicate_form_qualification`
- `predicate_relationship`
- `predicate_filter_qualification`
- `predicate_report_qualification`
- `predicate_prompt_qualification`
- `operator`

Function/operator names observed included `in`, `less_equal`, `equals`, `and`, `greater`, `add_days`, `between`, `less`, `greater_equal`, `or`, `not_in`, `not_between`, `is_not_null`, and `intersect`.

Examples:

- `Books` is `Category = Books`:
  - tree type `predicate_element_list`
  - `attribute`: Category (`8D679D3711D3E4981000E787EC6DE8A4`)
  - `elements`: `Books`, element id `h1`
  - function `in`
  - tokens include object reference `Category`, function `In`, and element token `{Category=Books}`.
- `Customer Region = ?` is a prompt-backed element list:
  - tree type `predicate_element_list`
  - `predicateTree.elementsPrompt` points to embedded prompt `Customers segmentation by region`
  - tokens show the prompt as an object reference.

Custom groups appeared in filter search as subtype `257`, but `/api/model/filters/{id}` returned "custom_group is not a supported object type." Route those through the custom group/consolidation APIs, not the filter endpoint.

## Prompt anatomy

Prompt definitions are metadata objects; prompt answers are runtime instance actions and live under report/document/dashboard prompt-answer endpoints.

A readable prompt body can contain:

- `information`
- `title`
- `instruction`
- `question`
- `defaultAnswer`
- `restriction`
- `expressionType` for expression prompts

Examples:

- Object prompt `Choose from a list of metrics` has `question.predefinedObjects[]` for `Revenue`, `Cost`, `Profit`, `Profit Margin`, and `Units Sold`.
- Element prompt `Choose from the Elements of Customer` has `question.attribute` pointing at `Customer` and `listAllElements:true`.
- Element prompt `Choose one or more years` has predefined elements for 2020, 2021, and 2022, a default answer of 2022, and `restriction.required:true`.

System prompts are intentionally not editable through `/api/model/prompts/{id}` and return a 400 error saying the prompt is a system prompt. Do not treat that as an auth failure.

## Legacy-to-Mosaic translation rules

When mining classic objects to propose a Mosaic model:

1. Start from the business content or table named by the user.
2. Resolve exact objects with search + ancestors. Ignore agent templates and system-only artifacts unless the user explicitly asks about them.
3. For attributes, collect lookup tables, all form expressions, display forms, and relationships. These become Mosaic attributes, forms, displays, and relationship candidates.
4. For facts, collect every expression/table mapping, entry level, and extension. These become candidate fact metrics, reusable facts, grain notes, and allocation/degradation review items.
5. For metrics, preserve expression text/tree, nested metrics, dimensionality, conditionality, transformations, smart totals, subtotal implementations, thresholds, and format. These become derived metric candidates or validation fixtures.
6. For filters, identify whether the filter is element-list, form qualification, metric qualification, filter qualification, prompt-backed, report qualification, relationship qualification, or custom-group-like. Only convert to Mosaic filters/security filters when the behavior belongs in the model.
7. For prompts, decide whether the prompt is content runtime behavior, a reusable prompt object, or a candidate model filter/default. Do not put every prompt into Mosaic by default.
8. For hierarchies, use system hierarchy relationship tuples for join semantics and user hierarchies for curated drill paths.
9. Use reports/documents/cubes as validation fixtures after building a Mosaic model; do not blindly mirror one report layout as a domain model.

## Automation quality gates

- Read before write. For classic edits, start from a successful `GET` body and patch only after object ID, ancestor path, subtype, and changed top-level fields are clear.
- PATCH/PUT bodies for Modeling Service often replace top-level sections. Preserve fields that must survive.
- Use changesets and commit only after referenced objects exist; discard failed changesets.
- When endpoint behavior differs from OpenAPI, prefer live tenant evidence and record it here or in a more specific memory file.
- Keep raw payloads in `/tmp`; commit compact lessons and helper scripts only.
