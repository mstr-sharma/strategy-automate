---
name: Multi-datasource Mosaic models cannot use connect_live
description: Verified 2026-04-23 — Mosaic rejects adding a second DB instance's table to a connect_live model with code 8004d232. Use in_memory (and accept publish risk) or split into per-DB models.
type: feedback
---

**Rule.** When a Mosaic data model needs tables from ≥2 distinct DB instances (e.g., Neon Postgres + Snowflake), `dataServeMode: connect_live` is not viable. Strategy rejects the second-instance table with:

```
HTTP 400 8004d232: "The table change will make connect-live Mosaic model invalid.
Connect-live Mosaic model should meet below conditions:
 1) The data source is a single relational database;
 2) No wrangling operations are performed."
```

**Why:** Connect-live pushes SQL straight to one warehouse; it has no federation plane.

**How to apply:**
- If the source list spans multiple `databaseInstance.objectId`s, default to `dataServeMode: in_memory` (Mosaic will materialize a cube).
- In-memory publish can stall with `iServerCode -2147212544` (CubeServer parallel-mode stall) on Strategy ONE Cloud tenants when physical-table `dataType` values carry warehouse-catalog sentinels; see `reference_mosaic_publish_path.md` ("DataType preconditions") for the fix (use UI-verified dataType shapes). When a tenant is genuinely stalled across all models, plan for a validation fallback that does not depend on the published Mosaic model. Raw reproduction transcripts live under `captures/<date>-studio-publish-stall/` when captured.
- If the tenant publish path is broken, consider building one Mosaic model per DB instance and joining downstream (e.g., via a separate federated model or a classic report).
- `build_mosaic.py` does not warn on this at pre-flight. Add a check: if the resolved `--source` list has ≥2 distinct dbInstanceIds and `--data-serve-mode connect_live` was requested, fail fast with this message.
