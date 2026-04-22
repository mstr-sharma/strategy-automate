---
name: Mosaic build quality rules (generalized from TPC-H side-by-side)
description: Durable, build-agnostic rules for Mosaic model construction, learned by diffing a hand-built vs auto-built TPC-H model where the auto-built one silently lost 40+ relationships, 16 date-hierarchy attributes, and all form labels.
type: feedback
---
On 2026-04-20 two Mosaic models over the same Snowflake TPCH_SF1 schema diverged dramatically: the hand-built one had 52 attributes / 54 relationships / populated form names / a business description, the script-built one had 36 attributes / 10 relationships / every `forms[].name` empty / no description / one table (REGION) returning HTTP 500 on read-back even though the commit reported success. The rules below are what would have caught each defect *at build time*, independent of TPC-H.

Every rule: `Rule. **Why:** ... **How to apply:** ...`

## R1 — Every attribute form must have a non-empty human-readable `name` before the first POST.

**Why:** empty form names are the single worst Mosaic build defect. They silently disable Strategy's auto-hierarchy-relationship detector (so intra-table fan-outs like `Customer Address → Customer`, `Part Brand → Part`, `Order Status → Order Key` never get created), they render as blank column headers in Library, and post-hoc PATCH to fix them fails on this tenant with `8004cc63`. Observed on the script-built model: 44 of the expected 54 relationships missing plus blank report headers, all traceable to `forms[i].name == ""`.

**How to apply:** in any attribute create path, derive `forms[i].name` from the semantic column name (title-case, no underscores) before the POST; if a category is set but the name is not, copy the category into the name. Treat `forms[i].name == ""` as a hard build failure — fail the changeset, not the report. Verify post-commit by reading the attribute list and asserting every form name is non-empty.

## R2 — `enableAutoHierarchyRelationships: true` is a convenience, not a contract.

**Why:** auto-hierarchy only fires when form metadata is well-formed *and* the shape is unambiguous (single lookup table, clean ID/DESC split). It never infers multi-hop chains, composite-key FKs, or dim-to-fact joins where the fact table has ≥3 FK columns pointing at different dims. Both TPC-H models had the flag on and both were missing the LINEITEM FK triangle (ORDERS→LINEITEM, PART→LINEITEM, SUPPLIER→LINEITEM, PARTSUPP-composite→LINEITEM). The flag covered the same 4 trivial dim→dim rels (REGION→NATION, NATION→CUSTOMER, NATION→SUPPLIER, CUSTOMER→ORDERS) in both cases; everything beyond that needed to be declared.

**How to apply:** enumerate FK relationships from the ERD *before* the build. Treat the flag as free cleanup for same-table descriptive fan-outs, but always emit explicit `PUT /attributes/{childId}/relationships` for every table-to-table FK. After build, compare declared-rel count to expected-FK count — gap > 0 is a flag to review.

## R3 — Every FK column on a fact table needs its own declared dim → fact-grain relationship.

**Why:** a fact table like LINEITEM has multiple FK columns (`L_ORDERKEY`, `L_PARTKEY`, `L_SUPPKEY`) — each one is a separate join path. Declaring only one (e.g., `Supplier → Line Number via LINEITEM`) means queries joining Part to LineItem have no path, and Strategy will either fail or detour through a wrong bridge and multiply rows. MODEL1 declared the PART→PARTSUPP→SUPPLIER chain but not direct SUPPLIER→LINEITEM; MODEL2 had the opposite gap. Neither had ORDERS→LINEITEM.

**How to apply:** for every fact table, emit one relationship per FK column: `dim's primary attribute → fact's grain attribute via <fact table>`. The "grain attribute" is typically the fact's own ID or line-number attribute (create one if missing). Run a coverage query post-build: for each fact table, count distinct parent-dim objects across its relationships; it must equal the number of FK columns you declared.

## R4 — Composite-key FKs require a compound bridge attribute; never simulate with two single-key rels.

**Why:** PARTSUPP → LINEITEM joins on (PARTKEY, SUPPKEY) together. Two separate one-to-many rels on PARTKEY and SUPPKEY independently will over-count: every LINEITEM row gets matched to every PARTSUPP row sharing *either* key, producing a Cartesian burst. Same pattern applies to any bridge/junction table, inventory-snapshot tables, and calendar keys combined with entity keys.

**How to apply:** detect FKs with ≥2 columns during ERD ingest. For each, create ONE compound attribute on the parent table with `forms[]` containing an ID form whose expression concatenates the key columns (or with multiple `category:"ID"` forms, compound-key style). Declare the relationship from this compound attribute to the fact grain. Document the join columns in the attribute description so downstream users see the composite nature.

## R5 — Bridge tables need one bridge-grain attribute that is the child of both parent dims.

**Why:** for PART ↔ PARTSUPP ↔ SUPPLIER and similar M:N patterns, the canonical Mosaic shape is: one attribute living on the bridge table, related upward to each of the two parent dims, and the bridge table itself used as `relationshipTable` in both rels. The hand-built TPC-H model did this with "Part Supplier Comment" (a PARTSUPP-level attribute) as child of both Part and Supplier via PARTSUPP. Any simulation with direct PART↔SUPPLIER rels is wrong for row fidelity.

**How to apply:** when ingesting an ERD, flag tables whose PK is the union of two FKs to other tables as bridges. For each, create a bridge-grain attribute (name it after the bridge, e.g., "Part Supplier"), and emit two `relationships[]` entries with the bridge table as `relationshipTable`.

## R6 — Date columns should auto-expand to Day/Month/Quarter/Year derivatives by default.

**Why:** the hand-built TPC-H model had 16 derived date attributes (4 date columns × 4 grains); the script-built model had zero. Without derived-date attributes, users can't group by Year-of-Order-Date or drill Month → Day without writing derived expressions in every report. The model works for ad-hoc users but fails for business dashboards.

**How to apply:** in the build pipeline, for every column whose `dataType.type` is `date` or `timestamp`, generate 4 additional attributes (`<Col> Day`, `<Col> Month`, `<Col> Quarter`, `<Col> Year`) with the appropriate temporal functions, a fan-out relationship chain (Day → Month → Quarter → Year), and calendar-ordered sorts on Month/Quarter. Expose `--no-date-hierarchies` as an opt-out, never an opt-in.

## R7 — Default aggregation on fact metrics encodes semantics; pick per column family, not per column.

**Why:** summing a discount rate yields nonsense; summing a unit price inflates totals; not summing a quantity makes the metric useless. The hand-built model left `Line Discount Rate`, `Part Retail Price`, and `Supply Cost` as SUM (wrong semantics for the first two); the script-built model converted all three to AVG (better for rates/prices, worse if the user wants SUM(qty × price)). Neither was uniformly correct.

**How to apply:** classify each fact column by semantic family at ingest:
- **Additive** (quantities, counts, extended amounts, totals, balances rolled up): SUM — `EXTENDEDPRICE`, `QUANTITY`, `TOTALPRICE`, `AVAILQTY`, `ACCTBAL` when rolling up a portfolio.
- **Averageable rates / ratios / percentages**: AVG — `DISCOUNT`, `TAX`, any `_RATE`/`_PCT`/`_RATIO` column.
- **Point-in-time unit values** (unit_price, list_price, retail_price, supply_cost): AVG at dim grain, kept raw at transaction grain; emit a derived SUM(qty × price) compound metric for transaction totals.
- **Semi-additive balances**: LAST or AVG — `ACCTBAL` at a single time-point, inventory snapshots, etc.
Run a column-name classifier in the build and surface a per-metric table in the build log: `column → family → chosen function`. The user can override via config.

## R8 — Commit success does not mean all objects persisted; read-back every created object.

**Why:** the script-built model reported a successful commit, yet `GET /api/model/dataModels/{id}/tables/{tableId}` for REGION returned HTTP 500 — a partial write that's invisible without post-build verification. Other objects in the same model read fine; the regression is per-object, not per-commit.

**How to apply:** after every changeset commit, iterate each object created and GET it individually. Fail the build on any non-200. Log object counts (tables, attrs, factMetrics, filters, relationships) and compare to the expected set derived from the ERD. This catches partial-write regressions, orphaned IDs, and silent model-server errors.

## R9 — Orphan attributes on fact/bridge tables signal an unwired relationship.

**Why:** in the hand-built model, the "Line Number" attribute had `relationships: []` even though LINEITEM is the fact table and Line Number is its grain. No query plan can navigate from a dim to Line Number, so every LINEITEM-grain report will fail or over-aggregate. Same pattern recurs in any build where the fact grain attribute gets created but no dim is declared as parent.

**How to apply:** post-build, list every attribute where `attributeLookupTable.name` is a fact or bridge table and `relationships` is empty. Each must have at least one parent rel. Cross-check against the FK coverage report from R3.

## R10 — Populate the model description field; it is a first-class AI/Mosaic surface.

**Why:** the model description is consumed by the Mosaic AI agent (Auto), the MCP `get_mosaic_models` tool, the Workstation catalog, and any downstream governance report. Blank descriptions materially hurt discoverability and AI-grounded QA. The script-built model had an empty description; the hand-built one had a one-sentence business summary.

**How to apply:** in the build helper, generate a 1–2 sentence business summary from the table list and fact-metric names at build time (`"Analyzes <grains> across <facts>, with <dimensions> hierarchy"`). Require non-empty before commit. Extend to every attribute and metric — blank descriptions are never acceptable on a consumer-grade build.

## R11 — Side-by-side model diff is a 30-second QA pattern; use it on every regeneration.

**Why:** the whole TPC-H root-cause investigation took under 5 minutes once a side-by-side was running: counts (attrs, relationships, factMetrics) surface 80% of defects, then drilling into one attribute per model shows the form-name and metadata gap. This generalizes — any time a build is regenerated or a script is updated, diffing the new model against the prior one surfaces silent regressions.

**How to apply:** for every rebuild against an existing model, run `validate-model` on both IDs and diff the summary blocks (see `reference_mosaic_build_validation.md`). Treat any drop in attribute count, relationship count, or factMetric count as a regression unless explicitly intended.
