---
name: mosaic-ship-bar
description: The consumer-grade ship bar for every Mosaic model — naming, form displays, metric formats, descriptions (incl. the ~250-char model cap), security-filter naming, and the pre-ship checklist; load before building or before reporting any build complete.
type: feedback
---
Every Mosaic model shipped to users must be **consumer-grade**: names readable by business users, descriptions business-friendly, metric formatting sensible, zero leftover schema jargon. No "<Entity> None" categories, no empty form names, no "Column X from table Y" boilerplate, no hardcoded example usernames.

**Why:** the user explicitly called this out after observing form names like "R Regionkey ID" and "Customer None" on a first-pass build. Consumer-grade quality is the release bar; remediation after the fact is expensive and error-prone on {MSTR_BASE host} (see the `8004cc63` note under Form naming). These rules are the difference between "Mosaic model that technically works" and "Mosaic model I can hand to an SE for a customer demo."

**How to apply:** run the checklist at the bottom before reporting a build complete. If anything in this file is missing or wrong, treat the build as incomplete.

## Attribute naming

- **Entity attribute = business noun, not technical key name.** `Order`, `Line Item`, `Customer`, `Supplier` — never `Order Key`, `Line Number`, `Customer ID`. The key value is a *form* on the entity, not the entity itself.
- **Conformed attributes span tables.** When the same logical entity appears in multiple tables (e.g., `Customer` with `C_CUSTKEY` in CUSTOMER and `O_CUSTKEY` in ORDERS), the single attribute must have expressions on every table it appears in. TPC-H-style per-table FK prefixes (`R_/N_/C_/O_`) break the build-skill's auto-conformance detection — either clone-and-remap from a reference model, or hand-declare conformance in the dictionary.
- **No per-column duplicates.** If `C_NATIONKEY` exists as its own attribute while `Nation` already exists, you have duplicates. Delete the FK-side duplicate and add its column as an expression on the parent entity.
- **Descriptor attributes use business labels.** `Customer Market Segment`, `Part Brand`, `Order Priority` — not `Mktsegment`, `P Brand`, `O Orderpriority`.

## Form naming

- **Every form must have a non-empty `name`.** Mosaic rejects PATCH with `8004cd0a "form property requires a non-empty name"`. During CREATE you can omit name, but during UPDATE every form in the patched `forms` list must have a name.
- **Empty form names are the single worst Mosaic build defect.** They silently disable Strategy's auto-hierarchy-relationship detector (so intra-table fan-outs like `Customer Address → Customer`, `Part Brand → Part`, `Order Status → Order Key` never get created) and they render as blank column headers in Library. Observed on a script-built TPC-H model: 44 of the expected 54 relationships missing plus blank report headers, all traceable to `forms[i].name == ""`.
- **Fix at create time, fail the changeset otherwise.** In any attribute create path, derive `forms[i].name` from the semantic column name (title-case, no underscores) before the POST; if a category is set but the name is not, copy the category into the name. Treat `forms[i].name == ""` as a hard build failure — fail the changeset, not the report. Verify post-commit by reading the attribute list and asserting every form name is non-empty.
- **Reference-clone pattern drops `form.name`.** A canonical reference-clone script once wrote forms without `name`, surfacing blank labels. The fix is one line — `"name": form.get("name", "") or form.get("category", "")` — applied to any clone-and-remap script; see `reference_strategy_object_cloning.md`.
- **Form categories should read cleanly.** Use `Key`, `Name`, `Description`, `Comment`, etc. — not `<Entity> None` (the default when no DESC form was explicitly named) or `<Attribute> None (1)`.
- **Post-build form-category PATCH is fragile on {MSTR_BASE host}.** `PATCH /api/model/dataModels/{mid}/attributes/{aid}` with `{forms:[...]}` returns `8004cc63 "Attribute does not contain a form with the ID"` even when GET returns that exact ID. Fix form names at **CREATE time**, not via post-hoc PATCH.
- **ID-form aliases are acceptable tech artifacts.** `alias: "C_CUSTKEY"` on the ID form is fine; the user never sees it. The user-facing `name` and `category` are what matter.

## Form displays — DESC forms are the display + browse forms

When creating a multi-form attribute, the ID form is the key for joins but **must never** be the form a user sees on a report or a prompt element list. Always set:

```json
"displays": {
  "reportDisplays":  [ {"id": "<desc form id>", "name": "DESC"} ],
  "browseDisplays":  [ {"id": "<desc form id>", "name": "DESC"} ]
}
```

- If the attribute has one DESC form, both arrays reference it.
- If the attribute has multiple DESC-category forms (DESC + Long Desc + Foreign Name, etc.), `reportDisplays` lists them in priority order; `browseDisplays` uses the most-readable one (typically DESC).
- If the attribute is ID-only (no DESC exists), **don't** leave displays as `[{"id":ID_FORM}]`; either skip the `displays` block entirely or add a compact text form synthesized from the ID (e.g., `"Brand " + BRAND_ID`).

**Why:** users in Library/Dossier/prompts see raw ID numbers instead of names when the display form defaults to ID. Every consumer-grade complaint I've seen against auto-built models traces to this default. The legacy semantic layer already has this configured correctly — mirror it when porting.

**How to apply:** after every `make_attr()` call in the build helper, update the displays block before POST. For the build-mosaic skill, change the default `displays` generator to use the first non-ID form if one exists; only fall back to ID when no descriptor exists.

## Metric naming and aggregation

- **Name = business concept.** `Order Total Price`, `Line Extended Price`, `Avg Discount Rate` — not `Sum O Totalprice` or `L Discount Sum`.
- **Put the aggregation in the name only when it disambiguates.** Use `Avg Discount Rate` (distinguishes from a hypothetical `Total Discount`), but not `Sum Line Quantity` (the default is obvious).
- **Aggregation function must match business semantics — classify per column family, not per column:**
  - **Additive measures → `SUM`** — monetary totals, counts, quantities, extended amounts, balances rolled up across a portfolio (`EXTENDEDPRICE`, `TOTALPRICE`, `QUANTITY`, `AVAILQTY`, `ACCTBAL` when rolling up a portfolio).
  - **Averageable rates / ratios / percentages → `AVG`** — `DISCOUNT`, `TAX`, any `_RATE`/`_PCT`/`_RATIO` column.
  - **Point-in-time unit values** (unit_price, list_price, retail_price, supply_cost) → `AVG` at dim grain, kept raw at transaction grain; emit a derived SUM(qty × price) compound metric for transaction totals. `SUM` only when the explicit business ask is a total (e.g., `RETAILPRICE` when aggregating catalog value, `SUPPLYCOST` when totaling supplier spend). *(Resolution of an earlier inconsistency between the naming and build-quality memories: the conditional reading wins — default AVG for unit values, SUM only on an explicit total-value ask.)*
  - **Semi-additive balances → `LAST` or `AVG`** — `ACCTBAL` at a single time-point, inventory snapshots, etc.
  - **Entity counts → `COUNT` / `COUNT_DISTINCT`.** **Bounds → `MIN`/`MAX`.**
  - Default is `SUM`; override explicitly via dictionary `metrics.{TABLE.COLUMN}.function`.
- **Surface the classification.** Run a column-name classifier in the build and emit a per-metric table in the build log: `column → family → chosen function`. The user can override via config.
- **Reserve AVG-style renames for true rate metrics.** If `Discount` is renamed to `Avg Discount Rate` so it reads honestly, do the same for `Tax` → `Avg Tax Rate`. Don't leave one renamed and the other not.
- **Verify on at least 3 ambiguous measures** before calling the build done.

## Metric formats

The Modeling Service `format.values[]` token list drives how numbers render. Never ship a metric with the default "generic" format — pick a format based on what the metric represents:

| Metric kind | Format category | Token shape |
|---|---|---|
| Dollar/currency (Revenue, Cost, Profit, Sales, Price) | currency | `[{"type":"number_category","value":"2"},{"type":"number_decimal_places","value":"2"},{"type":"number_format","value":"$#,##0.00;($#,##0.00)"}]` — or locale-appropriate symbol |
| Percent (Discount Rate, Margin, Growth %) — 0-1 scale | percent | `[{"type":"number_category","value":"5"},{"type":"number_decimal_places","value":"2"},{"type":"number_format","value":"0.00%"}]` |
| Count / Units / Quantity | integer | `[{"type":"number_category","value":"1"},{"type":"number_decimal_places","value":"0"},{"type":"number_format","value":"#,##0"}]` |
| Fixed decimal (Price per unit, Ratio) | fixed | `[{"type":"number_category","value":"1"},{"type":"number_decimal_places","value":"2"},{"type":"number_format","value":"#,##0.00"}]` |
| Very large magnitudes (Trade Volume, Population) | scientific | `[{"type":"number_category","value":"7"},{"type":"number_decimal_places","value":"2"},{"type":"number_format","value":"0.00E+00"}]` |
| Date-like numeric (YearMonth, YYYYMMDD key) | integer, no thousands sep | `[{"type":"number_category","value":"1"},{"type":"number_decimal_places","value":"0"},{"type":"number_format","value":"0"}]` |

Everything else gets an explicit 2-decimal fixed format so the default doesn't render with 6+ trailing zeros.

**Verified format.values shape (Strategy ONE 2026):** entries use `{type, value}` pairs, NOT `{category, formatString}` pairs. The Modeling Service rejects `{category: X}` payloads with `Unrecognized field: category`. Each format property is its own entry — `number_category`, `number_decimal_places`, `number_format` are independent.

**`number_category` enum (tenant-verified, canonical):** 0=General, 1=Number, 2=Currency, 3=Date, 4=Time, 5=Percentage, 6=Fraction, 7=Scientific, 9=Accounting.

Assignment heuristic (apply **before** build, cache in the dictionary):

1. **Name-based first pass.** If metric name contains `Revenue|Sales|Cost|Profit|Amount|Price|Spend|Expense` → currency. If it contains `%|Percent|Rate|Margin|Growth|Share` → percent. If it contains `Count|Qty|Quantity|Units|Orders|Transactions` → integer. `Ratio|Index|Score` → fixed decimal.
2. **Datatype fallback.** Integer/bigint source column → integer. Decimal with scale ≥ 2 → currency (conservative) unless the metric is ID-flavored. Decimal with scale 0 → integer.
3. **Scientific only when justified.** Use for columns whose observed magnitudes exceed 10⁹ in the warehouse, not by default.

**Why:** a validation dossier in Library that shows `Revenue: 41735.50` for every row is non-consumable. Finance users reject it before touching the data. The legacy MSTR project carries formats on every metric (see `format.values` in `GET /api/model/metrics/{id}`); the auto-builder omits them.

**How to apply:** extend `build_mosaic.py` so every metric POST includes a `format.values` block derived from (name, datatype). Keep `CURRENCY_METRICS` / `PERCENT_METRICS` / `INTEGER_METRICS` sets in the build script so formatting isn't a guessing game. Add a `--format-override` CLI flag for per-metric explicit formats when the heuristic picks wrong. When mirroring a legacy model, copy the legacy metric's `format.values` array verbatim — MSTR formats are JSON-portable across tenants.

## Descriptions

- **Business-first, not schema-first.** "Customer account balance used for credit, billing, and AR analysis" — not "Sum of C_ACCTBAL from CUSTOMER".
- **One sentence, end with a period.** Two sentences only when enumerated codes need explanation (e.g., `Order Status`: "Current order status (O = open, F = finalized, P = partial).").
- **Include domain hints when the column is cryptic.** `C_MKTSEGMENT` description should enumerate valid values; `O_ORDERPRIORITY` should enumerate priority tiers; `L_RETURNFLAG` should decode `R/N/A`.
- **Every attribute and every metric gets a description.** If the dictionary has a column, the description is written; if auto-detection added an attribute we didn't predict, it still needs one. Run a post-build audit — no `description: ""` or `description: null` is acceptable.
- **Run the description pass AFTER renames.** If you rename `Order Key` → `Order`, but the description map is keyed on `Order Key`, the description gets skipped. Either re-key the map post-rename, or run descriptions before renames and include both old+new names in the lookup.

### Model-description length cap (~250 chars)

Observed on a Strategy ONE Cloud tenant (captured run): PATCH `/api/model/dataModels/{id}` with `information.description` of ~700 chars → `400 8004cc10 "Object Description <full text> ..."` (the server echoes the rejected text; the error text itself is the truncation); ~480 chars → same error; ~205 chars → `200 ok`, commit 201. Empirically, **~250 chars is the safe ceiling** for Mosaic data-model descriptions on this tenant family — the iServer may be enforcing the classic MicroStrategy 255-char `ObjectInfo.Description` limit. Any automation that derives a description from warehouse metadata must truncate — or, better, summarize — before the PATCH.

- Keep the model description to one or two sentences, under ~250 chars. Prioritize: purpose, primary source DBs, grain, and any row-level security note.
- Put fuller modeling notes (aggregation rules, grain per table, ratio-safety caveats) in an external README or a `captures/<run>/model-design.md`, not the Mosaic description.
- If the model's automation wants to attach the full dictionary / ERD / validation artifact, store it in the repo or the skill's `examples/` directory and link it from the model's README rather than trying to cram it into the description.
- Do NOT retry blindly on `8004cc10` — it's a length-class error, not transient. Truncate and retry once.
- Attribute and metric descriptions on the same tenant appear to have a similar cap, though measurement is less rigorous. Err on the side of one-sentence descriptions when PATCHing in bulk.

## Security filter naming

When creating a security filter via `POST /api/model/dataModels/{id}/securityFilters` (Mosaic) or `/api/model/securityFilters` (classic), the `information.name` must describe the qualification itself, not the user it's assigned to or the date it was created. Generic names like "SF <user>" or "Row-level filter" are not acceptable.

**Why:** SFs are reused across users, groups, and audits. A name keyed to "who" (e.g., "SF <username> access") goes stale the moment the membership changes and hides the security rule from reviewers. Names keyed to "what" ("Region = EMEA") remain accurate for the life of the qualification.

**How to apply:**
- Single-value equals qualification → `"{Attribute} = {value}"`.
- In-list → `"{Attribute} IN ({v1}, {v2})"`.
- Range / inequality → `"{Attribute} >= {value}"`, `"{Attribute} BETWEEN {a} AND {b}"`.
- Compound → join with ` AND ` / ` OR ` at the top level: `"Region = EMEA AND Segment = Enterprise"`.
- If the qualification references a metric ranking → `"{Metric} top {N}"`.
- Prefer the human-readable display value, not the element ID (e.g., "Region = EMEA", not "Region.REGION_ID = hEMEA"). The element-ID / form binding is an implementation detail of the REST payload, not a consumer-facing name.
- Keep the `description` field for extra context (e.g., "Row-level security — restricts to a single tenant for scoped access"), not the qualification itself.

**When not applied:** if a filter is genuinely generic (e.g., a named operator role with multiple qualifications spliced together for a specific business reason), use a short business-domain name AND include the qualification summary in the description. Never use a purely administrative placeholder like `SF_NEW_1`.

**Automation rule:** `build_mosaic.py add-security-filter` takes `NAME=ATTR_ID[:FORM_ID]=VALUE|USER,...`. Any automation that wraps this must derive a qualification-descriptive `NAME` from the attribute name and value, not accept an arbitrary placeholder. Similarly, scripts that create SFs directly via REST must assemble the name from the qualification fields before POST.

## Cleanliness rules

- **Never hardcode example user identities.** No real personal names, tenant-internal usernames, placeholder-user fixtures, or example emails in any build script, memory file, or security-filter helper. Security filters are opt-in and parameterized: `add_security_filter(model_id, member_user_ids=[...])`. Example names drift, get copy-pasted into production, and are awkward for anyone else running the script.
- **Never hardcode credentials.** `MSTR_PASSWORD` env var only; do not commit passwords even to a script in `~/Desktop` — treat that as potentially sharable/visible.
- **Don't ship with raw column-name attribute names.** `R Regionkey`, `N Name`, `O Orderdate` — these are intermediate build artifacts. Either the dictionary renames them, or the build-skill's title-casing renames them (e.g., `Order Date`), or they don't ship.
- **Verify against a live query.** End-to-end means: attribute joins return expected cardinality, metric aggregates match a known-good reference, hierarchy drill works in Library UI (or at least in Trino).

## Validation hooks

`build_mosaic.py validate-model` (see `reference_mosaic_build_validation.md`) must explicitly fail a model that has:
- Any attribute with multiple forms whose `displays.reportDisplays[0].id == ID_FORM`.
- Any metric with empty `format.values[]` or `category:"Generic"`.

Every new model must pass both the display rule and the format rule before `validate-model` is considered done.

## Consumer-grade checklist (run before reporting a build complete)

1. Every attribute has a business-name (not a technical column name).
2. Every form has a non-empty `name`; DESC forms read as `Name`, `Description`, `Comment`, etc.
3. Every attribute and metric has a business-friendly description.
4. Metric aggregation functions match the business intent (SUM/AVG/etc.); verify on at least 3 ambiguous measures.
5. Every metric has a number-format token list matching its category (currency/percent/integer/decimal).
6. Relationships connect the right hierarchy — spot-check with a query that joins 2+ dim levels and a fact.
7. No hardcoded example users or personal names anywhere in the build script or filter definitions.
8. At least one validation query returns aggregates matching a known-good reference (see `skills/strategy-validation/SKILL.md` and `memory/reference_strategy_data_validation.md` for the paired-query validation suite; comparator can be another Mosaic model, a classic report, a flat file, direct warehouse SQL, or a REST fixture).
