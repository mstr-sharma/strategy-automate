# DevOpsCo finance & customer-impact extension — 2026-08-19

Extends the Studio Mosaic model **"Deployment and Incident Analytics"**
(`CD3ACE32C83E48D5B28D6D790111C7B2`, Shared Studio > My Reports > DevOpsCo,
`dataServeMode: in_memory`) with two Neon PostgreSQL tables. Same pattern as
the EReaderCo extension (`captures/20260819-ereader-subscriptions-promos/`).

## Business brief (translation artifact)

DevOps leaders lack a unified view of software delivery performance: where
resources are spent, whether teams deliver efficiently, and where quality or
release risks are emerging — data is fragmented across development, operations,
**finance**, and **customer** systems.

The existing model covers dev + ops: DEPLOYMENTS (deployment grain, Lead Time
Hours), INCIDENTS (incident grain, Resolution Time Hours), TEAMS (Headcount),
APPLICATIONS (List Cost Per Deployment — a static benchmark, not actual spend).
The two missing stores:

| New table (Neon PG `neondb.public`) | Grain | Metric(s) |
| --- | --- | --- |
| `DEVOPS_TEAM_APP_MONTHLY_COSTS` | team × application × month, activity-based (a row per month the team deployed that app; `COST_MONTH` = first of month) | **Cloud Infrastructure Cost** = SUM(CLOUD_COST), **Engineering Hours Logged** = SUM(ENGINEERING_HOURS) |
| `DEVOPS_CUSTOMER_IMPACT` | customer-impacting incident (≤1 per INCIDENTS row, `INCIDENT_ID` unique) | **Customers Affected** = SUM(CUSTOMERS_AFFECTED) |

New dimension attributes at integration: Budget Category (Run/Grow/Transform —
investment-mix lens), SLA Status (Met/Breached), Detection Source.

Governed derivations enabled: actual cost per deployment vs the list benchmark,
cost per engineering hour, Run/Grow/Transform mix by department/segment, SLA
breach rate by severity/tier, customer blast radius per release risk.

## Conformance

Both tables carry the model's conformed keys with byte-identical UPPERCASE
column names: `TEAM_ID` → Team (→ Team Name, Department, Segment), `APP_ID` →
Application (→ Name, Criticality Tier, Technology Stack), `INCIDENT_ID` →
Incident (1:1), `INCIDENT_DATE` → Incident Date. `COST_MONTH` is a new monthly
date — at integration it should conform into ONE model-wide date attribute
(note: the model already splits Deployment Date vs Incident Date; same
fan-trap risk as the EReaderCo date split — unify when doing the best-practice pass).

## Synthetic data (deterministic, seed 20260820)

Inputs `teams.csv` / `apps.csv` / `deployments.csv` / `incidents.csv` are real
keys extracted from the published cube (65 teams, 120 apps, 3,800 deployments,
2,200 incidents, 2025-01 → 2026-08). Generated: **3,658** cost rows
(cloud $1,153,120.14, hours 1,763,236) and **737** impact rows (34% of
incidents; 3,040,885 customers affected; 14% SLA-breached).

Consistency rules enforced (generator invariant checks, all passing):
- cost rows ↔ deployment activity align 1:1 on (team, app, month) — no phantom
  spend, no unaccounted deploy months;
- engineering hours conserve team capacity (headcount × 140–170h per
  team-month), apportioned by deploy count with failed/rolled-back deployments
  pulling a 1.5× share (**planted rework signal**: hours-per-deploy rises with
  failure rate);
- CLOUD_COST = tier base + deploys × real LIST_COST_PER_DEPLOY × U(0.85,1.35),
  so actual-vs-list cost comparisons are meaningful;
- SLA_STATUS derived from the parent incident's REAL resolution time vs
  severity targets (SEV-1 4h / SEV-2 24h / SEV-3 72h);
- impact rows mirror parent incident date/app; CUSTOMERS_AFFECTED scales with
  severity × app criticality tier.

## Files

- `ddl.sql` — quoted-UPPERCASE DDL with PK/UQ/CK constraints
- `generate.py` — deterministic generator (rerun → identical CSVs)
- `load.py` — DDL + load (creds via `PGHOST/PGUSER/PGPASSWORD/PGDATABASE`)
- `validate.sql` — post-load PG checks + profiles
- `teams.csv` / `apps.csv` / `deployments.csv` / `incidents.csv` — committed cube extracts
- `team_app_monthly_costs.csv` / `customer_impact.csv` — generated loads

## Status

Tables created + loaded + validated in Neon (2026-08-19). Operator added them
to the model in Studio (plain add: original names kept, 3 auto metrics, 32
attrs / 20 edges). **Best-practice pass applied same day via
`best_practice_update.py` and verified in data:**

- **One conformed "Activity Date"** (renamed from Incident Date; gained
  DEPLOY_DATE + COST_MONTH expressions; Deployment Date + 5 smarts deleted;
  junk `ID (1)` date form removed from the Cost Month grain anchor). Verified:
  deployments, incidents, cloud cost, and hours all trend on one attribute
  with monthly values matching the PG curve exactly.
- **Multi-form folds**: Team (ID + Name) and Application (ID + Name); separate
  Team Name / Application Name attributes deleted; Name set as display form.
- **All 7 metrics corrected**: List Cost Per Deployment → avg + currency
  (dp was 14!), Lead Time Hours → avg (DORA lead time), Resolution Time
  Hours → avg (MTTR), Cloud Cost → currency, Headcount / Customers Affected →
  integer, Engineering Hours → 1dp; business-first descriptions on every metric.
- **Kimball topology**: 23 descriptor→grain-anchor edges across 19 attributes;
  fixed the inverted Impact→Incident edge and the fully-orphaned Budget
  Category (now rolls up Run $594,304.11 / Grow $292,528.27 / Transform
  $266,287.76 — exact PG match). Totals verified: cloud $1,153,120.14, hours
  1,763,236, customers affected 3,040,885 (737 impacts, SLA breach pattern
  coherent with severity targets).

Gotcha captured: removing an attribute form 404s with `8004cc63` unless the
PATCH body carries `forms` AND corrected `displays` atomically (see
`memory/feedback_mosaic_ship_bar.md`).

## Cross-store LEVEL metrics (added + validated 2026-08-19)

`create_level_metrics.py` (final consolidated recipe) + `validate_level_metrics.py`
(+ `level_metric_expectations.json`, derived from the committed CSVs):

- Fact metrics: **Deployment Count** (= DORA deployment frequency when trended),
  **Incident Count**.
- Level intermediates (tokens, attribute-ONLY dimty): Team Cloud Cost @Team,
  Team Deployment Count @Team (`Count({Deployment})` — Sum over a count-function
  metric evaluates NULL), App Customers Affected @App, App Incident Count @App.
- Finals (tree divide, dimty null):
  **Team Cost per Deployment** = PG cloud spend / Snowflake deployment count @Team —
  constant benchmark on any row (Legacy Ops $343.80; grand total $303.45 vs $156.68
  avg list benchmark).
  **App Blast Radius per Incident** = PG customers affected / Snowflake incident
  count @Application.
- Validation: 65/65 teams and 111/111 impacted apps constant-within-parent AND equal
  to source-computed expectations; the 9 zero-impact apps are null-by-design (and the
  engine drops their rows from mixed grids — metric join type; count totals validated
  on clean grids: 3,800 / 2,200 exact).
- Five REST gotchas discovered en route are recorded in
  `memory/reference_mosaic_derived_metrics.md` §0b and the error-code index
  (8004cb04, 8004d711, 8004d716, 8004cd15-variant, plus the report-level no-op
  semantics).
