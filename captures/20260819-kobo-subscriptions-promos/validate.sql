-- =====================================================================================
-- Post-load consistency suite for the Kobo extension tables (run in Neon PG, psql).
-- Every check lists violations; a correct load returns 0 rows / expected counts.
-- =====================================================================================

-- 0. Row inventory
SELECT 'KOBO_SUBSCRIPTION_MONTHS' AS t, count(*) AS rows_, count(DISTINCT "CUSTOMER_ID") AS customers
FROM "KOBO_SUBSCRIPTION_MONTHS"
UNION ALL
SELECT 'KOBO_PROMO_REDEMPTIONS', count(*), count(DISTINCT "CUSTOMER_ID")
FROM "KOBO_PROMO_REDEMPTIONS";

-- 1. Snapshot integrity: one row per (customer, month) is DDL-enforced (UQ);
--    months must be contiguous per customer (no gaps between first and last).
SELECT "CUSTOMER_ID",
       count(*) AS months_present,
       (extract(year FROM age(max("DATE"), min("DATE"))) * 12
        + extract(month FROM age(max("DATE"), min("DATE"))) + 1) AS months_expected
FROM "KOBO_SUBSCRIPTION_MONTHS"
GROUP BY 1
HAVING count(*) <> (extract(year FROM age(max("DATE"), min("DATE"))) * 12
                    + extract(month FROM age(max("DATE"), min("DATE"))) + 1);

-- 2. Status semantics: exactly one 'New'-or-single-'Churned' opening row; 'Churned'
--    only on the last month; flag/status coherence is DDL-enforced (CK).
SELECT s."CUSTOMER_ID"
FROM "KOBO_SUBSCRIPTION_MONTHS" s
WHERE s."SUBSCRIPTION_STATUS" = 'Churned'
  AND s."DATE" <> (SELECT max(s2."DATE") FROM "KOBO_SUBSCRIPTION_MONTHS" s2
                   WHERE s2."CUSTOMER_ID" = s."CUSTOMER_ID");

-- 3. First-of-month convention
SELECT count(*) AS not_first_of_month
FROM "KOBO_SUBSCRIPTION_MONTHS" WHERE extract(day FROM "DATE") <> 1;

-- 4. MRR matches plan price
SELECT DISTINCT "PLAN_TYPE", "MRR_AMOUNT" FROM "KOBO_SUBSCRIPTION_MONTHS"
WHERE ("PLAN_TYPE", "MRR_AMOUNT") NOT IN (VALUES
    ('Kobo Plus Read', 7.99::double precision),
    ('Kobo Plus Listen', 7.99::double precision),
    ('Kobo Plus Read & Listen', 9.99::double precision));

-- 5. Promo discount sanity: positive (CK-enforced) and 3%..56% of implied gross
--    requires the SALES net amount, which lives in the Snowflake side of the model —
--    validated cross-store through the Mosaic/Trino layer instead (see README).

-- 6. Monthly business curve (eyeball): active subscribers should trend up,
--    churned counts stay small.
SELECT "DATE",
       sum("IS_ACTIVE_EOM") AS active_eom,
       count(*) FILTER (WHERE "SUBSCRIPTION_STATUS" = 'New') AS new_subs,
       count(*) FILTER (WHERE "SUBSCRIPTION_STATUS" = 'Churned') AS churned,
       round(sum("MRR_AMOUNT")::numeric, 2) AS mrr
FROM "KOBO_SUBSCRIPTION_MONTHS" GROUP BY 1 ORDER BY 1;

-- 7. Campaign mix
SELECT "CAMPAIGN_NAME", "PROMO_TYPE", count(*) AS redemptions,
       round(sum("DISCOUNT_AMOUNT")::numeric, 2) AS total_discount
FROM "KOBO_PROMO_REDEMPTIONS" GROUP BY 1, 2 ORDER BY 3 DESC;
