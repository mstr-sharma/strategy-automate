# AI-rebuilt model vs Built-by-Claude copy — comparison (2026-08-19)

Two published in_memory models over the identical 6 physical tables (4 Snowflake
MCI_DEMO + 2 Neon PG), Shared Studio > My Reports > Kobo:

- **Rebuilt (main)**: "Kobo Content & Customer Engagement Model"
  `20B2F4E3B58A47C7825C2C7A8D0559E9` — operator re-derived via Mosaic's built-in
  AI modeling service on 2026-08-19 21:19Z (edited in place; table objectIds kept).
- **Copy**: "Built-by-Claude_Kobo Content & Customer Engagement Model"
  `70F8B6DC20834DD6BADA7E6D53D069F9` — snapshot of the REST-wired state from
  `integrate_model.py`.

## Metric fixes applied to the rebuilt model (this session, `fix_metrics.py`)

| Metric | AI-rebuild state | Fixed to | Why |
| --- | --- | --- | --- |
| List Price | sum, cat 1 `#,##0.00` | **avg**, currency `$#,##0.00` | a unit price never sums |
| Transaction Amount | sum, cat 1 plain number | sum, currency | revenue metric |
| Minutes Consumed | sum, cat 0 General | sum, integer `#,##0` | count class |
| Monthly Recurring Revenue Amount | sum, **cat 9 / 'General'** (broken) | sum, currency | revenue metric |
| Discount Amount | sum, **cat 9 / 'General'** (broken) | sum, currency | revenue metric |
| **Active Subscribers** | **missing** — AI demoted the 0/1 flag to attribute "Is Active End Of Month", deleting the governed ARPU denominator | **recreated**: SUM(KOBO_SUBSCRIPTION_MONTHS.IS_ACTIVE_EOM), integer | 3rd requested metric; attribute left in place for filtering |

One changeset (`identity=True`), republished, REST read-back verified.

## Where the two models agree (verified in data, post-publish)

Conformed-key coverage is identical for Customer (5 tables), Content (4),
Transaction (2), Sales Channel (2), Content Category/Subcategory, Region, City —
the AI rebuild preserved the PG-table expressions. Paired queries returned
**identical results**, all tying to source:

- Revenue by channel: 11,267.08 / 6,577.37 / 21,190.64 / 4,070.02 (Σ 43,105.11)
- MRR + subscriber-months by plan: 18,051.99 / 1,933 total
- MRR, subs, discounts by customer segment (cross-table via Customer): identical
- Discount by campaign: identical, Σ 4,390.70

## Where they differ

### 1. The date dimension is SPLIT on the rebuilt model — silent cross-fact inflation

Copy: ONE conformed date ("Engagement Date") spans ENGAGEMENT + SALES +
KOBO_SUBSCRIPTION_MONTHS + KOBO_PROMO_REDEMPTIONS.
Rebuilt: "Session Date" (ENGAGEMENT + SALES + PROMO) and a separate
"Subscription Month Start Date" (SUBSCRIPTION_MONTHS only), each with its own
smart Day..Year family.

**Verified data impact:** `sum(MRR) GROUP BY session date (month)` on the rebuilt
model returns plausible-looking but **~10× inflated** values (2025-01: $7,757.44
vs true $229.74) — a fan-trap join through Customer, since SUBS has no Session
Date mapping. The same query shape on the copy's single date is correct. The
rebuilt model trends MRR correctly ONLY via "Subscription Month Start Date"
(verified: 229.74 / 461.49 / 779.14 …). Consequence: "total revenue = sales +
subscriptions by month" on one date attribute is unsafe on the rebuilt model.

### 2. Naming (AI vs original)

Transaction Amount ↔ Sales Amount · Monthly Recurring Revenue Amount ↔
Subscription Revenue · Discount Amount ↔ Promo Discount Amount · Campaign Name ↔
Campaign · Promotion Type ↔ Promo Type · Redemption ↔ Promo Redemption ·
Format Category ↔ Format Category Key · Session Date ↔ Engagement Date.
Descriptions AI-rewritten model-wide on the rebuilt.

### 3. Attribute style

Rebuilt folds TITLE into Content as a second form (multi-form attribute); copy
keeps the original separate "Content Title" attribute. Rebuilt carries the extra
"Is Active End Of Month" attribute (kept as a filter flag).

### 4. Relationships (drill paths / hierarchy correctness)

Copy (Kimball): descriptors → grain anchors — 12 edges into Subscription Month /
Promo Redemption, plus Customer→Transaction, Content→Transaction.

Rebuilt: **zero edges into Subscription Month and Redemption**; subscription
descriptors wired to Customer instead, including two semantically wrong claims —
`Subscription Status → Customer` and `Is Active End Of Month → Customer` (both
vary by month, not per customer) — and two inverted edges
(`Subscription Month → Signup Source`, `Redemption → Promotion Type`).
Campaign Name is treated as an entity hub (Customer/Content/Session Date →
Campaign Name → Sales Channel). Customer→Transaction and Content→Transaction were
dropped; Region/City→Transaction added. Same-table aggregations are unaffected
(hence the identical query results above); these edges mainly distort drill
hierarchies and multi-hop join paths.

## Follow-ups — APPLIED 2026-08-19 (`best_practice_update.py`), verified in data

1. **One conformed date**: `KOBO_SUBSCRIPTION_MONTHS.DATE` mapped into the shared
   date attribute; the redundant "Subscription Month Start Date" (+5 smarts)
   deleted; family renamed **"Activity Date"** (neutral: sessions, sales,
   redemptions, subscription months). Verified: sales + MRR + subscribers by
   Activity Date month now returns the true curve (MRR 229.74 … 920.98) — the
   ~10× fan-trap is gone.
2. **Kimball topology**: full rewire to 38 descriptor→grain-anchor edges across
   26 attributes (replace PUTs of curated per-attribute sets). Wrong per-customer
   claims, inverted edges, and the Campaign hub removed; Customer/Content/
   Activity Date→Transaction restored; geo chain Country→Region→City→Customer.
3. **Multi-form Customer**: separate "Email Address" attribute deleted; Customer
   now carries ID + Name + Email forms (Email in report/browse displays).
   Verified queryable as `customer (email)`.
4. Rollup consistency re-verified post-republish: MRR $18,051.99 / discounts
   $4,390.70 / sales $43,105.11 identical through region, segment, plan, and
   month paths.
