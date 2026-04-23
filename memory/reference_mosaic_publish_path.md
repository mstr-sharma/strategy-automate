---
name: Mosaic in-memory publish — verified endpoint sequence on Strategy ONE Cloud
description: Two publish endpoints exist for a Mosaic data model (subType 779) on Strategy ONE Cloud tenants; the UI uses the legacy-named `/api/cubes/{id}?cubeAction=publish` (202). The Modeling-native 3-step flow (`/api/dataModels/{id}/instances` + `/api/dataModels/{id}/publish` + `/publishStatus`) also works — but the 204-on-publish is a fire-and-forget and silently no-ops unless the table payload is well-formed (see also feedback_mosaic_publishable_datatypes.md). Both paths assume the tables carry clean, non-warehouse-catalog dataTypes.
type: reference
---

## Background — a 2026-04-22 memory was half wrong

`reference_mosaic_vs_legacy_surfaces.md` declared "`/api/cubes/*` is NOT the publish path for a Mosaic data model — use `POST /api/dataModels/{id}/publish`." After 2026-04-23, corrected: both paths work for a properly-typed Mosaic model. The real failure mode that memory captured was the dirty dataTypes — not the endpoint choice. Keep that memory for the classification rules (subType 779 vs 776) but read this one for the actual publish trigger. Observations here are from a Strategy ONE Cloud tenant; recheck endpoint choice on different iServer build families.

## What the Studio UI calls when you click "Publish"

Single request:
```
POST /api/cubes/{modelId}?cubeAction=publish
Headers: X-MSTR-AuthToken, X-MSTR-ProjectID
Body: (empty)
-> HTTP 202 Accepted
```

The server queues a CubeServer publish job (visible as `Cube report "<model name>" is being published by job <N>` if you race a second publish). Data lands in the cube within tens of seconds for small models; ~1–2 minutes for 4-table models with 5–50k rows per table.

No instance header is needed. No body is needed. The cube materializes for Trino federation automatically; no follow-up "activate" step.

## The Modeling-native 3-step flow (also works, use for fine-grained refresh)

Use when you need per-table refresh policies (add / replace / delete / update / upsert / ignore / reserved) or when you need the returned instance id for polling.

```
# 1. Create a data-model instance (no body). 204; instance id in RESPONSE HEADER.
POST /api/dataModels/{modelId}/instances
-> 204, X-MSTR-DataModelInstanceId: <inst>

# 2. Trigger publish. Body is REQUIRED (empty or {}) — server returns 400 "tableRefreshSettings cannot be null" otherwise.
POST /api/dataModels/{modelId}/publish
Headers: X-MSTR-DataModelInstanceId: <inst>
Body: {"tables":[{"id":"<tid>","refreshPolicy":"replace"}, ...]}    # one entry per logical table
-> 204 (fire-and-forget)

# 3. Poll status.
GET /api/dataModels/{modelId}/publishStatus
Headers: X-MSTR-DataModelInstanceId: <inst>
-> 200 {"status": <int>, "tables":[{"id","status":"reserved|schema_comparison_completed|loaded|error", ...}]}
```

Top-level statuses observed:
- `0` — all tables loaded (happy end).
- `1` — job queued/running. Tables list may be empty for the first tens of seconds.
- `5` — reserved.
- `6` — schema comparison completed.
- `-2147212544` — CubeServer parallel-mode stall. With REF-clean dataTypes this is rare; with warehouse-catalog types it is the default outcome on the observed Strategy ONE Cloud tenant family.

Per-table statuses: `reserved` → `schema_comparison_completed` → `loaded` (happy), or terminate at `error`.

**Instance id lifetime.** The X-MSTR-DataModelInstanceId expires within a couple minutes; if you see repeated `404 ERR004 "Message not found in user history list"` on `publishStatus`, your instance was reaped — mint a new one and re-publish. A short-lived session (one Python process, keep polling in the same `requests.Session`) rarely trips this; longer polling with multiple login cycles does.

## Which path to use in automation

| Situation | Use |
|---|---|
| "Just publish this model; don't care about refresh policies" | `/api/cubes/{id}?cubeAction=publish` — simplest, matches UI, no instance management. |
| "Publish and confirm every table loaded" | 3-step Modeling flow — only this returns per-table status. |
| "Incremental refresh (add/update specific tables)" | 3-step Modeling flow with specific `refreshPolicy`. |
| "Policy gate before declaring validation ready" | Always poll `/publishStatus` until every table `status:"loaded"`. Don't trust the 202/204 alone. |

## Helper-fix note

`build_mosaic.py publish` currently tries `/api/cubes/{id}` first and accepts the 202 as success — which is correct for Mosaic now that we've verified the UI uses this path. But it does NOT follow up with a publish-status poll. Add a poll via the 3-step instance flow after the 202 (or just wait and query via Trino) before reporting success. Otherwise validation can run before the cube finishes materializing.

## Verified on 2026-04-23 (tenant-family: Strategy ONE Cloud)

- `/api/cubes/{id}?cubeAction=publish` → 202, followed by Trino query success on the materialized model.
- `/api/dataModels/{id}/publish` with per-table bodies → 204, followed by `publishStatus` returning `status=1 tables:[]` while a parallel `/api/cubes` publish completed. Conclusion: the Modeling-native publish accepts the request but queues it in a way the CubeServer may not always drain on this tenant family — the `/api/cubes` path is the reliable one here. Recheck on other iServer build families.

(Raw reproduction, including model IDs and query text, lives under `captures/` on the run date. Link the capture from the follow-up ticket rather than re-embedding IDs here.)
