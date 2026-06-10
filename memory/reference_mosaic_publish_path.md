---
name: Mosaic in-memory publish — endpoints, single-trigger rule, and dataType preconditions
description: The ONE publish file for Mosaic data models (subType 779). Two publish endpoints exist on Strategy ONE Cloud tenants — the UI's `/api/cubes/{id}?cubeAction=publish` (202) and the Modeling-native 3-step `/api/dataModels/{id}/instances` + `/publish` + `/publishStatus` flow. Pick exactly ONE per run (firing both locks `publishStatus` into 500 iServerCode -2147072194). Either path silently no-ops or stalls (-2147212544) unless physical-table dataTypes are clean pipeline types, not warehouse-catalog sentinels. Load before any Mosaic publish/refresh.
type: reference
---

## Background — a 2026-04-22 memory was half wrong

`reference_mosaic_vs_legacy_surfaces.md` declared "`/api/cubes/*` is NOT the publish path for a Mosaic data model — use `POST /api/dataModels/{id}/publish`." After 2026-04-23, corrected: both paths work for a properly-typed Mosaic model. The real failure mode that memory captured was the dirty dataTypes — not the endpoint choice (see "DataType preconditions" below). Keep that memory for the classification rules (subType 779 vs 776) and the endpoint-pair cheat sheet; read this one for the actual publish trigger. Observations here are from a Strategy ONE Cloud tenant; recheck endpoint choice on different iServer build families.

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
- `-2147212544` — CubeServer parallel-mode stall. With REF-clean dataTypes this is rare; with warehouse-catalog types it is the default outcome on the observed Strategy ONE Cloud tenant family (see "DataType preconditions" below).

Per-table statuses: `reserved` → `schema_comparison_completed` → `loaded` (happy), or terminate at `error`.

**Instance id lifetime.** The X-MSTR-DataModelInstanceId expires within a couple minutes; if you see repeated `404 ERR004 "Message not found in user history list"` on `publishStatus`, your instance was reaped — mint a new one and re-publish. A short-lived session (one Python process, keep polling in the same `requests.Session`) rarely trips this; longer polling with multiple login cycles does.

## Which path to use in automation

| Situation | Use |
|---|---|
| "Just publish this model; don't care about refresh policies" | `/api/cubes/{id}?cubeAction=publish` — simplest, matches UI, no instance management. |
| "Publish and confirm every table loaded" | 3-step Modeling flow — only this returns per-table status. |
| "Incremental refresh (add/update specific tables)" | 3-step Modeling flow with specific `refreshPolicy`. |
| "Policy gate before declaring validation ready" | Always poll `/publishStatus` until every table `status:"loaded"`. Don't trust the 202/204 alone. |

## Never fire both publish endpoints in the same run

When publishing an in-memory Mosaic data model, call **exactly one** of the two publish endpoints per run:

- `POST /api/cubes/{id}?cubeAction=publish` — UI-equivalent, returns 202 immediately, no instance needed. Poll by Trino probe or `GET /api/cubes/{id}`.
- `POST /api/dataModels/{id}/instances` + `POST /api/dataModels/{id}/publish` + `GET /api/dataModels/{id}/publishStatus` — three-step, uses instance id, only this returns per-table status.

Do NOT issue both. If you fire `/api/cubes` first and then follow up with the 3-step `publish` POST, Strategy sees two publish jobs racing on the same cube. The CubeServer serializes them (accepts the first, queues/rejects the second), and `publishStatus` against the LOSING instance id returns `500 ERR001 iServerCode -2147072194` "is being published by job N" for the full duration of the winning job. Your polling loop sees the error continuously, times out, and reports failure — even though the cube is actually being published successfully.

### Observed

Strategy ONE Cloud tenant, multi-DB in-memory model (captured run):
- `/api/cubes/{id}?cubeAction=publish` → 202 (started publish job N).
- `/api/dataModels/{id}/publish` fired 200ms later → 204 (second publish, queued/blocked).
- `GET /api/dataModels/{id}/publishStatus` with the 3-step instance id → **21 consecutive 500 responses over ~5 minutes**, all `iServerCode: -2147072194` "Cube report … is being published by job N". The script never saw a green status.
- User checked the Library UI: publish had completed **in seconds**. MCP Trino query confirmed the cube had materialized its expected row count.

### Fix pattern — single trigger + MCP/Trino count(*) completion probe

```python
# Single-trigger, Trino-probe publish
r = s.post(f"{BASE}/api/cubes/{MID}?cubeAction=publish")
assert r.status_code == 202

# Poll by checking the Trino/MCP catalog, not by 3-step status
deadline = time.time() + 600
while time.time() < deadline:
    time.sleep(15)
    probe = s.post(f"{MCP_BASE}/query",
                   json={"schema": PROJECT_NAME.lower(),
                         "query": f'SELECT count(*) FROM "{model_name.lower()}"'})
    if probe.ok and "count" in probe.json(): break
```

Or, if you need per-table status (incremental refresh / schema drift detection), use ONLY the 3-step flow — do NOT combine it with `/api/cubes`.

### Why this tripped a real run

The script was defensive — it tried both paths to be robust against either one failing. In this tenant family BOTH paths succeed, but they serialize on the cube lock, and the losing instance's `publishStatus` call is the one the script polled. Net effect: a working publish looked like an infinite stall.

**Don't confuse the two iServerCodes:** `-2147212544` = real stall (bad dataTypes — next section); `-2147072194` = job-in-progress lockout (you fired both endpoints).

## DataType preconditions — clean pipeline types, not warehouse-catalog types

Confirmed 2026-04-23 on a Strategy ONE Cloud tenant: when the publishable columns carry warehouse-catalog sentinels (precision=-1 or scale=-2147483648, `variable_length_string`, `fixed_length_string`, `binary`, `unsigned`, `decimal` with warehouse precision), the Mosaic in-memory publish accepts the request but the cube never materializes (status=1 with empty tables, or -2147212544 stall). A reference model built by the UI wizard shows normalized types (`utf8_char(32000,0)`, `integer(4,0)`, `integer(2,0)`, `double(P,S)`, `int64(8,0)`, `date(10,0)`, `time_stamp(26,6)` or `(23,9)`) — cloning those dataTypes into an otherwise-identical model fixes publish end-to-end. Recheck on other iServer build families before asserting this as universal.

### What happens if you skip this

`build_mosaic.py build` reads warehouse column metadata via `/api/datasources/{id}/catalog/tables/{tid}` and forwards those `dataType` objects verbatim into the new physical table's `physicalTable.columns[]` and pipeline. Two symptoms follow:

1. The helper's `publish` subcommand and the Mosaic 3-step flow return 2xx and then either:
   - `status=1` with `tables:[]` forever (nothing happens — IServer silently no-ops), or
   - `-2147212544` QueryEngine parallel-mode stall that the 2026-04-22 memory attributed to the tenant. We now know at least part of that stall was the dataType shape, not tenant health — a REF model built the same day with clean types publishes fine.
2. The UI's "Publish" button, which routes through `POST /api/cubes/{modelId}?cubeAction=publish` (202 Accepted), also works on these clean-typed models. On dirty-typed models the UI still hits `/api/cubes` but the resulting job errors inside the CubeServer component.

### Canonical dataType mapping (warehouse → Mosaic in-memory)

Apply this when building a physical table to publish. Source values come from `/api/datasources/{id}/catalog/tables/{tid}`; target values are what the UI-created reference model (REF) used.

| Source `type` | Source shape | → Target `type` | Target precision | Target scale |
|---|---|---|---|---|
| `variable_length_string` | precision=-1, scale=-MIN_INT | `utf8_char` | 32000 | 0 |
| `fixed_length_string` | precision=any, scale=-MIN_INT | `utf8_char` | 32000 | 0 |
| `integer` | precision=4, scale=-MIN_INT | `integer` | 4 | 0 |
| `binary` | precision=1, scale=-1 | `integer` | 2 | 0 |
| `unsigned` | precision=1, scale=-MIN_INT | `integer` | 2 | 0 |
| `decimal` | precision=P, scale=0 | `int64` | 8 | 0 |
| `decimal` | precision=P, scale=S (S>0) | `double` | P | S |
| `time_stamp` | precision=8 | `time_stamp` | 26 | 6 |
| `time_stamp` | precision=9 | `time_stamp` | 23 | 9 |
| `date` | precision=0, scale=-MIN_INT | `date` | 10 | 0 |

`-MIN_INT` above = `-2147483648` (Java `Integer.MIN_VALUE`, meaning "not set" in the warehouse catalog payload).

### Where the dataType lives

Two places must stay in sync on every table:

1. `physicalTable.columns[i].dataType` — the public column definition.
2. `physicalTable.pipeline` (JSON string) — the pipeline spec has its own `rootTable.children[*].columns[*].dataType` AND `sourceDataType`. Both need the cleaned type.

Aligning them by column name is the safe pattern — before POSTing the table, walk the pipeline, ensure the `id` of each pipeline column matches `physicalTable.columns[i].information.objectId`, and ensure both `dataType` and `sourceDataType` carry the target shape.

### The clean-types-via-clone pattern

The fastest way to fix an already-built dirty-typed model is to clone a known-good reference:

1. Fetch REF model via `GET /api/model/dataModels/{refId}?showExpressionAs=tokens`, then for each table `GET /api/model/dataModels/{refId}/tables/{tid}?showColumns=true`.
2. Deep-copy each table body; strip `information.objectId`/`information.dateCreated` and the pipeline's `id`/`rootTable.id`/`children[*].id`/`columns[*].id` — mint fresh UUIDs. Keep column NAMES identical so `physicalTable.columns` and the pipeline's column list still zip by name.
3. Keep every `dataType`/`sourceDataType` from REF unchanged — this is the whole point.
4. POST each rebuilt table to the new model inside a changeset.
5. Clone attributes and fact metrics too, using text-only `column_reference` tokens (`{"type":"column_reference","value":"COL_NAME"}` — no `target.objectId`) so Mosaic re-binds to the new column ids by name on commit. Do NOT carry REF's `expressionId`/`target.objectId` values — those will collide.
6. Commit tables + attributes + metrics in ONE changeset. The "table has no attribute/metric" commit check (`8004e42f`) requires at least one attribute or metric per table to be created before commit.
7. Follow up with a second changeset for relationships and a third for security filters.

## Helper-fix note

`build_mosaic.py publish` currently tries `/api/cubes/{id}` first and accepts the 202 as success — which is correct for Mosaic now that we've verified the UI uses this path. But it does NOT follow up with a publish-status poll. Add a poll via the 3-step instance flow after the 202 (or just wait and query via Trino) before reporting success. Otherwise validation can run before the cube finishes materializing. (Do not let the helper fire BOTH triggers — see the single-trigger rule above.)

## Verified on 2026-04-23 (tenant-family: Strategy ONE Cloud)

- `/api/cubes/{id}?cubeAction=publish` → 202, followed by Trino query success on the materialized model.
- `/api/dataModels/{id}/publish` with per-table bodies → 204, followed by `publishStatus` returning `status=1 tables:[]` while a parallel `/api/cubes` publish completed. Conclusion: the Modeling-native publish accepts the request but queues it in a way the CubeServer may not always drain on this tenant family — the `/api/cubes` path is the reliable one here. Recheck on other iServer build families.

(Raw reproduction, including model IDs and query text, lives under `captures/` on the run date. Link the capture from the follow-up ticket rather than re-embedding IDs here. The 2026-04-22 tenant-level QueryEngineServer stall narrative lives in `captures/2026-04-22-queryengine-publish-incident/README.md`.)
