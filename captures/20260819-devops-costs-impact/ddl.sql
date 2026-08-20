-- =====================================================================================
-- DevOpsCo software-delivery performance -- finance & customer extension tables (PostgreSQL / Neon)
--
-- Extends the Studio Mosaic model
--   "Deployment and Incident Analytics" (CD3ACE32C83E48D5B28D6D790111C7B2)
-- which holds DEPLOYMENTS (deployment grain) / INCIDENTS (incident grain) /
-- TEAMS / APPLICATIONS in Snowflake <snowflake-schema>, with 4 metrics: Lead Time Hours,
-- Resolution Time Hours, Headcount, List Cost Per Deployment.
--
-- Use case: DevOps leaders need ONE view of software delivery performance --
-- where resources are spent, whether teams deliver efficiently, and where
-- quality/release risks are emerging -- across development, operations,
-- FINANCE, and CUSTOMER systems. The model covers dev+ops; these tables add
-- the missing finance and customer stores.
--
-- New grains (conformed keys TEAM_ID / APP_ID / INCIDENT_ID carried so every
-- metric aggregates at team, department, segment, application, criticality
-- tier, tech stack, severity, and calendar grains):
--   DEVOPS_TEAM_APP_MONTHLY_COSTS  (team x application x month, activity-based:
--                                a row exists for each month the team deployed
--                                that app; ties spend to real delivery activity)
--   DEVOPS_CUSTOMER_IMPACT         (one row per customer-impacting incident,
--                                <=1 per INCIDENTS row via unique INCIDENT_ID)
--
-- Three new governed metrics (exactly three, mirroring the EReaderCo pattern):
--   Cloud Infrastructure Cost = SUM(DEVOPS_TEAM_APP_MONTHLY_COSTS.CLOUD_COST)        currency
--   Engineering Hours Logged  = SUM(DEVOPS_TEAM_APP_MONTHLY_COSTS.ENGINEERING_HOURS) number
--   Customers Affected        = SUM(DEVOPS_CUSTOMER_IMPACT.CUSTOMERS_AFFECTED)       integer
-- Governed derivations these enable: actual cost per deployment (vs the list
-- benchmark already in the model), cost per engineering hour, Run/Grow/Transform
-- investment mix, SLA breach rate, customer blast radius per severity/tier.
--
-- Identifiers quoted UPPERCASE to byte-match the model's existing column names.
-- =====================================================================================

DROP TABLE IF EXISTS "DEVOPS_CUSTOMER_IMPACT";
DROP TABLE IF EXISTS "DEVOPS_TEAM_APP_MONTHLY_COSTS";

-- -------------------------------------------------------------------------------------
-- 1. DEVOPS_TEAM_APP_MONTHLY_COSTS
--    Grain: one row per (team, application, calendar month) in which that team
--    deployed that application ("COST_MONTH" = first day of month). Engineering
--    hours conserve team capacity: per team-month they sum to ~headcount x 155h,
--    apportioned across the team's active apps -- failed/rolled-back deployments
--    pull a larger share (rework signal).
--    Additive: CLOUD_COST, ENGINEERING_HOURS.
-- -------------------------------------------------------------------------------------
CREATE TABLE "DEVOPS_TEAM_APP_MONTHLY_COSTS" (
    "COST_MONTH_ID"      varchar(20)      NOT NULL,  -- PK, degenerate ('DCM-000001')
    -- ---- conformed keys back to the Studio model ----
    "COST_MONTH"         date             NOT NULL,  -- first of month
    "TEAM_ID"            varchar(12)      NOT NULL,  -- FK -> TEAMS.TEAM_ID
    "APP_ID"             varchar(12)      NOT NULL,  -- FK -> APPLICATIONS.APP_ID
    -- ---- finance descriptor (new dimension) ----
    "BUDGET_CATEGORY"    varchar(12)      NOT NULL,  -- 'Run' | 'Grow' | 'Transform'
    -- ---- measures ----
    "CLOUD_COST"         double precision NOT NULL,  -- infra + pipeline spend that month (USD)
    "ENGINEERING_HOURS"  double precision NOT NULL,  -- engineering effort logged that month
    CONSTRAINT "PK_DEVOPS_COSTS" PRIMARY KEY ("COST_MONTH_ID"),
    CONSTRAINT "UQ_DEVOPS_COSTS_GRAIN" UNIQUE ("TEAM_ID", "APP_ID", "COST_MONTH"),
    CONSTRAINT "CK_DEVOPS_COSTS_BUDGET" CHECK ("BUDGET_CATEGORY" IN ('Run','Grow','Transform')),
    CONSTRAINT "CK_DEVOPS_COSTS_POS" CHECK ("CLOUD_COST" > 0 AND "ENGINEERING_HOURS" > 0)
);

-- -------------------------------------------------------------------------------------
-- 2. DEVOPS_CUSTOMER_IMPACT
--    Grain: one row per customer-impacting incident (subset of INCIDENTS;
--    INCIDENT_ID unique -> joins 1:1 through the conformed Incident attribute).
--    INCIDENT_DATE / APP_ID replicate the parent incident so the table also
--    aggregates standalone at every grain. SLA_STATUS is derived from the
--    parent's real RESOLUTION_TIME_HOURS vs severity targets
--    (SEV-1: 4h, SEV-2: 24h, SEV-3: 72h) -- internally consistent by construction.
--    Additive: CUSTOMERS_AFFECTED.
-- -------------------------------------------------------------------------------------
CREATE TABLE "DEVOPS_CUSTOMER_IMPACT" (
    "IMPACT_ID"           varchar(20) NOT NULL,      -- PK, degenerate ('IMP-000001')
    -- ---- conformed keys back to the Studio model ----
    "INCIDENT_ID"         varchar(12) NOT NULL,      -- FK -> INCIDENTS.INCIDENT_ID (1:1)
    "INCIDENT_DATE"       date        NOT NULL,      -- = parent incident date
    "APP_ID"              varchar(12) NOT NULL,      -- FK -> APPLICATIONS.APP_ID
    -- ---- customer descriptors (new dimensions) ----
    "SLA_STATUS"          varchar(10) NOT NULL,      -- 'Met' | 'Breached' (vs severity target)
    "DETECTION_SOURCE"    varchar(20) NOT NULL,      -- 'Monitoring', 'Customer Reported', ...
    -- ---- measure ----
    "CUSTOMERS_AFFECTED"  integer     NOT NULL,      -- distinct customers impacted
    CONSTRAINT "PK_DEVOPS_IMPACT" PRIMARY KEY ("IMPACT_ID"),
    CONSTRAINT "UQ_DEVOPS_IMPACT_INCIDENT" UNIQUE ("INCIDENT_ID"),
    CONSTRAINT "CK_DEVOPS_IMPACT_SLA" CHECK ("SLA_STATUS" IN ('Met','Breached')),
    CONSTRAINT "CK_DEVOPS_IMPACT_POS" CHECK ("CUSTOMERS_AFFECTED" > 0)
);

CREATE INDEX "IX_DEVOPS_COSTS_TEAM"  ON "DEVOPS_TEAM_APP_MONTHLY_COSTS" ("TEAM_ID");
CREATE INDEX "IX_DEVOPS_COSTS_APP"   ON "DEVOPS_TEAM_APP_MONTHLY_COSTS" ("APP_ID");
CREATE INDEX "IX_DEVOPS_COSTS_MONTH" ON "DEVOPS_TEAM_APP_MONTHLY_COSTS" ("COST_MONTH");
CREATE INDEX "IX_DEVOPS_IMPACT_APP"  ON "DEVOPS_CUSTOMER_IMPACT" ("APP_ID");
CREATE INDEX "IX_DEVOPS_IMPACT_DATE" ON "DEVOPS_CUSTOMER_IMPACT" ("INCIDENT_DATE");
