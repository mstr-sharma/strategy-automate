---
name: Studio tenant Mosaic publish stall is still active 2026-04-23
description: Re-confirmed on 2026-04-23 — in-memory Mosaic publish on studio.strategy.com still returns `iServerCode -2147212544` (QueryEngineServer parallel-mode stall) for arbitrary models. This is an IServer health issue, not a per-model bug. Plan every build accordingly.
type: feedback
---

**2026-04-23 afternoon update — dataType shape was a co-cause.** A REF model built via the Studio UI on the exact same 4 tables (Neon incidents + tenant_service_hourly, WACSE TENANTS + USAGE_HOURLY) publishes successfully on this tenant. Cloning REF's physical-table dataTypes (`utf8_char(32000,0)`, `integer(4,0)`, `double(P,S)`, `int64(8,0)`, `time_stamp(26,6)`) into a new model also publishes. So the stall signature below is triggered AT LEAST as much by warehouse-catalog dataType sentinels (`variable_length_string` precision=-1, `decimal` scale=-MIN_INT, `binary` / `unsigned`) as by tenant health. When publish stalls with `-2147212544` going forward, check the "DataType preconditions" section of `memory/reference_mosaic_publish_path.md` before concluding the tenant is broken.

**Original finding (still useful — the pre-clean-types reproduction).** Built `Tenant GPU Analysis-<TS>` (model id `<mosaic-model-id-1>`) in-memory with 4 tables across Neon Postgres + WACSE Snowflake. The 3-step Mosaic publish flow (`POST /api/dataModels/{id}/instances` → `POST /api/dataModels/{id}/publish` with per-table `refreshPolicy:"replace"` → poll `publishStatus`) reliably returned:

```
top_status = -2147467259 (first attempt) or -2147212544 (second)
tables: all "error"
"(QueryEngine encountered error: Parallel mode report execution has stalled before report is finished.
 Canceling report.. Error in Process method of Component: QueryEngineServer,
 Project Shared Studio, Job <N>, Error Code= -2147212544.)"
```

Same signature as 2026-04-22. Retrying does not help; this is the tenant-level failure recorded in `captures/2026-04-22-queryengine-publish-incident/README.md`.

**How to apply:**
1. Before building in-memory on studio.strategy.com, run a canary publish on a known-good small model. If it stalls with `-2147212544`, do not begin a new in-memory build — the whole tenant's publish path is down.
2. If multi-DB so connect_live is unavailable, choose ONE of:
   - Validate via direct warehouse SQL (Neon + Snowflake) rather than against the published model, and mark "data validation: pending — tenant publish stall".
   - Split into per-DB models that can run connect_live and are immediately queryable.
3. The helper's `publish` subcommand still falls through to `/api/cubes/{id}` and reports "published" — that is a lie on a Mosaic model (subtype 779). Do not trust it without polling `/api/dataModels/{id}/publishStatus` with the instance header.
4. Surface the tenant health issue to the admin; keep a standing note in the session output.

**Verified sequence for diagnostic purposes (2026-04-23):**
```
POST /api/dataModels/{id}/instances  -> 204, X-MSTR-DataModelInstanceId: <inst>
POST /api/dataModels/{id}/publish  body={tables:[{id,refreshPolicy:"replace"}, …]}  -> 204
GET  /api/dataModels/{id}/publishStatus  header X-MSTR-DataModelInstanceId:<inst>
     -> 500 iServerCode -2147212544 repeatedly
```

The instance gets reaped within a few minutes; after that the status endpoint returns `404 ERR004 "Message not found in user history list"`, which is unrelated noise — not a new bug.
