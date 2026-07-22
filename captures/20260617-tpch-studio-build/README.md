# TPC-H SF10 live-connect Mosaic build — studio.strategy.com (2026-06-17)

Built a Snowflake TPC-H SF10 live-connect Mosaic model in the **Shared Studio** project,
saved to **Shared Reports > Collaboration > Arpan Sharma**, then queried it for
supplier and order insights. ERD-driven (TPC-H standard schema).

## Tenant IDs (studio.strategy.com)
- Project **Shared Studio**: `1FC5A43B374C963CC773C285DF86E2F6`
- DB instance **Snowflake Sample Data**: `245EBDFD85458E568C76FCB353406E93` (schema `TPCH_SF10`)
- Dest folder **Public Objects > Reports > Collaboration > Arpan Sharma**: `DC377018BD4CACD81B7E4CAEB8DB62B4`
- **Model**: `7413CB35B8834574B0FEDD7212AFA588`
  - URL: https://studio.strategy.com/MicroStrategyLibrary/app/library#/model/7413CB35B8834574B0FEDD7212AFA588
- Trino: host `studio.strategy.com`, catalog `sql`, schema `shared studio`, model table = `"TPC-H SF10 (Snowflake Sample Data)"`

## Build recipe (TPC-H prefixed keys defeat auto-conformance)
TPC-H columns are table-prefixed (`R_REGIONKEY` ≠ `N_REGIONKEY`), so the build helper's
entity/shared-column detection finds nothing. Canonical recipe used:
1. `build --data-serve-mode connect_live --skip-relationships` + `dictionary.json`
   (business names/descriptions/agg functions), `--attr-cols P_SIZE O_SHIPPRIORITY`
   (decimal categoricals), `--skip-cols` the 7 noise `*_COMMENT` columns (kept PS_COMMENT
   as the PARTSUPP bridge grain). → 8 tables, 44 attrs, 10 metrics.
2. `merge-attributes --hints merge-hints.json` → conformed 9 FK columns into 6 key
   dimensions (Region, Nation, Supplier, Part, Customer, Order). 9/9, 9 children deleted → 35 attrs.
3. `wire-relationships --hints wire-hints.json` → 9 entity joins (single-key; the composite
   PARTSUPP→LINEITEM join is deliberately NOT wired to avoid the R4 Cartesian — Supplier→LINEITEM
   and Part→LINEITEM are wired directly instead).
4. `wire-relationships --hints desc-hints.json` → 27 descriptor→entity relationships (clears orphans).
5. `polish.py` → model description + metric number formats (currency/percent/integer).
6. `validate-model` → PASS (7 by-design WARNs: date-hierarchy gap, REGION heuristic FP, acctbal-SUM choice).

Relationships: 36 logical (72 directional entries).

## Data validation (rollup consistency — PASS)
Same measure totals identically across independent dimension paths ⇒ joins correct, no fan-out:
- Gross extended price = **$2,293.8B** across {supplier region, return flag, nation}.
- Order value = **$2,266B** across {status, priority, segment, year, customer region}.
- Cardinalities match TPC-H SF10: 100K suppliers, 1.5M customers, 15M orders, ~60M line items.

## Supplier insights
- **Top suppliers by gross revenue** ~ $34.2–34.7M each (Supplier#000042989 = $34.7M, MOROCCO). Flat head — uniform TPC-H data.
- **Supply base by region** (~20K suppliers each): AMERICA $461.3B, EUROPE $459.5B, ASIA $459.1B, MIDDLE EAST $458.7B, AFRICA $455.3B.
- **Credit exposure (Σ account balance)**: MIDDLE EAST $91.4M (avg $4,561) → AFRICA $89.1M (avg $4,492). Total $451.8M.
- **Sourcing**: avg supply cost ~$500 and ~8.0B units available in every region (uniform).

## Order insights
- **By status**: F(finalized) 7.31M / $1,098B · O(open) 7.31M / $1,097B · P(partial) 0.38M / $71B.
- **By priority / segment**: flat ~$453B each; avg order value ~$151K; BUILDING segment marginally highest.
- **By year**: 1992–1997 steady ~2.28M orders / ~$344B; **1998 partial** (1.33M / $201.5B — data ends mid-1998).
- **By customer region**: EUROPE leads ($454.4B, 301K customers) → AMERICA ($452.1B).
- **Returns**: ~33% of line-item value flagged returned (R $566B + A $566B vs N $1,161B); avg discount 5%.

## Notes / limitations
- **Mosaic MCP not connected this session** → used the documented `query` REST fallback (direct Trino HTTPS, `_trino_query` in `strategy_validate_models.py`). Functionally identical to the MCP `query` tool.
- **Nation/Region are conformed** across Supplier & Customer; a fact grouped by geography resolves to ONE path. Geography queries pin the role via a supplier-count (supplier geo) or customer-count (customer geo).
- **No net-revenue metric** (SUM(ext×(1−disc))) — needs a row-level fact-expression metric; gross extended price used as the revenue measure.
- **No date hierarchies** (build gap) — time analysis via Trino `year()`.

Files: dictionary.json, merge-hints.json, wire-hints.json, desc-hints.json, tq.py (Trino runner), polish.py, build-summary.json.
