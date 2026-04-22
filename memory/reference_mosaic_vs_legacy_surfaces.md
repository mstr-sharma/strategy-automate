---
name: Mosaic vs Legacy surface delineation (must-read before any write)
description: Hard rule — do not mix Mosaic data-model endpoints with legacy Intelligent Cube / classic project endpoints. Every Strategy write must be routed to the correct surface before any call is made. Lists the one-to-one endpoint pairs that look similar but are not interchangeable.
type: feedback
---

**Why this exists.** On 2026-04-22 the agent built a Mosaic data model in in-memory mode, then tried to publish the cube via `/api/cubes/{id}` and `/api/cubes/{id}?cubeAction=publish` (legacy Intelligent Cube endpoints). The cube returned `HTTP 202` but the model never became visible to Trino federation — because the Mosaic-native publish lives at `/api/dataModels/{dataModelId}/publish`, not under `/api/cubes`. The helper `build_mosaic.py publish` currently probes a mix of legacy + Mosaic paths (`/api/cubes/{id}`, `/api/model/dataModels/{id}/publish`, `/api/model/dataModels/{id}/import`, `/api/cubes/{id}/publish`) and stops at the first 2xx. A 2xx on a *legacy* path is not the same outcome as a 2xx on a Mosaic path. The user caught this and flagged: *"There needs to be clear delineation between legacy and Mosaic. This is a core part of these skills and memories."*

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

## Implication for `build_mosaic.py publish`

The current helper tries `/api/cubes/{id}` first, accepts `202`, and reports "published" — which is what misled the agent on 2026-04-22. The helper must be fixed to:
- Detect subType first (`GET /api/objects/{id}?type=3`).
- If subType is 779 (Mosaic), use the 3-step Mosaic publish flow below and poll `GET /api/dataModels/{id}/publishStatus` until every table reports `status:"loaded"` (top-level `status==0`) before returning success.
- Only fall through to `/api/cubes/...` if subType is 776 (classic cube).
- Never treat a legacy 2xx as evidence a Mosaic model is queryable.

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
