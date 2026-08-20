-- =====================================================================================
-- Post-load consistency suite for the DevOpsCo extension tables (run in Neon PG, psql).
-- Violation checks return 0 rows on a correct load; profile checks are for eyeballing.
-- =====================================================================================

-- 0. Row inventory
SELECT 'DEVOPS_TEAM_APP_MONTHLY_COSTS' AS t, count(*) AS rows_,
       count(DISTINCT "TEAM_ID") AS teams, count(DISTINCT "APP_ID") AS apps
FROM "DEVOPS_TEAM_APP_MONTHLY_COSTS"
UNION ALL
SELECT 'DEVOPS_CUSTOMER_IMPACT', count(*), NULL, count(DISTINCT "APP_ID")
FROM "DEVOPS_CUSTOMER_IMPACT";

-- 1. First-of-month convention (0 rows expected)
SELECT count(*) AS not_first_of_month
FROM "DEVOPS_TEAM_APP_MONTHLY_COSTS" WHERE extract(day FROM "COST_MONTH") <> 1;

-- 2. Monthly spend + effort curve (profile)
SELECT "COST_MONTH",
       count(*) AS active_pairs,
       round(sum("CLOUD_COST")::numeric, 0) AS cloud_cost,
       round(sum("ENGINEERING_HOURS")::numeric, 0) AS eng_hours
FROM "DEVOPS_TEAM_APP_MONTHLY_COSTS" GROUP BY 1 ORDER BY 1;

-- 3. Run/Grow/Transform investment mix (profile)
SELECT "BUDGET_CATEGORY", count(*) AS rows_,
       round(sum("CLOUD_COST")::numeric, 0) AS cloud_cost,
       round(sum("ENGINEERING_HOURS")::numeric, 0) AS eng_hours
FROM "DEVOPS_TEAM_APP_MONTHLY_COSTS" GROUP BY 1 ORDER BY 3 DESC;

-- 4. SLA + detection profile
SELECT "SLA_STATUS", "DETECTION_SOURCE", count(*) AS impacts,
       sum("CUSTOMERS_AFFECTED") AS customers_affected
FROM "DEVOPS_CUSTOMER_IMPACT" GROUP BY 1, 2 ORDER BY 1, 4 DESC;
