---
name: Mosaic relationship wiring — pre-flight, post-build verify, fix-forward
description: End-to-end recipe for getting Mosaic attribute relationships correct on multi-DB / mixed-case builds. Combines the conformance pre-flight, the dictionary grouping rule, the post-build attribute-expression check, and the relationship PUT contract so that a fresh operator can get a joined model on the first try instead of repeating the "build returns 2xx but model shows disconnected star fragments" failure.
type: feedback
---

**Rule:** a shippable multi-source Mosaic model must have every cross-table query path either (a) carried by a conformed attribute with expressions on every participating table OR (b) wired by an explicit relationship whose `relationship_table` appears in BOTH parent and child attribute expressions. Nothing else joins.

**Why:** on every multi-DB, mixed-case warehouse build so far (Neon Postgres lowercase + Snowflake uppercase is the canonical case), `build_mosaic.py`'s auto-conformance silently merges some columns, orphans others, and leaves a third class (semantically-same but differently-named FKs) as standalone attributes with no path back. Issuing relationship PUTs blindly then fails with `8004ccdb` / `8004ccc7`, and operators waste the session-cap budget retrying. This memory consolidates the recipe across `feedback_build_mosaic_conforming_attr_rules.md`, `reference_mosaic_relationship_archetypes.md`, and `reference_mosaic_clone_pattern.md` so you don't re-derive it per build.

**How to apply — six-step recipe:**

1. **Write the logical-attribute plan on paper BEFORE `build`.** For every physical column, decide: (i) it becomes a conformed dimension attribute spanning N tables, or (ii) it stays table-scoped, or (iii) it's metric fodder. Record it as a map:
   ```
   Tenant         ← TENANTS.TENANT_ID, USAGE_HOURLY.TENANT_ID, tenant_service_hourly.tenant_id, incidents.primary_impacted_tenant_id
   Cluster        ← incidents.cluster_id, tenant_service_hourly.cluster_id, USAGE_HOURLY.CLUSTER_ID
   Service Timestamp ← tenant_service_hourly.service_ts, USAGE_HOURLY.USAGE_TS
   ```
   This plan is the single source of truth for the dictionary.

2. **Express conformance in the dictionary via identical `name`.** The build script groups `attributes[table.col]` entries by their `name` field, not by column name. So to conform `primary_impacted_tenant_id` and `tenant_id` into one "Tenant" attribute:
   ```json
   "attributes": {
     "TENANTS.TENANT_ID":                      {"name": "Tenant", "description": "…"},
     "USAGE_HOURLY.TENANT_ID":                 {"name": "Tenant"},
     "tenant_service_hourly.tenant_id":        {"name": "Tenant"},
     "incidents.primary_impacted_tenant_id":   {"name": "Tenant"}
   }
   ```
   The auto-conformance pass collapses these into a single multi-table attribute regardless of case or column-name mismatch. The case-sensitive inference only fires when the dictionary does NOT cover the column.

3. **Declare ONLY the relationships you cannot express via conformance.** Shared-attribute joins happen for free. The dictionary `relationships[]` block is for genuinely different attributes joined through a fact table (e.g., `Incident → Tenant` through `incidents` when Incident is not a tenant-keyed attribute). Never list a relationship where both parent and child resolve to the same logical attribute name — Mosaic rejects it as `8004ccdb` "appears more than once".

4. **After `build` returns, immediately GET every conformed attribute and verify `forms[*].expressions[*].tables` covers every expected table.** A missing table means auto-conformance dropped the case-mismatched variant despite the dictionary. Fix with a single PATCH changeset that adds the missing expression (clone-and-remap pattern). Do this BEFORE any relationship PUTs.

5. **For each relationship, verify the `relationship_table` prerequisite: the parent attribute must have an expression on that table AND the child attribute must have an expression on that table.** If either is missing, the `8004ccc7` "Table cannot be used as the join table" fires. Add the missing expression first (same PATCH pattern), then issue the relationship.

6. **Validate with a Trino rollup query AT THE ATTRIBUTE GRAIN you expect users to query.** `SELECT "tenant", SUM("jobs_completed") FROM "<project>"."<model_name>" GROUP BY 1` on a model with a broken tenant conformance will either return one row (all aggregated) or error; a correctly-conformed model returns one row per tenant. If the number of rows is off by a factor of 2–N, conformance is wrong.

**Common failure modes this recipe catches:**
- *"Model has no joins"* — step 4 check fails; add missing expressions.
- *"Relationship PUT returns 8004ccdb"* — step 3 violation; parent+child already share a logical attribute.
- *"Relationship PUT returns 8004ccc7"* — step 5 violation; pick a different relationship_table or add the missing expression.
- *"Trino query returns zero rows when grouping by two attributes from different tables"* — the joining attribute is not conformed; step 2 was skipped for one of the tables.
- *"Metric values balloon vs source table totals"* — Cartesian product because the conformance path doesn't exist; relationships are serving a Cartesian fallback. Step 4 + step 5 fix this.

**Session-cap corollary:** steps 4 and 5 typically need 2–4 `/api/model/dataModels/{id}/attributes/{aid}` GETs + 1 PATCH each. That's 10–20 project-scoped calls for a 4-table model. Batch them all inside a SINGLE Python process with one login — see `feedback_build_mosaic_session_leak.md` for the session-cap rules. Do not run them as individual `api-call` shell invocations or you will cap the user mid-fix.

**Helper-script gap (known, durable work item):**
- `build_mosaic.py` needs a `wire-relationships` subcommand that: (a) loads a post-hoc FK hint file, (b) GETs every attribute, (c) validates step 3 and step 5 prerequisites, (d) issues only the PUTs that will succeed, (e) reports which ones need attribute merges first. Until that ships, the canonical workaround is a single inline Python block calling the Modeling-Service REST endpoints directly.
- A `--conformance-map` flag on `build` that accepts `logical_name: [table.col, …]` would replace the "identical name in dictionary" trick with an explicit map. Currently unspecified; memory says to use the dictionary-name convention.

Related:
- `feedback_build_mosaic_conforming_attr_rules.md` — case-sensitivity + FK-naming root causes.
- `feedback_build_mosaic_session_leak.md` — session-cap budget and batching rules.
- `reference_mosaic_relationship_archetypes.md` — the 6 canonical join patterns (star, snowflake, bridge, composite-FK, descriptive, date-hierarchy) and which one to pick.
- `reference_mosaic_clone_pattern.md` — the PATCH-with-GET-first procedure for adding a missing expression to an existing attribute.
