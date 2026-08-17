-- =====================================================================================
-- SemiTestCo Semiconductor Test Analysis -- deep-technical extension tables (PostgreSQL / Neon)
--
-- Extends the Studio Mosaic model
--   "SD Manufacturing SemiTestCo Production Quality and Maintenance Model" (3F80CD71D1C446E594F200B534F7FCD2)
-- which holds CUSTOMERS / PRODUCTS / LOT_DISPOSITIONS / TESTER_MAINTENANCE at LOT grain.
--
-- Grain ladder (each level rolls up EXACTLY to the one above):
--   LOT_DISPOSITIONS (lot)                       <- existing, Studio in-memory model
--     -> SEMITEST_WAFER_TEST_RUNS (wafer/sublot x insertion)
--          -> SEMITEST_PARAMETRIC_TEST_RESULTS (test run x test number)
--
-- Conformed keys carried on BOTH tables so either can be aggregated standalone at any
-- grain and joined cross-store without traversing the other:
--   DISPOSITION_ID, CUSTOMER_ID, PRODUCT_ID, TEST_DATE, TEST_STAGE
--
-- Identifiers are quoted UPPERCASE to byte-match the column names already in the Studio
-- model, so Mosaic auto-merges the attributes instead of needing a manual merge pass.
-- =====================================================================================

DROP TABLE IF EXISTS "SEMITEST_PARAMETRIC_TEST_RESULTS";
DROP TABLE IF EXISTS "SEMITEST_WAFER_TEST_RUNS";

-- -------------------------------------------------------------------------------------
-- 1. SEMITEST_WAFER_TEST_RUNS
--    Grain: one row per (lot disposition x wafer/sublot x test insertion).
--    Additive: UNITS_*, TOTAL_TEST_TIME_SEC, PROBE_TOUCHDOWNS, PAT_OUTLIERS_REMOVED,
--              CONTACT_RESISTANCE_FAILS.
--    Non-additive (ratio -- compute as SUM(num)/SUM(den) in Mosaic, never AVG):
--              FIRST_PASS_YIELD_PCT, FINAL_YIELD_PCT, TESTER_UTILIZATION_PCT,
--              EDGE_DIE_YIELD_PCT, CENTER_DIE_YIELD_PCT, AVG_TEST_TIME_SEC, UNITS_PER_HOUR.
-- -------------------------------------------------------------------------------------
CREATE TABLE "SEMITEST_WAFER_TEST_RUNS" (
    "TEST_RUN_ID"                 varchar(24)   NOT NULL,   -- PK, degenerate
    -- ---- conformed keys back to the Studio model ----
    "DISPOSITION_ID"              varchar(24)   NOT NULL,   -- FK -> LOT_DISPOSITIONS.DISPOSITION_ID
    "CUSTOMER_ID"                 varchar(24)   NOT NULL,   -- FK -> CUSTOMERS.CUSTOMER_ID
    "PRODUCT_ID"                  varchar(24)   NOT NULL,   -- FK -> PRODUCTS.PRODUCT_ID
    "TEST_DATE"                   date          NOT NULL,   -- conforms to LOT_DISPOSITIONS.TEST_DATE
    "TEST_STAGE"                  varchar(40)   NOT NULL,   -- conforms to LOT_DISPOSITIONS.TEST_STAGE
    -- ---- material / lot traceability ----
    "FAB_LOT_ID"                  varchar(24)   NOT NULL,
    "WAFER_ID"                    varchar(32)   NOT NULL,
    "WAFER_NUMBER"                integer       NOT NULL,
    "SUBSTRATE_TECHNOLOGY"        varchar(32)   NOT NULL,   -- e.g. 'CMOS 7nm', 'GaN', 'SiGe BiCMOS'
    -- ---- equipment (degenerate dimensions; promote to a tester dim later if needed) ----
    "FAB_SITE"                    varchar(48)   NOT NULL,
    "TEST_FLOOR"                  varchar(16)   NOT NULL,
    "TESTER_ID"                   varchar(24)   NOT NULL,
    "TESTER_MODEL"                varchar(48)   NOT NULL,
    "HANDLER_OR_PROBER_ID"        varchar(24)   NOT NULL,
    "PROBE_CARD_ID"               varchar(24),              -- wafer sort only
    "LOAD_BOARD_ID"               varchar(24),              -- package test only
    "LAST_CALIBRATION_DATE"       date          NOT NULL,
    "DAYS_SINCE_LAST_CALIBRATION" integer       NOT NULL,
    -- ---- test program / conditions ----
    "TEST_PROGRAM_NAME"           varchar(64)   NOT NULL,
    "TEST_PROGRAM_VERSION"        varchar(16)   NOT NULL,
    "INSERTION_TYPE"              varchar(24)   NOT NULL,   -- Probe 1 / Probe 2 / Final Test 1 / SLT ...
    "TEST_TEMPERATURE_C"          numeric(6,1)  NOT NULL,
    "SITE_COUNT"                  integer       NOT NULL,   -- multi-site parallelism (x1..x32)
    -- ---- volumes (additive; reconcile to LOT_DISPOSITIONS) ----
    "UNITS_TESTED"                integer       NOT NULL,   -- SUM per lot = LOT_SIZE
    "UNITS_PASSED"                integer       NOT NULL,   -- SUM per lot = ROUND(LOT_SIZE*YIELD_PERCENTAGE/100)
    "UNITS_FAILED"                integer       NOT NULL,   -- UNITS_TESTED - UNITS_PASSED
    "UNITS_FAILED_FIRST_PASS"     integer       NOT NULL,   -- SUM of child FIRST_FAIL_UNITS
    "UNITS_RETESTED"              integer       NOT NULL,
    "UNITS_RECOVERED_ON_RETEST"   integer       NOT NULL,
    -- ---- yield / loss attribution ----
    "FIRST_PASS_YIELD_PCT"        numeric(7,3)  NOT NULL,
    "FINAL_YIELD_PCT"             numeric(7,3)  NOT NULL,
    "TOP_FAIL_HARD_BIN"           integer,
    "TOP_FAIL_HARD_BIN_NAME"      varchar(40),
    "TOP_FAIL_SOFT_BIN"           integer,
    "TOP_FAIL_BIN_UNITS"          integer,
    "YIELD_LOSS_CATEGORY"         varchar(32)   NOT NULL,
    "EDGE_DIE_YIELD_PCT"          numeric(7,3),             -- wafer sort only
    "CENTER_DIE_YIELD_PCT"        numeric(7,3),             -- wafer sort only
    -- ---- throughput / equipment health ----
    "AVG_TEST_TIME_SEC"           numeric(10,3) NOT NULL,
    "TOTAL_TEST_TIME_SEC"         numeric(14,2) NOT NULL,
    "UNITS_PER_HOUR"              numeric(10,2) NOT NULL,
    "TESTER_UTILIZATION_PCT"      numeric(6,2)  NOT NULL,
    "PROBE_TOUCHDOWNS"            integer,
    "CONTACT_RESISTANCE_FAILS"    integer       NOT NULL,
    "PAT_OUTLIERS_REMOVED"        integer       NOT NULL,   -- Part Average Testing screen
    "SITE_TO_SITE_MAX_DELTA_PCT"  numeric(7,3)  NOT NULL,
    "DATA_SOURCE_SYSTEM"          varchar(32)   NOT NULL,
    CONSTRAINT "PK_SEMITEST_WAFER_TEST_RUNS" PRIMARY KEY ("TEST_RUN_ID"),
    CONSTRAINT "CK_WTR_UNITS"   CHECK ("UNITS_PASSED" + "UNITS_FAILED" = "UNITS_TESTED"),
    CONSTRAINT "CK_WTR_FP"      CHECK ("UNITS_FAILED_FIRST_PASS" >= "UNITS_FAILED"),
    CONSTRAINT "CK_WTR_RETEST"  CHECK ("UNITS_RECOVERED_ON_RETEST" <= "UNITS_RETESTED")
);

-- -------------------------------------------------------------------------------------
-- 2. SEMITEST_PARAMETRIC_TEST_RESULTS
--    Grain: one row per (test run x test number).
--    Additive:      FIRST_FAIL_UNITS (SUM per run = UNITS_FAILED_FIRST_PASS), FAIL_EVENTS,
--                   PAT_OUTLIER_COUNT.
--    SEMI-additive: UNITS_MEASURED -- identical on every test of a run. Additive ACROSS
--                   runs, NOT across tests. In Mosaic aggregate with MAX at test-run level.
--    Non-additive:  CP / CPK / PPK / MEASURED_* / *_PCT -- averages must be weighted.
-- -------------------------------------------------------------------------------------
CREATE TABLE "SEMITEST_PARAMETRIC_TEST_RESULTS" (
    "PARAM_RESULT_ID"             varchar(32)   NOT NULL,   -- PK
    "TEST_RUN_ID"                 varchar(24)   NOT NULL,   -- FK -> SEMITEST_WAFER_TEST_RUNS
    -- ---- conformed keys (denormalized so this table aggregates standalone) ----
    "DISPOSITION_ID"              varchar(24)   NOT NULL,
    "CUSTOMER_ID"                 varchar(24)   NOT NULL,
    "PRODUCT_ID"                  varchar(24)   NOT NULL,
    "TEST_DATE"                   date          NOT NULL,
    "TEST_STAGE"                  varchar(40)   NOT NULL,
    "WAFER_ID"                    varchar(32)   NOT NULL,
    "TESTER_ID"                   varchar(24)   NOT NULL,
    -- ---- test identity ----
    "TEST_NUMBER"                 integer       NOT NULL,
    "TEST_NAME"                   varchar(64)   NOT NULL,
    "TEST_SUITE"                  varchar(40)   NOT NULL,
    "TEST_TYPE"                   varchar(32)   NOT NULL,   -- DC Parametric / AC Timing / RF / Leakage / ...
    "PARAMETER_UNIT"              varchar(12)   NOT NULL,
    -- ---- spec limits ----
    "LOW_SPEC_LIMIT"              numeric(18,6) NOT NULL,
    "HIGH_SPEC_LIMIT"             numeric(18,6) NOT NULL,
    "TARGET_VALUE"                numeric(18,6) NOT NULL,
    -- ---- measured distribution ----
    "MEASURED_MEAN"               numeric(18,6) NOT NULL,
    "MEASURED_MEDIAN"             numeric(18,6) NOT NULL,
    "MEASURED_SIGMA"              numeric(18,6) NOT NULL,
    "MEASURED_MIN"                numeric(18,6) NOT NULL,
    "MEASURED_MAX"                numeric(18,6) NOT NULL,
    "MEASURED_P01"                numeric(18,6) NOT NULL,
    "MEASURED_P99"                numeric(18,6) NOT NULL,
    -- ---- process capability ----
    "CP"                          numeric(9,4)  NOT NULL,
    "CPK"                         numeric(9,4)  NOT NULL,
    "PPK"                         numeric(9,4)  NOT NULL,
    "BASELINE_CPK"                numeric(9,4)  NOT NULL,
    "GUARDBAND_MARGIN_PCT"        numeric(8,3)  NOT NULL,
    "DISTANCE_TO_LIMIT_SIGMA"     numeric(9,4)  NOT NULL,
    "DRIFT_VS_BASELINE_PCT"       numeric(8,3)  NOT NULL,
    -- ---- fallout ----
    "UNITS_MEASURED"              integer       NOT NULL,   -- SEMI-ADDITIVE (see header)
    "FAIL_EVENTS"                 integer       NOT NULL,   -- units failing this test (may overlap)
    "FIRST_FAIL_UNITS"            integer       NOT NULL,   -- units whose FIRST fail was this test
    "TEST_FAIL_RATE_PCT"          numeric(8,4)  NOT NULL,
    "PAT_OUTLIER_COUNT"           integer       NOT NULL,
    "IS_YIELD_LIMITING_TEST"      boolean       NOT NULL,
    "FAIL_PARETO_RANK"            integer       NOT NULL,
    "HARD_BIN"                    integer       NOT NULL,
    "SOFT_BIN"                    integer       NOT NULL,
    -- ---- multi-site correlation ----
    "SITE_MIN_MEAN"               numeric(18,6) NOT NULL,
    "SITE_MAX_MEAN"               numeric(18,6) NOT NULL,
    "SITE_TO_SITE_DELTA_PCT"      numeric(8,3)  NOT NULL,
    "SITE_CORRELATION_FLAG"       varchar(16)   NOT NULL,   -- OK / Marginal / Fail
    "TEST_TIME_MS"                numeric(10,3) NOT NULL,
    CONSTRAINT "PK_SEMITEST_PARAMETRIC_TEST_RESULTS" PRIMARY KEY ("PARAM_RESULT_ID"),
    CONSTRAINT "FK_PTR_RUN" FOREIGN KEY ("TEST_RUN_ID") REFERENCES "SEMITEST_WAFER_TEST_RUNS" ("TEST_RUN_ID"),
    CONSTRAINT "CK_PTR_FAIL" CHECK ("FAIL_EVENTS" >= "FIRST_FAIL_UNITS")
);

-- -------------------------------------------------------------------------------------
-- Indexes for the cross-store join / drill paths
-- -------------------------------------------------------------------------------------
CREATE INDEX "IX_WTR_DISPOSITION" ON "SEMITEST_WAFER_TEST_RUNS" ("DISPOSITION_ID");
CREATE INDEX "IX_WTR_CUST_PROD"   ON "SEMITEST_WAFER_TEST_RUNS" ("CUSTOMER_ID", "PRODUCT_ID");
CREATE INDEX "IX_WTR_DATE"        ON "SEMITEST_WAFER_TEST_RUNS" ("TEST_DATE");
CREATE INDEX "IX_WTR_TESTER"      ON "SEMITEST_WAFER_TEST_RUNS" ("TESTER_ID");

CREATE INDEX "IX_PTR_RUN"         ON "SEMITEST_PARAMETRIC_TEST_RESULTS" ("TEST_RUN_ID");
CREATE INDEX "IX_PTR_DISPOSITION" ON "SEMITEST_PARAMETRIC_TEST_RESULTS" ("DISPOSITION_ID");
CREATE INDEX "IX_PTR_CUST_PROD"   ON "SEMITEST_PARAMETRIC_TEST_RESULTS" ("CUSTOMER_ID", "PRODUCT_ID");
CREATE INDEX "IX_PTR_DATE"        ON "SEMITEST_PARAMETRIC_TEST_RESULTS" ("TEST_DATE");
CREATE INDEX "IX_PTR_TEST"        ON "SEMITEST_PARAMETRIC_TEST_RESULTS" ("TEST_NAME");
