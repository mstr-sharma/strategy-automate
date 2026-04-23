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

## 2026-04-23 update — explicit relationships in dictionary still fail when parent/child share an attribute

**Observed on the same Tenant GPU build:** even with an explicit `relationships[]` block in the dictionary, the `PUT /api/model/dataModels/{id}/attributes/{childAttrId}/relationships` calls returned:

- `8004ccdb` — *"Attribute (id '…') appears in a relationship more than once."*
- `8004ccc7` — *"Table (id '…') cannot be used as the join table for a relationship involving attribute (id '…')."*

**Why these fire:**
1. When auto-conformance has already merged an attribute across ≥2 tables (e.g., `Tenant` spans TENANTS + USAGE_HOURLY), issuing a relationship whose parent is `TENANTS.TENANT_ID` and child is `USAGE_HOURLY.TENANT_ID` is **a self-reference** — the build script resolves both sides to the same attribute object id. Mosaic rejects it as "appears more than once".
2. The `relationship_table` must contain an expression of BOTH the parent and the child attribute. If the parent attribute has no expression on that table (e.g., Tenant has no expression on the `incidents` table because `primary_impacted_tenant_id` became its own attribute "Primary Impacted Tenant"), the `8004ccc7` fires.
3. Auto-conformance dedupe silently drops the case-mismatched variant of the column from the attribute's expression list (lowercase `tenant_id` column on `tenant_service_hourly` never got added to the `Tenant` attribute because `TENANT_ID` uppercase won the race). Relationships then have no path through the orphaned fact table.

**How to apply:**
1. **Pre-flight the attribute topology before writing relationships.** After build, for every attribute you expect to be a conformed dimension, GET the attribute and verify its `forms[*].expressions[*].tables` set contains every expected table id. If a table is missing, PATCH the attribute to add the expression (the clone-and-remap pattern from `reference_mosaic_clone_pattern.md`) BEFORE attempting to wire a relationship through that table.
2. **Only declare relationships between attributes that DO NOT already share a table via their own expressions.** If Tenant spans TENANTS + USAGE_HOURLY via expressions, you do NOT need a relationship between them — the join is implicit via the shared attribute. Skip those rows in the dictionary; keep relationship rows only for genuinely different attributes (e.g., Tenant → Primary Impacted Tenant).
3. **When two columns are semantically the same FK but named differently (e.g., `primary_impacted_tenant_id` vs `tenant_id`), decide up front: merge into one attribute (add the second column as another expression of Tenant) OR keep separate and wire a relationship.** Do not do both.
4. **Dictionary `relationships[]` is for `parent.child` relationships — NOT for conformance.** Conformance is expressed by repeating the same attribute `name` across multiple `attributes` entries so the build scripts see them as a single logical attribute and emits a multi-table expression. Relationships are for semantically-distinct attributes that need a join path.
5. **Canonical fix recipe (end-to-end) for any multi-DB, mixed-case Mosaic build:**
   - Step 1: normalize the logical-attribute plan on paper — one row per (logical name) → (list of table.column expressions). Write it down before calling `build`.
   - Step 2: in the dictionary, use identical `name` across every `TABLE.COLUMN` entry that should collapse into one attribute. The build script groups by `name`, not by column name.
   - Step 3: after build, GET every conformed attribute and verify expressions include all expected tables. If missing, PATCH (single changeset) to add expressions — this is the `attribute-merge` pattern.
   - Step 4: only THEN issue relationship PUTs, and only for attribute pairs that have at least one shared table between their expressions. Use that shared table as `relationship_table`.
   - Step 5: validate via a Trino smoke query that groups by each attribute and shows non-null metric values across tables — a disconnected model returns one side nulled.

**Helper-script gap (known):** `build` does not yet support a `--conformance-map` flag that accepts `logical_name: [table.col, table.col, …]` entries. Today's workaround is to write identical `name` values in the dictionary attributes block; confirm in memory that this is the intended grouping mechanism.

**Missing also:** no `wire-relationships` subcommand that takes post-hoc FK hints and issues the relationship changeset intelligently (skipping self-refs, validating shared-table prerequisite). When added, this memory should be updated to point at it instead of hand-rolling PUTs.
