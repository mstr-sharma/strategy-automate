# Model review — "SemiTestCo Production Quality and Maintenance Model" (2026-08-10)

Model `3F80CD71D1C446E594F200B534F7FCD2`, Shared Studio > My Reports > SemiTestCo.
6 tables / 53 attributes / 56 fact metrics, `dataServeMode: in_memory`.

Reviewed after the two Neon Postgres tables (`SEMITEST_WAFER_TEST_RUNS`,
`SEMITEST_PARAMETRIC_TEST_RESULTS`) were added to the model.

---

## 1. Relationships

### What auto-conformance got right

The shared keys merged cleanly across all six tables — this is the part that makes
cross-store analysis work, and it is correct:

| Attribute | Tables its ID form spans |
|---|---|
| Product | LOT_DISPOSITIONS, PRODUCTS, TESTER_MAINTENANCE, PARAMETRIC, WAFER_RUNS |
| Disposition | LOT_DISPOSITIONS, PARAMETRIC, WAFER_RUNS |
| Test Date | LOT_DISPOSITIONS, PARAMETRIC, WAFER_RUNS |
| Test Stage | LOT_DISPOSITIONS, PARAMETRIC, WAFER_RUNS |
| Test Run / Wafer / Tester | PARAMETRIC, WAFER_RUNS |

The drill hierarchies inside the new tables were also built correctly:
`Test Suite → Test Name → Test Number → Parametric Result`,
`Product Category → Subcategory → Product Name → Product`, and the equipment
attributes (Fab Site, Test Floor, Tester Model, Probe Card, …) all hang off Test Run.

### Defect 1 — Customer was severed from the lot and maintenance facts (FIXED)

The `Customer` attribute's ID form covered only CUSTOMERS, PARAMETRIC and WAFER_RUNS.
It was **missing `LOT_DISPOSITIONS.CUSTOMER_ID` and `TESTER_MAINTENANCE.CUSTOMER_ID`** —
both columns exist in the warehouse and were mapped in the original model. `Product`
correctly spanned all five tables, which is what made the omission easy to miss.

Effect: customer-level analysis of lot yield and of maintenance had no direct join path.
Lot queries silently resolved through the new WAFER_RUNS bridge (right answer, wrong
reason, and it would have broken for any lot with no test runs); maintenance did not
resolve at all.

**Fix applied:** PATCHed the ID form to five expressions, one per (table, column) pair.

### Defect 2 — geography and segment were orphaned from Customer (FIXED)

Relationship edges existed for `Country → Region → State`, but **`State → Customer` was
absent and `Customer Segment` had no edge at all**. The CUSTOMERS descriptive attributes
therefore could not route to any fact.

Symptom, before the fix — three of four segments reported the *grand total* downtime:

```
customer segment | downtime   <- 6,910.2 is the model-wide total
Fabless          |  4,248.8
OSAT             |  6,910.2
Tier 1 IDM       |  6,910.2
Tier 2 IDM       |  6,910.2
```

Verified the hierarchy is clean before wiring (no state spans two regions/countries).

**Fix applied:** wired `State → Customer` and `Customer Segment → Customer`.

### Defect 3 — nine missing dimension→fact edges (FIXED)

Auto-detection wired the new tables to each other but not back to several conformed
dimensions. All nine were confirmed missing by `wire-relationships --dry-run`:

```
Customer    → Disposition, Maintenance, Parametric Result
Product     → Test Run
Test Date   → Test Run, Parametric Result
Test Stage  → Test Run, Parametric Result
Tester      → Parametric Result
```

**Fix applied** via merge-aware PUT (never `--replace`, which wipes incoming edges).

### Open item — "Maintenance Date" is no longer its own attribute

In the pre-extension model `Maintenance Date` was a standalone attribute. It is now a
**form of the `Maintenance` attribute**, so maintenance activity cannot be grouped or
trended by date on its own. `Test Date` and `Last Calibration Date` both kept full
Day/Week/Month/Quarter/Year hierarchies; maintenance did not.

This matters for the demo's calibration story — "maintenance spend by month" is not
currently expressible. Recommend promoting it back to a standalone attribute with its
own date hierarchy. Not changed here because it alters the shape the user built.

---

## 2. Metric aggregation and formatting

**All 56 metrics were auto-generated as `function: sum`**, and the number formats used
the wrong `number_category` codes throughout (percentages landed on `4` = *Time*,
currency on `1` = *Number*; canonical enum is 0=General, 1=Number, 2=Currency, 3=Date,
4=Time, 5=Percentage, 6=Fraction, 7=Scientific, 9=Accounting).

Summing a percentage or a Cpk is not a rounding problem — it produces numbers that are
wrong by orders of magnitude the moment anything is grouped.

### Corrections applied (all 56, one changeset)

| Class | Metrics | Was | Now |
|---|---|---|---|
| Additive counts / volumes | Lot Size, Units Tested/Passed/Failed/Failed First Pass/Retested/Recovered, Fail Events, First Fail Units, Top Fail Bin Units, Probe Touchdowns, Contact Resistance Fails, PAT Outliers Removed, Pattern Outlier Count | sum ✓ | sum, `#,##0` (cat 1) |
| Currency | Maintenance Cost | sum, cat 1 | sum, `$#,##0.00;($#,##0.00)` (cat 2) |
| Price (never a sum) | List Price | sum | **avg**, currency |
| Percentages (stored 0-100) | Yield %, First Pass Yield %, Final Yield %, Edge/Center Die Yield %, Test Fail Rate %, Tester Utilization %, Guardband Margin %, Drift vs Baseline %, Site-to-Site Delta % | **sum**, cat 4 | **avg**, `#,##0.0"%"` (cat 1) |
| Site-to-site max | Site To Site Maximum Delta % | sum | **max** |
| Process capability | Cp, Cpk, Ppk, Baseline Cpk, Distance To Limit Sigma | **sum** | **avg**, `#,##0.000` |
| Measured distribution | Target Value, Measured Mean/Median/Sigma/P01/P99 | **sum** | **avg**, scientific `0.000E+00` (cat 7) |
| Extremes | Measured Minimum, Site Minimum Mean, Low Spec Limit | **sum** | **min**, scientific |
| Extremes | Measured Maximum, Site Maximum Mean, High Spec Limit | **sum** | **max**, scientific |
| Rank | Fail Pareto Rank | **sum** | **min** (best rank wins) |
| Bin identifiers | Top Fail Hard Bin, Top Fail Soft Bin | **sum** | **max** — see caveat |
| Run conditions | Days Since Last Calibration, Test Temperature (°C), Site Count, Units Per Hour, Average Test Time Seconds | **sum** | **avg** |
| Durations | Total Test Time Seconds, Test Time Milliseconds | sum ✓ | sum, fixed decimal |
| Semi-additive | Units Measured | **sum** | **max** — see caveat |

Two format decisions worth knowing:

- **Percentages use category 1 with a literal `"%"` suffix, not category 5.** The source
  columns store 0-100, and true percent formatting multiplies by 100 — category 5 would
  have rendered 94.44 as `9444%`.
- **Parametric measurements use scientific notation.** Those columns span 1e-12 (jitter,
  seconds) to 1e10 (high-Z impedance, ohms); the auto-assigned `#,##0.000000` rendered
  most of them as `0.000000`.

### Caveats that aggregation cannot fix

- **`Units Measured` is semi-additive** — it is identical on every test row of a run, so
  no single function is right at every grain. `max` is correct at test-run grain and
  conservative above it. **Use `Units Tested` instead** (fully additive, same value at
  run grain). Consider removing `Units Measured` from the model.
- **`Top Fail Hard Bin`, `Top Fail Soft Bin`, `Fail Pareto Rank` are dimensional values,
  not measures.** `max`/`min` keeps them from summing into nonsense, but they belong as
  attributes. `Top Fail Hard Bin Name`, `Hard Bin` and `Soft Bin` already exist as
  attributes and should be preferred.
- **Averaged percentages are unweighted.** `avg` of Final Yield % across runs weights a
  500-unit wafer the same as a 5,000-unit wafer. For anything that matters, use the
  ratio `SUM(Units Passed) / SUM(Units Tested)`, which is correct at every grain.
  Recommend adding these as compound metrics (see `reference_mosaic_derived_metrics.md`
  for the tree payload shape).
- **`Pattern Outlier Count` is misnamed** — PAT is *Part Average Testing*, not "Pattern".
  Auto friendly-naming expanded the abbreviation wrongly. Rename to `PAT Outlier Count`
  to match its sibling `PAT Outliers Removed`.

---

## 3. Data validation

Ground truth = the 3,500-row lot spine extracted from the model before the extension,
plus direct Postgres aggregates.

| Grain | Check | Result |
|---|---|---|
| Grand total | `SUM(Lot Size)` | 5,307,134 ✓ |
| Test stage | lots + units, 3 stages | exact ✓ |
| Product | units for 4 sampled products | exact to the unit ✓ |
| Customer | top-6 lot units vs ground truth | exact ✓ |
| Product category | `Lot Size` vs `Units Tested` | identical across all 3 ✓ |
| Product category | `First Fail Units` vs `Units Failed First Pass` | identical across all 3 ✓ |
| Maintenance type × product category | downtime additivity | sums to 6,910.2 ✓ |
| Customer segment / region × downtime | additivity | **FAILED → fixed** (Defect 2) |

### Re-validation after the fixes + republish

The relationship fixes only took effect in query results **after the cube was
republished** — `in_memory` models serve from the published cube, so schema edits are
invisible until then. Budget a republish into any schema change.

| Grain | Check | Result |
|---|---|---|
| Customer segment | downtime additivity | 65.4 + 1,716.2 + 3,155.8 + 1,972.8 = **6,910.2** ✓ |
| Region | downtime additivity | 1,056.6 + 891.4 + 2,514.3 + 2,447.9 = **6,910.2** ✓ |
| Region | `Lot Size` vs `Units Tested` | identical, all 4 ✓ |
| Region | `First Fail Units` vs `Units Failed First Pass` | identical, all 4 ✓ |
| Test stage × disposition status | `Lot Size` vs `Units Tested` | identical, all 11 ✓ |
| Test stage × disposition status | `Units Passed` | totals **5,083,779**, matches Postgres ✓ |
| Month (test date hierarchy) | lot vs run units, ff vs uffp | identical, every month ✓ |
| Test type | `First Fail Units` | totals **251,479**, matches region grain ✓ |
| Test stage | weighted vs averaged yield | 95.61/96.09/95.84 vs 95.68/96.08/95.79 — within 0.07pp ✓ |
| Customer segment | all 4 metrics, post-fix | 5,307,134 / 5,083,779 / 251,479 / 6,910.2 — all exact ✓ |
| State | downtime + lot units | varies per state, no repeated totals ✓ |
| Country (single value = grand total) | every metric | 5,307,134 / 5,083,779 / 6,910.2 / 251,479 ✓ |
| Test suite × test name (deepest grain) | Cpk, fail events ≥ first-fail units | sane, ordering correct ✓ |

The cross-store rollup is the important one and it holds: `Lot Size` (Studio in-memory)
and `Units Tested` (Neon Postgres) agree exactly at grand total, stage, disposition
status, product category, customer, region and month grain, and the parametric fallout
ties to the wafer-run fallout at every level tested.

The weighted-vs-averaged yield gap (≤0.07pp here) is the measurable cost of `avg` on a
percentage. It is small on this data because wafer sizes are similar, but it is the
reason the ratio metrics below are worth adding.

---

## 4. Recommendations not applied

These change the shape of the model or the source tables, so they are left as decisions.

1. **Add weighted ratio metrics.** `SUM(Units Passed)/SUM(Units Tested)` and
   `(SUM(Units Tested) − SUM(Units Failed First Pass))/SUM(Units Tested)` are correct at
   every grain, unlike the `avg` versions. Payload shape in
   `memory/reference_mosaic_derived_metrics.md` (`/metrics` endpoint, expression tree,
   `dimty: null`).
2. **Promote `Maintenance Date` back to a standalone attribute** with a date hierarchy so
   maintenance spend/downtime can be trended by month.
3. **Rename `Pattern Outlier Count` → `PAT Outlier Count`** (Part Average Testing).
4. **Drop `Units Measured`** in favour of `Units Tested`, or leave it at `max` and keep it
   off report templates.
5. **Convert `Top Fail Hard Bin` / `Top Fail Soft Bin` / `Fail Pareto Rank` to attributes.**
6. **Add a calibration-age band** so the headline cross-store insight can be charted as a
   bar chart rather than only as a scatter. `Days Since Last Calibration` exists only as a
   metric, so it cannot be grouped on today:

   ```sql
   ALTER TABLE "SEMITEST_WAFER_TEST_RUNS" ADD COLUMN "CALIBRATION_AGE_BAND" varchar(16);
   UPDATE "SEMITEST_WAFER_TEST_RUNS" SET "CALIBRATION_AGE_BAND" =
     CASE WHEN "DAYS_SINCE_LAST_CALIBRATION" <  50 THEN 'a. 0-49 days'
          WHEN "DAYS_SINCE_LAST_CALIBRATION" < 100 THEN 'b. 50-99 days'
          WHEN "DAYS_SINCE_LAST_CALIBRATION" < 150 THEN 'c. 100-149 days'
          ELSE 'd. 150+ days' END;
   ```

   Re-import the column into the model and republish.

---

## 5. Query caveats for the demo

- **Do not cross maintenance attributes with test-run metrics.** `Maintenance Type ×
  Units Tested` returns the grand total on every row. That is expected multi-fact
  behaviour, not a bug — maintenance events and test runs are independent facts that share
  only Customer / Product / Date. Show maintenance metrics with maintenance or customer
  attributes; show the calibration story via `Days Since Last Calibration` on the wafer
  test runs, which is a run-level column.
- **`Units Measured` at `max`** deliberately no longer resembles a volume (it reports
  ~1,952 where `Units Tested` reports 243,595). That is the semi-additive guard working.
- Avoid bare `COUNT(*)` / un-grouped aggregates over the whole model — it materialises the
  full six-table join and trips the iServer job time limit.
