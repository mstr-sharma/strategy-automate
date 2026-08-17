-- Validation suite for the NI semiconductor test-analysis extension tables.
-- Every check must return zero offending rows (or the stated expected value).

\echo '== V1  row counts =='
SELECT (SELECT count(*) FROM "NI_WAFER_TEST_RUNS")           AS wafer_test_runs,
       (SELECT count(*) FROM "NI_PARAMETRIC_TEST_RESULTS")   AS parametric_results;

\echo '== V2  grand total units -- must equal LOT_DISPOSITIONS SUM(LOT_SIZE) = 5,307,134 =='
SELECT sum("UNITS_TESTED") AS units_tested, sum("UNITS_PASSED") AS units_passed
FROM "NI_WAFER_TEST_RUNS";

\echo '== V3  parametric FIRST_FAIL_UNITS must sum to the run UNITS_FAILED_FIRST_PASS (expect 0) =='
SELECT count(*) AS violations FROM (
  SELECT r."TEST_RUN_ID"
  FROM "NI_WAFER_TEST_RUNS" r
  JOIN "NI_PARAMETRIC_TEST_RESULTS" p ON p."TEST_RUN_ID" = r."TEST_RUN_ID"
  GROUP BY r."TEST_RUN_ID", r."UNITS_FAILED_FIRST_PASS"
  HAVING sum(p."FIRST_FAIL_UNITS") <> r."UNITS_FAILED_FIRST_PASS"
) t;

\echo '== V4  UNITS_MEASURED must equal the run UNITS_TESTED on every test row (expect 0) =='
SELECT count(*) AS violations
FROM "NI_PARAMETRIC_TEST_RESULTS" p
JOIN "NI_WAFER_TEST_RUNS" r ON r."TEST_RUN_ID" = p."TEST_RUN_ID"
WHERE p."UNITS_MEASURED" <> r."UNITS_TESTED";

\echo '== V5  conformed keys must agree between parent and child (expect 0) =='
SELECT count(*) AS violations
FROM "NI_PARAMETRIC_TEST_RESULTS" p
JOIN "NI_WAFER_TEST_RUNS" r ON r."TEST_RUN_ID" = p."TEST_RUN_ID"
WHERE (p."DISPOSITION_ID", p."CUSTOMER_ID", p."PRODUCT_ID", p."TEST_DATE", p."TEST_STAGE")
   IS DISTINCT FROM
      (r."DISPOSITION_ID", r."CUSTOMER_ID", r."PRODUCT_ID", r."TEST_DATE", r."TEST_STAGE");

\echo '== V6  no orphan test runs / results (expect 0,0) =='
SELECT (SELECT count(*) FROM "NI_PARAMETRIC_TEST_RESULTS" p
          WHERE NOT EXISTS (SELECT 1 FROM "NI_WAFER_TEST_RUNS" r WHERE r."TEST_RUN_ID"=p."TEST_RUN_ID")) AS orphan_results,
       (SELECT count(*) FROM "NI_WAFER_TEST_RUNS" WHERE "UNITS_TESTED" <= 0)                            AS empty_runs;

\echo '== V7  key domain coverage -- must match the Studio model (3500 lots / 120 cust / 75 prod / 3 stages) =='
SELECT count(DISTINCT "DISPOSITION_ID") AS lots, count(DISTINCT "CUSTOMER_ID") AS customers,
       count(DISTINCT "PRODUCT_ID")     AS products, count(DISTINCT "TEST_STAGE") AS stages,
       min("TEST_DATE") AS first_date, max("TEST_DATE") AS last_date
FROM "NI_WAFER_TEST_RUNS";

\echo '== V8  capability sanity -- CPK banding =='
SELECT CASE WHEN "CPK" < 1.00 THEN 'a. <1.00 (incapable)'
            WHEN "CPK" < 1.33 THEN 'b. 1.00-1.33 (marginal)'
            WHEN "CPK" < 1.67 THEN 'c. 1.33-1.67 (capable)'
            ELSE                   'd. >=1.67 (robust)' END AS cpk_band,
       count(*) AS tests, round(avg("CPK"),3) AS avg_cpk
FROM "NI_PARAMETRIC_TEST_RESULTS" GROUP BY 1 ORDER BY 1;

\echo '== V9  the planted signal: calibration age vs first-pass yield =='
SELECT width_bucket("DAYS_SINCE_LAST_CALIBRATION", 0, 200, 4) AS cal_age_bucket,
       min("DAYS_SINCE_LAST_CALIBRATION") || '-' || max("DAYS_SINCE_LAST_CALIBRATION") AS days_range,
       count(*) AS runs,
       round(100.0 * sum("UNITS_TESTED" - "UNITS_FAILED_FIRST_PASS") / sum("UNITS_TESTED"), 3) AS first_pass_yield_pct
FROM "NI_WAFER_TEST_RUNS" GROUP BY 1 ORDER BY 1;

\echo '== V10  yield-loss pareto by test stage =='
SELECT "TEST_STAGE", "YIELD_LOSS_CATEGORY", count(*) AS runs, sum("TOP_FAIL_BIN_UNITS") AS units
FROM "NI_WAFER_TEST_RUNS" GROUP BY 1,2 ORDER BY 1, 4 DESC NULLS LAST;
