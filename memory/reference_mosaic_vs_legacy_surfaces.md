---
name: Mosaic vs Legacy surface delineation (must-read before any write)
description: Hard rule — do not mix Mosaic data-model endpoints with legacy Intelligent Cube / classic project endpoints. Classify every target by subType (779 Mosaic / 776 classic cube / else stop) before any call, then use the endpoint-pair cheat sheet to pick the right URL prefix.
type: feedback
---

**Why this exists.** This memory's core value is the **object-classification rule** (779 Mosaic data model vs 776 classic Intelligent Cube) and the table of endpoint pairs that LOOK interchangeable but aren't. Read it before any publish/refresh/execute/ACL/security-filter write so you pick the right URL prefix for the object family. For everything publish-specific — trigger endpoints, the single-trigger rule, dataType preconditions, polling — `reference_mosaic_publish_path.md` is the one publish file; for noun→surface routing beyond these pairs (security filters, ACLs, cubes, datasets, agents), `reference_strategy_surface_matrix.md` wins.

**Rule: before any write, classify the object.**

Read `GET /api/objects/{id}?type=3` → `subtype`:

1. `779` (`report_emma_cube`) → Mosaic data model, owned by the Modeling Service.
2. `776` → Legacy Intelligent Cube via the classic cube server.
3. Anything else → stop and classify further: classic project object (attribute/metric/report/filter in the legacy semantic layer) or AI agent / Auto agent (separate surface).

Never call a legacy endpoint on a Mosaic object, or a Mosaic endpoint on a legacy object, even if the id would happen to resolve on both. The responses are *different behaviors*, not interchangeable aliases. Calling a Mosaic-only endpoint (`/api/model/dataModels/*`) on a non-779 object fails with `8004e457` — "Given object is not a Mosaic model" — which is the classification rule above telling you it was skipped.

## The pairs that most often get confused

| Intent | Mosaic (use this for a Mosaic data model) | Legacy (use this for a classic Intelligent Cube or classic cube) | Notes |
|---|---|---|---|
| Publish / materialize | `POST /api/dataModels/{modelId}/publish` (3-step, per-table status) — but on Strategy ONE Cloud the UI-verified trigger for subType 779 is `POST /api/cubes/{modelId}?cubeAction=publish` (202); see `reference_mosaic_publish_path.md` | `POST /api/cubes/{id}?cubeAction=publish` or `/api/cubes/{id}` | 2026-04-23 correction: an earlier version of this row said `/api/cubes/*` is never the Mosaic publish path — half wrong; both work on a properly-typed model. Pick ONE trigger per run and never trust the 2xx alone — poll `publishStatus` or Trino-probe before declaring success. Mosaic endpoint lives under `/api/dataModels` (**top-level**, not `/api/model/dataModels`). |
| Publish status | `GET /api/dataModels/{modelId}/publishStatus` | `GET /api/cubes/{id}/status` | The Mosaic status is the source of truth for "is this queryable yet." |
| Execute / get data | `POST /api/dataModels/{modelId}/instances` (data-model instance API) | `POST /api/cubes/{id}/instances` (cube execution) | Both return instance IDs but the data-model API respects Mosaic metrics/attrs; the cube API treats the object as a flat cube. |
| Create / edit metadata | `POST/PATCH /api/model/dataModels/...` (Modeling Service, changeset-scoped) | No direct equivalent for classic schema — classic schema edits go through `mstrio-py` or Workstation, not REST | Modeling Service = Mosaic only. Do not attempt classic schema edits via `/api/model/...`. |
| Security filter (create) | `POST /api/model/dataModels/{modelId}/securityFilters` under changeset | `POST /api/securityFilters` (project-level classic SF) | Different shape, different member-assignment path. Routing detail: `reference_strategy_surface_matrix.md`. |
| Security filter (assign members) | `PATCH /api/dataModels/{modelId}/securityFilters/{sfId}/members` | `PATCH /api/securityFilters/{sfId}/members` | Mosaic uses `/Members` PascalCase + `addElements`; classic uses `/members` lowercase — see `reference_mosaic_security_filter.md`. |
| Serve mode change | `PATCH /api/model/dataModels/{modelId}` body `{"dataServeMode":"in_memory|connect_live|hybrid"}` inside a changeset | No equivalent — classic cube has no serve-mode concept | After changing to `in_memory`, the model is *unpublished* until a Mosaic publish completes. |
| Relationships | `PUT /api/model/dataModels/{modelId}/attributes/{childId}/relationships` inside a changeset | Classic relationships live on project schema objects; different endpoints | See `reference_mosaic_rest_gotchas.md`. |
| ACL | `/api/model/dataModels/.../objects/{oid}/acl` (Modeling) OR `/api/objects/{oid}?type=...&showACL=true` (cross-tenant) | `/api/securityPermissions/...` or classic `/api/objects/{oid}/acl` depending on object type | See `reference_mosaic_acl.md`; routing detail in `reference_strategy_surface_matrix.md`. |

## Two asymmetries that keep tripping automation

1. **Mosaic modeling writes** use `/api/model/dataModels/...` (prefix `model/`).
   **Mosaic runtime reads/writes** (publish, publishStatus, instances, securityFilter member assignment) use `/api/dataModels/...` (no `model/`).
   If you see 404 on a path that exists in both shapes, try flipping the `model/` prefix.

2. **`/api/cubes/...` is almost never the right surface for a Mosaic data model.** Two exceptions: (a) the publish trigger `POST /api/cubes/{id}?cubeAction=publish`, which the Studio UI itself uses for subType 779 on Strategy ONE Cloud (see `reference_mosaic_publish_path.md`); (b) the user explicitly wants Intelligent Cube semantics (cache/hit/status) and the object is truly a classic cube. If in doubt, read `GET /api/objects/{id}?type=3` → `subtype`. `subtype:779` → Mosaic data model → classify before touching `/api/cubes/*`.

## Publish — pointer, not a copy

The full verified publish flow (UI `/api/cubes` trigger, 3-step Modeling flow with `X-MSTR-DataModelInstanceId` header + `tables[]` body + `publishStatus` polling, the never-fire-both-endpoints rule, dataType preconditions) lives in `reference_mosaic_publish_path.md`. The classification consequence for `build_mosaic.py publish`: detect subType first; 779 → Mosaic publish per that file with a post-2xx confirmation (poll `publishStatus` or MCP/Trino smoke query); 776 → `/api/cubes/*` directly (no data-model instance needed). Track helper quality in the gap register (`reference_strategy_automation_coverage.md`) — publish is at "captured fallback", not "wrapped helper", until the post-2xx confirmation lands.

The dated tenant-level QueryEngineServer stall narrative that originally motivated this file lives in `captures/2026-04-22-queryengine-publish-incident/README.md`.

## Decision template to apply before every Strategy call

Ask two questions:

> **Q1. Is the target a Mosaic data model, a classic cube, a classic project object, or an agent?**
> **Q2. Am I reading metadata (Modeling Service), writing metadata (Modeling Service), running the model, or administering it (project admin / security)?**

The answers pick the URL prefix (`/api/model/dataModels/...` vs `/api/dataModels/...` vs `/api/cubes/...` vs `/api/objects/...` vs `/api/securityFilters/...`). Write down the classification in the task output (even one line: *"Mosaic data model (779), runtime publish"*) so follow-up steps stay on the right surface.
