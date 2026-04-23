---
name: build_mosaic.py auto-conformance is case-sensitive and same-name-only
description: The helper's shared-column conformance groups table columns into one entity attribute only when the column names match exactly (case-sensitive) across tables. Mixed-case warehouses (lowercase Postgres, uppercase Snowflake) and intentionally-different FK names (`primary_impacted_tenant_id` vs `tenant_id`) break conformance silently, yielding an under-joined model that the user rightly calls "not correct".
type: feedback
---

**Observed 2026-04-23** on the Tenant GPU Analysis build:

- `cluster_id` in Neon `incidents` and Neon `tenant_service_hourly`, `CLUSTER_ID` in Snowflake `USAGE_HOURLY` — the helper produced one `Cluster` attribute bound only to `USAGE_HOURLY` (first match wins; lowercase+uppercase did not conform).
- `tenant_id` in `tenant_service_hourly`, `TENANT_ID` in `TENANTS` and `USAGE_HOURLY` — produced `Tenant` attribute with only TENANTS + USAGE_HOURLY expressions; the Postgres `tenant_id` was orphaned.
- `primary_impacted_tenant_id` in `incidents` — not the same name, so never grouped. It became its own standalone attribute with no relationship back to Tenant. Model UI showed "no joins" between Incidents and Tenants, which is exactly what the user flagged.

**How to apply:**
1. When sources span mixed-case warehouses, always declare relationships explicitly in the dictionary:
   ```json
   "relationships": [
     {"parent":"TENANTS.TENANT_ID","child":"tenant_service_hourly.tenant_id","relationship_table":"tenant_service_hourly","type":"one_to_many"},
     {"parent":"TENANTS.TENANT_ID","child":"incidents.primary_impacted_tenant_id","relationship_table":"incidents","type":"one_to_many"}
   ]
   ```
   (This disables auto-conformance, so EVERY shared-column pair must be listed. Do not mix styles.)
2. Or supply an ERD (`.dbml` / `.sql` / `.json`) covering every cross-table join.
3. Fix candidate for the helper: before conformance, normalize column names to a comparable key (`col.lower()`) AND offer an `--fk-map` flag mapping FK aliases (`incidents.primary_impacted_tenant_id -> tenants.tenant_id`) so differently-named FKs still conform.
4. Post-build reality check: for every pair of fact tables that the user expects to join, confirm `GET /api/model/dataModels/{id}/attributes/{id}` shows `forms[*].expressions` spanning both tables. If not, either PATCH the attribute to add the second expression OR add an explicit relationship. Do not ship an under-joined Mosaic model — the UI renders it as disconnected star fragments, which reads as "broken" to end users.
