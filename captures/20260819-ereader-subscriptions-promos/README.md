# EReaderCo subscription & promotion extension — 2026-08-19

Extends the Studio Mosaic model **"EReaderCo Content & Customer Engagement Model"**
(`20B2F4E3B58A47C7825C2C7A8D0559E9`, Shared Studio > My Reports > EReaderCo,
`dataServeMode: in_memory`) with two Neon PostgreSQL tables and exactly three
new governed fact metrics.

## Business brief (translation artifact)

EReaderCo wants one trusted view across **digital book sales,
subscriptions, and reading/listening engagement**: consistent revenue, ARPU,
churn, content-performance, and cohort measures to optimize pricing,
promotions, catalog investment, partnerships, and discovery.

The existing model covers à-la-carte sales (SALES, transaction grain),
engagement (ENGAGEMENT, session grain), and the CONTENT / CUSTOMERS dimensions
— with only 3 metrics (List Price, Sales Amount, Minutes Consumed). The two
missing business processes were **recurring subscription revenue** and
**promotion economics**:

| New table (Neon PG `neondb.public`) | Grain | Metric(s) |
| --- | --- | --- |
| `EREADER_SUBSCRIPTION_MONTHS` | subscriber × calendar month (periodic snapshot; `DATE` = first of month) | **Subscription Revenue** = SUM(MRR_AMOUNT), **Active Subscribers** = SUM(IS_ACTIVE_EOM) |
| `EREADER_PROMO_REDEMPTIONS` | promo redemption (≤1 per SALES transaction, `TRANSACTION_ID` unique) | **Promo Discount Amount** = SUM(DISCOUNT_AMOUNT) |

Governed derivations these enable: `ARPU = Subscription Revenue / Active
Subscribers`, `gross sales = Sales Amount + Promo Discount Amount`,
`effective discount rate = Promo Discount / (Sales Amount + Promo Discount)`,
subscription churn rate from `Subscription Status = 'Churned'` counts vs
Active Subscribers.

## Conformance (aggregation at every existing grain)

Both tables carry the model's conformed keys with **byte-identical UPPERCASE
column names**, and the integration script appends their expressions into the
existing attributes (not parallel dimensions):

- `CUSTOMER_ID` → **Customer** (→ Segment, Country/Region/City, Acquisition/Churn Date cohorts)
- `DATE` → **Engagement Date** (→ smart Day/Week/Month/Quarter/Year attributes)
- `CONTENT_ID` → **Content** (→ Title, Author, Format, Category, Subcategory, Publisher) — promo table
- `TRANSACTION_ID` → **Transaction** (1:1 tie to the discounted sale) — promo table
- `CHANNEL` → **Sales Channel** — promo table

New dimension attributes: Subscription Month, Plan Type, Signup Source
(discovery analysis), Subscription Status, Promo Redemption, Campaign,
Promo Type.

## Synthetic data (deterministic, seed 20260819)

Inputs `customers.csv` / `content.csv` / `sales.csv` are **real keys extracted
from the published cube** (`POST /api/v2/cubes/{id}/instances`, element ids
carry the ID-form key). Generated volumes: **2,001** subscription-months
(169 subscribers of 280 customers, active EoM 26 → 101 across
2025-01..2026-08, EReaderCo Plus tiers 7.99/7.99/9.99) and **1,239** promo
redemptions (34% of the 3,600 transactions, 10 campaigns incl. Black Friday
2025, Partner Points Day, format/category-targeted windows).

Consistency rules enforced (see `validate.sql` + generator invariant checks):
contiguous subscription months; account-churned customers' subscriptions end
on/before their `CHURN_DATE` month with status `Churned`; `IS_ACTIVE_EOM=0`
exactly on churn months; promo rows mirror the parent transaction's
date/customer/content/channel; discounts imply 3–56% off gross where
`gross = net AMOUNT + DISCOUNT_AMOUNT`.

## Files

- `ddl.sql` — quoted-UPPERCASE DDL with PK/UQ/CK constraints
- `generate.py` — deterministic generator (rerun → byte-identical CSVs)
- `load.py` — DDL + load into PG (creds via `PGHOST/PGUSER/PGPASSWORD/PGDATABASE`)
- `validate.sql` — post-load PG consistency suite
- `integrate_model.py` — one-session model integration: add pipeline tables →
  new attrs + 3 fact metrics (formats at create time) → schemaEdit conform pass →
  merged relationship PUTs → post-add audit → publish trigger.
  Creds via `MSTR_*` env vars.
- `customers.csv` / `content.csv` / `sales.csv` — committed cube extracts (generator inputs)
- `subscription_months.csv` / `promo_redemptions.csv` — generated loads (committed for reproducibility)

## Postscript (2026-08-19 ~21:19Z)

After `integrate_model.py` committed and its publish landed, a whole-model
re-derivation pass ran on the tenant (every object, including the four original
Snowflake tables, re-stamped `dateModified=21:19:17.505Z` in one operation —
operator working in the Studio UI). Effects vs. this capture's committed state:
both PG tables retained; metrics renamed (Sales Amount → "Transaction Amount",
Subscription Revenue → "Monthly Recurring Revenue Amount", Promo Discount
Amount → "Discount Amount"); Engagement Date renamed "Session" and smart dates
added to Acquisition/Churn Date; **the Active Subscribers fact metric was
dropped — IS_ACTIVE_EOM was re-classified as an attribute** ("Is Active End Of
Month"), a known failure class of whole-model auto passes (0/1 flag reads as a
dimension). Model-side state is now owned by the operator; this capture remains
the record of the REST-committed state and the reusable recipe.

## Gotchas hit in this session (fed back to memory)

1. **Changeset commit 400s bare** when a table commits with no bound
   attribute/metric (`8004e42f` class): tables + their attributes + metrics
   must land in ONE changeset. A tables-only changeset is uncommittable.
2. `commit_cs()` `die()`s with `SystemExit`, which an `except Exception`
   discard path does not catch — orphaned changesets result; use
   `open_cs(release_self_locks=True)` on the next run and raise catchable
   errors instead.
3. Identity token IS required for Mosaic data-model changeset commits even on
   studio (the tenant's "identity-off" note applies to classic/project reads);
   `cmd_build` itself logs in with `identity=True`.
