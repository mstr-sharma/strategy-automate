# SemiTestCo semiconductor test-analysis extension tables (2026-08-10)

Two deep-technical PostgreSQL tables in Neon that extend the Studio Mosaic model
**"SD Manufacturing SemiTestCo Production Quality and Maintenance Model"**
(`3F80CD71D1C446E594F200B534F7FCD2`, Shared Studio > My Reports > SemiTestCo) for a
SemiTestCo test & measurement demo (incumbent-tool displacement).

## What the existing model has

`dataServeMode: in_memory`, 4 tables, 17 attributes, 5 metrics.

| Table | Grain | Notable columns |
|---|---|---|
| `..._CUSTOMERS` | customer | `CUSTOMER_ID`, `CUSTOMER_NAME`, `SEGMENT`, `COUNTRY`, `REGION`, `STATE` |
| `..._PRODUCTS` | product | `PRODUCT_ID`, `PRODUCT_NAME`, `CATEGORY`, `SUBCATEGORY`, `LIST_PRICE` |
| `..._LOT_DISPOSITIONS` | **lot** | `DISPOSITION_ID`, `CUSTOMER_ID`, `PRODUCT_ID`, `TEST_DATE`, `LOT_SIZE`, `YIELD_PERCENTAGE`, `DISPOSITION_STATUS`, `TEST_STAGE` |
| `..._TESTER_MAINTENANCE` | maintenance event | `MAINTENANCE_ID`, `CUSTOMER_ID`, `PRODUCT_ID`, `MAINTENANCE_DATE`, `DOWNTIME_HOURS`, `MAINTENANCE_TYPE`, `MAINTENANCE_COST` |

Scale: 3,500 lots / 5,307,134 units / 120 customers / 75 products / 2025-01-01 → 2026-08-10.

**The analytical gap:** the deepest fact is one `YIELD_PERCENTAGE` number per lot. There
is no equipment, no test program, no bin, no parametric distribution — i.e. none of the
data an incumbent-tool user actually works in.

## What was added (Neon PostgreSQL, `neondb.public`)

Grain ladder — each level rolls up **exactly** to the one above:

```
LOT_DISPOSITIONS (lot, Studio in-memory)          3,500 rows
  └─ SEMITEST_WAFER_TEST_RUNS (wafer/sublot × insertion)   25,818 rows
       └─ SEMITEST_PARAMETRIC_TEST_RESULTS (run × test)   196,456 rows
```

| Table | Grain | Covers |
|---|---|---|
| `SEMITEST_WAFER_TEST_RUNS` | lot × wafer/sublot × insertion | tester / prober / probe-card / load-board identity, test program + version, insertion type, temperature, multi-site parallelism, FPY vs final yield, hard/soft bin pareto head, yield-loss category, edge-vs-center wafer yield, PAT outliers, touchdowns, throughput (UPH), tester utilization, calibration age |
| `SEMITEST_PARAMETRIC_TEST_RESULTS` | test run × test number | per-test spec limits (LSL/USL/target), measured mean/median/sigma/min/max/P01/P99, **Cp / Cpk / Ppk** vs baseline, guardband margin, distance-to-limit in sigma, drift vs baseline, fail events vs first-fail units, PAT outliers, yield-limiting flag + pareto rank, site-to-site correlation, test time |

Full column list and additivity notes: [`ddl.sql`](ddl.sql).

### Join / conformance design

Both tables carry the **full conformed key set** — `DISPOSITION_ID`, `CUSTOMER_ID`,
`PRODUCT_ID`, `TEST_DATE`, `TEST_STAGE` — so either can be aggregated standalone at any
grain (customer, segment, region, product, category, date, stage) without traversing the
other, and both join straight back to the Studio dimensions. `SEMITEST_PARAMETRIC_TEST_RESULTS`
also carries `TEST_RUN_ID` and `WAFER_ID` for the drill path, and `TESTER_ID` so equipment
analysis works without a join.

Identifiers are **quoted UPPERCASE** to byte-match the column names already in the Studio
model, so Mosaic auto-merges the attributes rather than needing a `merge-attributes` pass.

### Additivity contract (read before defining metrics)

- **Additive:** all `UNITS_*`, `TOTAL_TEST_TIME_SEC`, `PROBE_TOUCHDOWNS`, `PAT_OUTLIER*`,
  `CONTACT_RESISTANCE_FAILS`, `FAIL_EVENTS`, `FIRST_FAIL_UNITS`.
- **Semi-additive:** `UNITS_MEASURED` on the parametric table is identical on every test row
  of a run. Additive *across runs*, **not across tests** — aggregate with `MAX` at run level.
- **Non-additive ratios:** every `*_PCT`, `CP`, `CPK`, `PPK`, `AVG_TEST_TIME_SEC`,
  `UNITS_PER_HOUR`. Define as `SUM(numerator)/SUM(denominator)`, never `AVG`.
  e.g. final yield = `SUM(UNITS_PASSED)/SUM(UNITS_TESTED)`.
- `FAIL_EVENTS` counts units failing a given test and **overlaps across tests** (one unit can
  fail several). `FIRST_FAIL_UNITS` is the disjoint attribution and is what reconciles.

## Reconciliation contract (all verified)

| # | Rule | Result |
|---|---|---|
| C1 | `SUM(runs.UNITS_TESTED)` per lot = `LOT_DISPOSITIONS.LOT_SIZE` | 0 mismatches / 3,500 lots |
| C2 | `SUM(runs.UNITS_PASSED)` per lot = `ROUND(LOT_SIZE × YIELD_PERCENTAGE/100)` | 0 mismatches |
| C3 | `SUM(params.FIRST_FAIL_UNITS)` per run = `runs.UNITS_FAILED_FIRST_PASS` | 0 mismatches / 25,818 runs |
| C4 | `params.UNITS_MEASURED` = `runs.UNITS_TESTED` | 0 mismatches / 196,456 rows |

Cross-store totals verified live against the Mosaic model:

| Test stage | Mosaic lots / units | Neon lots / units |
|---|---|---|
| Final Test | 1,198 / 1,780,662 | 1,198 / 1,780,662 |
| System Level Test | 363 / 571,685 | 363 / 571,685 |
| Wafer Sort | 1,939 / 2,954,787 | 1,939 / 2,954,787 |
| **Total** | **3,500 / 5,307,134** | **3,500 / 5,307,134** |

Product-level spot check (PROD-100/101/102/115) matched to the unit.

## Planted demo signals

1. **Calibration age drives yield.** First-pass yield degrades monotonically with
   `DAYS_SINCE_LAST_CALIBRATION`: 97.0% (2-49d) → 95.9% → 94.7% → 93.3% (150-195d).
   This is the cross-store story — `TESTER_MAINTENANCE` lives in the Studio model,
   `DAYS_SINCE_LAST_CALIBRATION` in Neon, and they agree.
2. **Cpk explains yield loss.** Test capability is correlated with run yield, so the
   Cpk pareto genuinely identifies the yield-limiting test. Distribution:
   5.1% incapable (<1.00), 7.0% marginal, 17.5% capable, 70.4% robust.
3. **Bin pareto by stage.** Continuity dominates wafer sort; parametric/leakage lead at
   final test.

## Files

| File | Purpose |
|---|---|
| `ddl.sql` | table definitions, constraints, indexes, additivity comments |
| `generate.py` | deterministic generator (seeded per lot/run — re-running is byte-identical) |
| `validate.sql` | 10-check validation suite, all passing |
| `lots.csv` | lot spine extracted from the Studio cube (input to the generator) |
| `products.csv` | product → category/subcategory map (drives realistic test parameters) |

Generated CSVs are gitignored (62 MB + 8.4 MB). Regenerate with:

```bash
python generate.py
```

## Loading into a fresh database

```bash
export PGPASSWORD='<password>'
CONN="host=<host> port=5432 dbname=neondb user=neondb_owner sslmode=require"
psql "$CONN" -v ON_ERROR_STOP=1 -f ddl.sql
psql "$CONN" -c "\copy \"SEMITEST_WAFER_TEST_RUNS\" FROM 'semitest_wafer_test_runs.csv' WITH (FORMAT csv, HEADER true, NULL '')"
psql "$CONN" -c "\copy \"SEMITEST_PARAMETRIC_TEST_RESULTS\" FROM 'semitest_parametric_test_results.csv' WITH (FORMAT csv, HEADER true, NULL '')"
psql "$CONN" -v ON_ERROR_STOP=1 -f validate.sql
```

## Wiring into Mosaic

The Studio datasource **"Neon PostgreSQL"** (`1026BAC01A4AAA58A344BC83897F9F12`) already
points at this exact host and database — no new datasource needed.

The model is `in_memory`, so adding the Postgres tables to the **same model** is allowed.
(Multi-DB under `connect_live` is rejected with `8004d232` — see
`memory/feedback_mosaic_multi_db_connect_live.md`. Do not flip serve mode.)

After adding the two tables, wire relationships on the conformed keys:
`DISPOSITION_ID` → Disposition, `CUSTOMER_ID` → Customer, `PRODUCT_ID` → Product,
`TEST_DATE` → Test Date, `TEST_STAGE` → Test Stage, plus `TEST_RUN_ID` between the two new
tables. Then re-publish and re-run the rollup check
(`memory/reference_rollup_consistency_validation.md`).

> **Naming note (2026-09-04):** company, person, and tenant identifiers in this capture are stand-ins (`EReaderCo`, `PharmaCo`, `<operator>`, …) per `memory/feedback_generalize_durable_artifacts.md`. The gitignored local scripts/payloads in this folder and the live warehouse objects keep the original identifiers, so table, plan, and file names here will not match them verbatim.
