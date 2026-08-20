-- =====================================================================================
-- Kobo unified business metrics -- subscription & promotion extension tables (PostgreSQL / Neon)
--
-- Extends the Studio Mosaic model
--   "Kobo Content & Customer Engagement Model" (20B2F4E3B58A47C7825C2C7A8D0559E9)
-- which holds CONTENT (content grain) / CUSTOMERS (customer grain) /
-- ENGAGEMENT (session grain) / SALES (transaction grain) in Snowflake MCI_DEMO,
-- with exactly 3 fact metrics: List Price, Sales Amount, Minutes Consumed.
--
-- Use case: unified, trusted view across digital book sales, SUBSCRIPTIONS, and
-- engagement -- consistent revenue / ARPU / churn / content-performance / cohort
-- measures, plus pricing & promotion optimization and discovery-source analysis.
--
-- New grains (each carries the full conformed key set, so every metric aggregates
-- at ALL existing grains: customer, content, transaction, channel, geography via
-- Customer, and calendar day/week/month/quarter/year via the shared date role):
--   KOBO_SUBSCRIPTION_MONTHS   (subscriber x calendar month, periodic snapshot)
--   KOBO_PROMO_REDEMPTIONS     (promo redemption == discounted sales transaction)
--
-- Three new governed metrics (exactly three, per request):
--   Subscription Revenue   = SUM(KOBO_SUBSCRIPTION_MONTHS.MRR_AMOUNT)     currency
--   Active Subscribers     = SUM(KOBO_SUBSCRIPTION_MONTHS.IS_ACTIVE_EOM)  integer
--   Promo Discount Amount  = SUM(KOBO_PROMO_REDEMPTIONS.DISCOUNT_AMOUNT)  currency
-- These enable governed derivations: ARPU = Subscription Revenue / Active
-- Subscribers; gross sales = Sales Amount + Promo Discount Amount; effective
-- discount rate = Promo Discount Amount / (Sales Amount + Promo Discount Amount).
--
-- Identifiers are quoted UPPERCASE to byte-match the column names already in the
-- Studio model (CUSTOMER_ID, CONTENT_ID, TRANSACTION_ID, DATE, CHANNEL), so the
-- model conforms the new tables into the existing attributes instead of creating
-- parallel dimensions.
-- =====================================================================================

DROP TABLE IF EXISTS "KOBO_PROMO_REDEMPTIONS";
DROP TABLE IF EXISTS "KOBO_SUBSCRIPTION_MONTHS";

-- -------------------------------------------------------------------------------------
-- 1. KOBO_SUBSCRIPTION_MONTHS
--    Grain: one row per subscriber per calendar month with a PAID Kobo Plus
--    subscription that month ("DATE" = first day of month, standard periodic
--    snapshot convention). A customer appears in consecutive months from signup
--    to cancellation.
--    Additive: MRR_AMOUNT, IS_ACTIVE_EOM.
--    SUBSCRIPTION_STATUS row semantics: 'New' = first paid month,
--    'Active' = continuing month, 'Churned' = final paid month (subscriber
--    cancelled during it; IS_ACTIVE_EOM = 0 on exactly these rows).
-- -------------------------------------------------------------------------------------
CREATE TABLE "KOBO_SUBSCRIPTION_MONTHS" (
    "SUB_MONTH_ID"          varchar(20)      NOT NULL,  -- PK, degenerate ('SUBM-000001')
    -- ---- conformed keys back to the Studio model ----
    "DATE"                  date             NOT NULL,  -- first of month; conforms to ENGAGEMENT.DATE / SALES.DATE
    "CUSTOMER_ID"           varchar(12)      NOT NULL,  -- FK -> CUSTOMERS.CUSTOMER_ID
    -- ---- subscription descriptors (new dimensions) ----
    "PLAN_TYPE"             varchar(30)      NOT NULL,  -- 'Kobo Plus Read' | 'Kobo Plus Listen' | 'Kobo Plus Read & Listen'
    "SIGNUP_SOURCE"         varchar(30)      NOT NULL,  -- discovery channel: 'Kobo Storefront', 'Email Campaign', ...
    "SUBSCRIPTION_STATUS"   varchar(10)      NOT NULL,  -- 'New' | 'Active' | 'Churned' (month-level state)
    -- ---- measures ----
    "MRR_AMOUNT"            double precision NOT NULL,  -- monthly recurring revenue recognized this month (USD)
    "IS_ACTIVE_EOM"         integer          NOT NULL,  -- 1 = still active at end of month, 0 = churned during month
    CONSTRAINT "PK_KOBO_SUBSCRIPTION_MONTHS" PRIMARY KEY ("SUB_MONTH_ID"),
    CONSTRAINT "UQ_KOBO_SUB_CUST_MONTH" UNIQUE ("CUSTOMER_ID", "DATE"),
    CONSTRAINT "CK_KOBO_SUB_STATUS" CHECK ("SUBSCRIPTION_STATUS" IN ('New','Active','Churned')),
    CONSTRAINT "CK_KOBO_SUB_FLAG" CHECK ("IS_ACTIVE_EOM" IN (0,1)),
    CONSTRAINT "CK_KOBO_SUB_FLAG_STATUS" CHECK (("IS_ACTIVE_EOM" = 0) = ("SUBSCRIPTION_STATUS" = 'Churned'))
);

-- -------------------------------------------------------------------------------------
-- 2. KOBO_PROMO_REDEMPTIONS
--    Grain: one row per promotion redemption; at most one per sales transaction
--    (TRANSACTION_ID is unique), so it joins 1:1 onto the SALES fact through the
--    conformed Transaction attribute. DATE / CUSTOMER_ID / CONTENT_ID / CHANNEL
--    replicate the parent transaction's values so the table also aggregates
--    standalone at every grain without traversing SALES.
--    Additive: DISCOUNT_AMOUNT (USD given away; SALES.AMOUNT is the net paid,
--    so gross = AMOUNT + DISCOUNT_AMOUNT).
-- -------------------------------------------------------------------------------------
CREATE TABLE "KOBO_PROMO_REDEMPTIONS" (
    "REDEMPTION_ID"     varchar(20)      NOT NULL,      -- PK, degenerate ('PRM-000001')
    -- ---- conformed keys back to the Studio model ----
    "TRANSACTION_ID"    varchar(40)      NOT NULL,      -- FK -> SALES.TRANSACTION_ID (1:1)
    "DATE"              date             NOT NULL,      -- = parent transaction date
    "CUSTOMER_ID"       varchar(12)      NOT NULL,      -- FK -> CUSTOMERS.CUSTOMER_ID
    "CONTENT_ID"        varchar(12)      NOT NULL,      -- FK -> CONTENT.CONTENT_ID
    "CHANNEL"           varchar(20)      NOT NULL,      -- conforms to SALES.CHANNEL (Sales Channel)
    -- ---- promotion descriptors (new dimensions) ----
    "CAMPAIGN_NAME"     varchar(40)      NOT NULL,      -- 'Black Friday 2025', 'Summer Reading 2026', ...
    "PROMO_TYPE"        varchar(30)      NOT NULL,      -- 'Percentage Discount', 'Rakuten Points Redemption', ...
    -- ---- measures ----
    "DISCOUNT_AMOUNT"   double precision NOT NULL,      -- USD discount vs list-derived gross price
    CONSTRAINT "PK_KOBO_PROMO_REDEMPTIONS" PRIMARY KEY ("REDEMPTION_ID"),
    CONSTRAINT "UQ_KOBO_PROMO_TXN" UNIQUE ("TRANSACTION_ID"),
    CONSTRAINT "CK_KOBO_PROMO_DISC" CHECK ("DISCOUNT_AMOUNT" > 0)
);

CREATE INDEX "IX_KOBO_SUB_CUSTOMER" ON "KOBO_SUBSCRIPTION_MONTHS" ("CUSTOMER_ID");
CREATE INDEX "IX_KOBO_SUB_DATE"     ON "KOBO_SUBSCRIPTION_MONTHS" ("DATE");
CREATE INDEX "IX_KOBO_PROMO_CUST"   ON "KOBO_PROMO_REDEMPTIONS" ("CUSTOMER_ID");
CREATE INDEX "IX_KOBO_PROMO_DATE"   ON "KOBO_PROMO_REDEMPTIONS" ("DATE");
