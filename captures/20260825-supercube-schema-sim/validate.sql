-- Post-load checks for the SEMI_* simulation tables.
-- Run: psql -X -f validate.sql   (libpq env vars supply the connection)

\echo === row counts ===
SELECT 'SEMI_TEST_CATALOG' AS table_name, count(*) AS rows FROM "SEMI_TEST_CATALOG"
UNION ALL
SELECT 'SEMI_PARAMETRIC_MEASUREMENTS', count(*) FROM "SEMI_PARAMETRIC_MEASUREMENTS"
UNION ALL
SELECT 'SEMI_LIMIT_OVERRIDES', count(*) FROM "SEMI_LIMIT_OVERRIDES";

\echo === per-test distribution vs spec (computed Cp / Cpk / pass rate) ===
SELECT c."TEST_NUM" AS tnum, c."TEST_NAME" AS test, count(*) AS n,
       round(avg(m."FLOAT_VALUE"), 4) AS mean,
       round(stddev_samp(m."FLOAT_VALUE"), 4) AS sigma,
       round((c."USL" - c."LSL") / (6 * stddev_samp(m."FLOAT_VALUE")), 2) AS cp,
       round(least(c."USL" - avg(m."FLOAT_VALUE"),
                   avg(m."FLOAT_VALUE") - c."LSL") / (3 * stddev_samp(m."FLOAT_VALUE")), 2) AS cpk,
       round(100.0 * avg(m."IS_PASS"), 2) AS pass_pct
FROM "SEMI_PARAMETRIC_MEASUREMENTS" m
JOIN "SEMI_TEST_CATALOG" c USING ("TEST_NUM")
GROUP BY c."TEST_NUM", c."TEST_NAME", c."USL", c."LSL"
ORDER BY c."TEST_NUM";

\echo === planted signal 1: VDD_LEAKAGE_UA drift (monthly Cpk decay) ===
SELECT date_trunc('month', m."TEST_DATE")::date AS month, count(*) AS n,
       round(avg(m."FLOAT_VALUE"), 3) AS mean_ua,
       round((max(c."USL") - avg(m."FLOAT_VALUE")) / (3 * stddev_samp(m."FLOAT_VALUE")), 2) AS cpk_upper,
       round(100.0 * avg(m."IS_PASS"), 2) AS pass_pct
FROM "SEMI_PARAMETRIC_MEASUREMENTS" m
JOIN "SEMI_TEST_CATALOG" c USING ("TEST_NUM")
WHERE c."TEST_NAME" = 'VDD_LEAKAGE_UA'
GROUP BY 1 ORDER BY 1;

\echo === planted signal 2: VTH_N_MV site-to-site offset (site 3 high) ===
SELECT m."SITE_NUM" AS site, count(*) AS n,
       round(avg(m."FLOAT_VALUE"), 2) AS mean_mv,
       round(stddev_samp(m."FLOAT_VALUE"), 2) AS sigma
FROM "SEMI_PARAMETRIC_MEASUREMENTS" m
WHERE m."TEST_NAME" = 'VTH_N_MV'
GROUP BY 1 ORDER BY 1;

\echo === limit-override seeds (the Step-4 write-back rows) ===
SELECT * FROM "SEMI_LIMIT_OVERRIDES" ORDER BY "OVERRIDE_ID";
