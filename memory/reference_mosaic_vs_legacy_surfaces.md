---
name: Mosaic vs Legacy surface delineation (must-read before any write)
description: Hard rule — do not mix Mosaic data-model endpoints with legacy Intelligent Cube / classic project endpoints. Every Strategy write must be routed to the correct surface before any call is made. Lists the one-to-one endpoint pairs that look similar but are not interchangeable.
type: feedback
---

**Why this exists.** This memory's core value is the **object-classification rule** (779 Mosaic data model vs 776 classic Intelligent Cube) and the table of endpoint pairs that LOOK interchangeable but aren't. Read it before any publish/refresh/execute/ACL/security-filter write so you pick the right URL prefix for the object family.

**Note on the publish endpoint (2026-04-23 correction).** An earlier version of this memory said `/api/cubes/{id}?cubeAction=publish` "is NOT the publish path for a Mosaic data model" — that was half wrong. On Strategy ONE Cloud tenants the Studio UI's Publish button routes through `POST /api/cubes/{modelId}?cubeAction=publish` (HTTP 202) for Mosaic models (subtype 779) AND it's the reliable trigger path. See `reference_mosaic_publish_path.md` for the verified flow and trade-offs between that endpoint and the Modeling-native 3-step `/api/dataModels/{id}/instances` → `/publish` → `/publishStatus` flow. Publishability also depends on the physical-table `dataType` shape — see `feedback_mosaic_publishable_datatypes.md`. Either publish path silently no-ops if the columns carry warehouse-catalog sentinels (`variable_length_string` precision=-1, `decimal` scale=-MIN_INT, etc.). Behavior may differ on other iServer build families — re-verify before asserting the rule.

The original incident (2026-04-22) still matters: a 2xx on `/api/cubes` does not guarantee materialization — always poll `publishStatus` or confirm via Trino `get_mosaic_models`/`query` before declaring success.

**Rule: before any write, classify the object.**
1. Mosaic data model (subType 779 / `report_emma_cube`, owned by the Modeling Service)
2. Legacy Intelligent Cube (subType 776 via the classic cube server)
3. Classic project object (attribute/metric/report/filter in the legacy semantic layer)
4. AI agent / Auto agent (separate surface)

Never call a legacy endpoint on a Mosaic object, or a Mosaic endpoint on a legacy object, even if the id would happen to resolve on both. The responses are *different behaviors*, not interchangeable aliases.

## The pairs that most often get confused

| Intent | Mosaic (use this for a Mosaic data model) | Legacy (use this for a classic Intelligent Cube or classic cube) | Notes |
|---|---|---|---|
| Publish / materialize | `POST /api/dataModels/{modelId}/publish` | `POST /api/cubes/{id}?cubeAction=publish` or `/api/cubes/{id}` | Mosaic endpoint lives under `/api/dataModels` (**top-level**, not `/api/model/dataModels`). Legacy endpoints return 2xx but do NOT make a Mosaic model visible to Trino/federation. |
| Publish status | `GET /api/dataModels/{modelId}/publishStatus` | `GET /api/cubes/{id}/status` | The Mosaic status is the source of truth for "is this queryable yet." |
| Execute / get data | `POST /api/dataModels/{modelId}/instances` (data-model instance API) | `POST /api/cubes/{id}/instances` (cube execution) | Both return instance IDs but the data-model API respects Mosaic metrics/attrs; the cube API treats the object as a flat cube. |
| Create / edit metadata | `POST/PATCH /api/model/dataModels/...` (Modeling Service, changeset-scoped) | No direct equivalent for classic schema — classic schema edits go through `mstrio-py` or Workstation, not REST | Modeling Service = Mosaic only. Do not attempt classic schema edits via `/api/model/...`. |
| Security filter (create) | `POST /api/model/dataModels/{modelId}/securityFilters` under changeset | `POST /api/securityFilters` (project-level classic SF) | Different shape, different member-assignment path. |
| Security filter (assign members) | `PATCH /api/dataModels/{modelId}/securityFilters/{sfId}/members` | `PATCH /api/securityFilters/{sfId}/members` | Mosaic uses `/Members` PascalCase + `addElements`; classic uses `/members` lowercase — see `reference_mosaic_security_filter.md`. |
| Serve mode change | `PATCH /api/model/dataModels/{modelId}` body `{"dataServeMode":"in_memory|connect_live|hybrid"}` inside a changeset | No equivalent — classic cube has no serve-mode concept | After changing to `in_memory`, the model is *unpublished* until a Mosaic publish completes. |
| Relationships | `PUT /api/model/dataModels/{modelId}/attributes/{childId}/relationships` inside a changeset | Classic relationships live on project schema objects; different endpoints | See `reference_mosaic_rest_gotchas.md`. |
| ACL | `/api/model/dataModels/.../objects/{oid}/acl` (Modeling) OR `/api/objects/{oid}?type=...&showACL=true` (cross-tenant) | `/api/securityPermissions/...` or classic `/api/objects/{oid}/acl` depending on object type | See `reference_mosaic_acl.md`. |

## Two asymmetries that keep tripping automation

1. **Mosaic modeling writes** use `/api/model/dataModels/...` (prefix `model/`).
   **Mosaic runtime reads/writes** (publish, publishStatus, instances, securityFilter member assignment) use `/api/dataModels/...` (no `model/`).
   If you see 404 on a path that exists in both shapes, try flipping the `model/` prefix.

2. **`/api/cubes/...` is almost never the right surface for a Mosaic data model.** Exception: the user explicitly wants Intelligent Cube semantics (cache/hit/status), and the object is truly a classic cube. If in doubt, read `GET /api/objects/{id}?type=3` → `subtype`. `subtype:779` → Mosaic data model → do not use `/api/cubes/*`.

## Implication for `build_mosaic.py publish` (updated 2026-04-23)

The helper's current `/api/cubes/{id}` fallback is actually correct for Mosaic on Strategy ONE Cloud tenants — the UI uses the same path. What's missing is a **post-202 confirmation step**. Required fix:
- Detect subType first (`GET /api/objects/{id}?type=3`).
- If subType is 779 (Mosaic): call `POST /api/cubes/{id}?cubeAction=publish`, then confirm completion by either (a) polling the 3-step Modeling flow (`/api/dataModels/{id}/instances` + `/publish` + `/publishStatus`) until every table is `loaded`, or (b) a smoke query via MCP `query` / Trino. Do not declare success on the 202 alone.
- If subType is 776 (classic cube): use `/api/cubes/*` directly (no data-model instance needed).
- Before publishing a Mosaic in-memory model, sanity-check the physical-table column dataTypes per `feedback_mosaic_publishable_datatypes.md` — warehouse-catalog types cause silent no-ops on either endpoint.

Track this in the gap register (`reference_strategy_automation_coverage.md`) — helper currently at "captured fallback" quality for publish, not "wrapped helper".

## Verified 3-step Mosaic publish flow (2026-04-22)

```
# 1. Create a data-model instance. 204 with the ID returned in a response HEADER (not body).
POST /api/dataModels/{modelId}/instances
-> HTTP 204
-> response header:  X-MSTR-DataModelInstanceId: <instanceId>

# 2. Trigger publish with the instance header AND a JSON body describing per-table refresh policy.
POST /api/dataModels/{modelId}/publish
headers: X-MSTR-DataModelInstanceId: <instanceId>
body:
{
  "tables": [
    {"id": "<logicalTableId>", "refreshPolicy": "replace"},
    ...
  ]
}
-> HTTP 204 (fire-and-forget; no body)

# 3. Poll status until every table is loaded.
GET /api/dataModels/{modelId}/publishStatus
headers: X-MSTR-DataModelInstanceId: <instanceId>
-> 200 { "status": <int>, "tables": [ {"id": "...", "status": "reserved|schema_comparison_completed|loaded|error", ...} ] }
```

Gotchas:
- **The instance id ONLY comes in the `X-MSTR-DataModelInstanceId` response header.** The 204 has no body — `r.json()` will throw.
- **`publish` without the `tables[]` body returns 500 `Bad Request`.** The OpenAPI spec lists `requestBody` as required; empty `{}` is not enough. Enumerate every logical table id from `GET /api/model/dataModels/{id}/tables` and send `refreshPolicy: "replace"` for a full rebuild (other values: `add`, `delete`, `update`, `upsert`, `ignore`, `reserved`).
- **Top-level status codes seen:** `5` = reserved/starting, `6` = schema-compared, `-2147212544` = QueryEngineServer parallel-mode stall (tenant-side, see below), `0` = success (all tables loaded).
- **Per-table `status` strings:** `reserved` → `schema_comparison_completed` → `loaded` on the happy path; `error` terminates.
- **The legacy `/api/cubes/{id}?cubeAction=publish` returns 202 but the Mosaic model stays unpublished** — this is the regression we spent a round on.

## Tenant-level failure mode observed on Strategy ONE Shared Studio (2026-04-22)

Publishing ANY Mosaic model in-memory on the Studio tenant — including a pre-existing, unrelated 6-table model (`OC Test`) — returned the same QueryEngineServer stall:

```
(QueryEngine encountered error: Parallel mode report execution has stalled before report is finished.
 Canceling report.. Error in Process method of Component: QueryEngineServer,
 Project Shared Studio, Job <N>, Error Code= -2147212544.)
```

Symptoms:
- `publish` returns 204 and tables briefly show `schema_comparison_completed`.
- Status then flips to top-level `-2147212544` with every table `status:"error"`.
- Reproducible across distinct models, user sessions, and clean server-side instance IDs.

Conclusion: this is an Intelligence Server / QueryEngineServer health issue at the tenant level, NOT a per-model metric-shape bug. When this signature appears:
1. Confirm tenant-wide by publishing a known-good in-memory model.
2. Fall back to `connect_live` serve mode (PATCH `dataServeMode`) so Trino federation sees the model immediately — no cube materialization needed. Validation still works; you just lose the in-memory performance benefit.
3. Surface the tenant issue to the admin; do NOT keep retrying publish in a loop.

Do not silently retry the legacy `/api/cubes/...` path as a "works around the regression" — it 2xxs but leaves the model unpublished, which is exactly the confusion that spawned this memory.

## Decision template to apply before every Strategy call

Ask two questions:

> **Q1. Is the target a Mosaic data model, a classic cube, a classic project object, or an agent?**
> **Q2. Am I reading metadata (Modeling Service), writing metadata (Modeling Service), running the model, or administering it (project admin / security)?**

The answers pick the URL prefix (`/api/model/dataModels/...` vs `/api/dataModels/...` vs `/api/cubes/...` vs `/api/objects/...` vs `/api/securityFilters/...`). Write down the classification in the task output (even one line: *"Mosaic data model (779), runtime publish"*) so follow-up steps stay on the right surface.
