---
name: Consumer-grade naming rules for Mosaic models
description: Durable rules for naming attributes, forms, metrics, and descriptions so every model shipped is consumer-grade from day one.
type: feedback
---
Every Mosaic model shipped to users must be **consumer-grade**: names readable by business users, descriptions business-friendly, metric formatting sensible, zero leftover schema jargon. No "<Entity> None" categories, no empty form names, no "Column X from table Y" boilerplate, no hardcoded example usernames.

**Why:** the user explicitly called this out after observing form names like "R Regionkey ID" and "Customer None" on a first-pass build. Consumer-grade quality is the release bar; remediation after the fact is expensive and error-prone on {MSTR_BASE host} (see `8004cc63` note below).

**How to apply:** run this checklist before reporting a build complete. If anything in this list is missing or wrong, treat the build as incomplete.

## Attribute naming

- **Entity attribute = business noun, not technical key name.** `Order`, `Line Item`, `Customer`, `Supplier` — never `Order Key`, `Line Number`, `Customer ID`. The key value is a *form* on the entity, not the entity itself.
- **Conformed attributes span tables.** When the same logical entity appears in multiple tables (e.g., `Customer` with `C_CUSTKEY` in CUSTOMER and `O_CUSTKEY` in ORDERS), the single attribute must have expressions on every table it appears in. TPC-H-style per-table FK prefixes (`R_/N_/C_/O_`) break the build-skill's auto-conformance detection — either clone-and-remap from a reference model, or hand-declare conformance in the dictionary.
- **No per-column duplicates.** If `C_NATIONKEY` exists as its own attribute while `Nation` already exists, you have duplicates. Delete the FK-side duplicate and add its column as an expression on the parent entity.
- **Descriptor attributes use business labels.** `Customer Market Segment`, `Part Brand`, `Order Priority` — not `Mktsegment`, `P Brand`, `O Orderpriority`.

## Form naming

- **Every form must have a non-empty `name`.** Mosaic rejects PATCH with `8004cd0a "form property requires a non-empty name"`. During CREATE you can omit name, but during UPDATE every form in the patched `forms` list must have a name.
- **Reference-clone pattern drops `form.name`.** The canonical `build_tpch_mosaic_model.py` originally wrote forms without `name`, surfacing blank labels. The fix is one line — `"name": form.get("name", "") or form.get("category", "")` — applied to any clone-and-remap script.
- **Form categories should read cleanly.** Use `Key`, `Name`, `Description`, `Comment`, etc. — not `<Entity> None` (the default when no DESC form was explicitly named) or `<Attribute> None (1)`.
- **Post-build form-category PATCH is fragile on {MSTR_BASE host}.** `PATCH /api/model/dataModels/{mid}/attributes/{aid}` with `{forms:[...]}` returns `8004cc63 "Attribute does not contain a form with the ID"` even when GET returns that exact ID. Fix form names at **CREATE time**, not via post-hoc PATCH.
- **ID-form aliases are acceptable tech artifacts.** `alias: "C_CUSTKEY"` on the ID form is fine; the user never sees it. The user-facing `name` and `category` are what matter.

## Metric naming and aggregation

- **Name = business concept.** `Order Total Price`, `Line Extended Price`, `Avg Discount Rate` — not `Sum O Totalprice` or `L Discount Sum`.
- **Put the aggregation in the name only when it disambiguates.** Use `Avg Discount Rate` (distinguishes from a hypothetical `Total Discount`), but not `Sum Line Quantity` (the default is obvious).
- **Aggregation function must match business semantics:**
  - `SUM` for additive measures — monetary totals, counts, quantities (`EXTENDEDPRICE`, `TOTALPRICE`, `QUANTITY`, `AVAILQTY`, `ACCTBAL`, `RETAILPRICE` when aggregating catalog value, `SUPPLYCOST` when totaling supplier spend).
  - `AVG` for rates / percentages / per-unit values (`DISCOUNT`, `TAX`, rates, per-unit prices when per-line averages are the business ask).
  - `COUNT` / `COUNT_DISTINCT` for entity counts.
  - `MIN`/`MAX` for bounds.
  - Default is `SUM`; override explicitly via dictionary `metrics.{TABLE.COLUMN}.function`.
- **Reserve AVG-style renames for true rate metrics.** If `Discount` is renamed to `Avg Discount Rate` so it reads honestly, do the same for `Tax` → `Avg Tax Rate`. Don't leave one renamed and the other not.

## Metric formatting

Apply post-build format tokens to each metric:

- **Currency** (monetary fields): `format.values = [{type:"number_category",value:"1"},{type:"number_format",value:"#,##0.00"},{type:"symbol_position",value:"prefix"},{type:"symbol",value:"$"}]` — or locale-appropriate symbol.
- **Percent** (rate metrics, 0-1 scale): `{type:"number_category",value:"2"},{type:"number_format",value:"0.00%"}`.
- **Integer** (counts, quantities): `{type:"number_category",value:"3"},{type:"number_format",value:"#,##0"}`.
- **Decimal** (everything else): explicit 2-decimal format so the default doesn't render with 6+ trailing zeros.

Keep `CURRENCY_METRICS` / `PERCENT_METRICS` / `INTEGER_METRICS` sets in the build script so formatting isn't a guessing game.

## Descriptions

- **Business-first, not schema-first.** "Customer account balance used for credit, billing, and AR analysis" — not "Sum of C_ACCTBAL from CUSTOMER".
- **One sentence, end with a period.** Two sentences only when enumerated codes need explanation (e.g., `Order Status`: "Current order status (O = open, F = finalized, P = partial).").
- **Include domain hints when the column is cryptic.** `C_MKTSEGMENT` description should enumerate valid values; `O_ORDERPRIORITY` should enumerate priority tiers; `L_RETURNFLAG` should decode `R/N/A`.
- **Every attribute and every metric gets a description.** If the dictionary has a column, the description is written; if auto-detection added an attribute we didn't predict, it still needs one. Run a post-build audit — no `description: ""` or `description: null` is acceptable.
- **Run the description pass AFTER renames.** If you rename `Order Key` → `Order`, but the description map is keyed on `Order Key`, the description gets skipped. Either re-key the map post-rename, or run descriptions before renames and include both old+new names in the lookup.

## Cleanliness rules

- **Never hardcode example user identities.** No real personal names, tenant-internal usernames, placeholder-user fixtures, or example emails in any build script, memory file, or security-filter helper. Security filters are opt-in and parameterized: `add_security_filter(model_id, member_user_ids=[...])`. Example names drift, get copy-pasted into production, and are awkward for anyone else running the script.
- **Never hardcode credentials.** `MSTR_PASSWORD` env var only; do not commit passwords even to a script in `~/Desktop` — treat that as potentially sharable/visible.
- **Don't ship with raw column-name attribute names.** `R Regionkey`, `N Name`, `O Orderdate` — these are intermediate build artifacts. Either the dictionary renames them, or the build-skill's title-casing renames them (e.g., `Order Date`), or they don't ship.
- **Verify against a live query.** End-to-end means: attribute joins return expected cardinality, metric aggregates match a known-good reference, hierarchy drill works in Library UI (or at least in Trino).

## Consumer-grade checklist (run before reporting a build complete)

1. Every attribute has a business-name (not a technical column name).
2. Every form has a non-empty `name`; DESC forms read as `Name`, `Description`, `Comment`, etc.
3. Every attribute and metric has a business-friendly description.
4. Metric aggregation functions match the business intent (SUM/AVG/etc.); verify on at least 3 ambiguous measures.
5. Every metric has a number-format token list matching its category (currency/percent/integer/decimal).
6. Relationships connect the right hierarchy — spot-check with a query that joins 2+ dim levels and a fact.
7. No hardcoded example users or personal names anywhere in the build script or filter definitions.
8. At least one validation query returns aggregates matching a known-good reference (see `skill/mosaic-validation/` for the standard Mosaic-to-Mosaic validation recipe).
