---
name: Mosaic vs Legacy surface delineation (must-read before any write)
description: Hard rule — do not mix Mosaic data-model endpoints with legacy Intelligent Cube / classic project endpoints. Classify every target by subType + extType (779 + extType 448 Mosaic / 779 other extType = data-import cube / 776 classic cube / else stop) before any call, then use the endpoint-pair cheat sheet to pick the right URL prefix.
type: feedback
---

**Why this exists.** This memory's core value is the **object-classification rule** (779 + extType 448 Mosaic data model vs 776 classic Intelligent Cube) and the table of endpoint pairs that LOOK interchangeable but aren't. Read it before any publish/refresh/execute/ACL/security-filter write so you pick the right URL prefix for the object family. For everything publish-specific — trigger endpoints, the single-trigger rule, dataType preconditions, polling — `reference_mosaic_publish_path.md` is the one publish file; for noun→surface routing beyond these pairs (security filters, ACLs, cubes, datasets, agents), `reference_strategy_surface_matrix.md` wins.

**Rule: before any write, classify the object.**

Read `GET /api/objects/{id}?type=3` → `subtype` and `extType`:

1. `779` (`report_emma_cube`) **and** `extType` 448 (`DATA_IMPORT_DATASET`) → Mosaic data model, owned by the Modeling Service.
2. `779` with any other `extType` → data-import (MTDI) cube, not a Mosaic model. Subtype 779 is shared by both families; mstrio-py's `list_mosaic_models` filters on subtype 779 **plus** extType 448, and `build_mosaic.py`'s `classify_object_surface` now checks `extType` the same way (corrected 2026-10-05 — earlier versions of this note said "779 = Mosaic").
3. `776` → Legacy Intelligent Cube via the classic cube server.
4. Anything else → stop and classify further: classic project object (attribute/metric/report/filter in the legacy semantic layer) or AI agent / Auto agent (separate surface).

Never call a legacy endpoint on a Mosaic object, or a Mosaic endpoint on a legacy object, even if the id would happen to resolve on both. The responses are *different behaviors*, not interchangeable aliases. Calling a Mosaic-only endpoint (`/api/model/dataModels/*`) on a non-Mosaic object fails with `8004e457` — "Given object is not a Mosaic model" — which is the classification rule above telling you it was skipped.

## The pairs that most often get confused

| Intent | Mosaic (use this for a Mosaic data model) | Legacy (use this for a classic Intelligent Cube or classic cube) | Notes |
|---|---|---|---|
| Publish / materialize | `POST /api/dataModels/{modelId}/instances` → `POST /api/dataModels/{modelId}/publish` (`tables[].refreshPolicy`) → `GET …/publishStatus` → `DELETE …/instances/{instanceId}` — the documented flow. `POST /api/cubes/{modelId}?cubeAction=publish` (202) is what the Studio UI fired in 2026-04 tenant captures, but it is internal + deprecated in the spec: tenant-observed fallback only (corrected 2026-10-05); see `reference_mosaic_publish_path.md` | `POST /api/v2/cubes/{id}` (public, 202 + job id; "Intelligent cube or MTDI cube"); v1 `POST /api/cubes/{id}` is internal + deprecated | 2026-04-23 correction: an earlier version of this row said `/api/cubes/*` is never the Mosaic publish path — half wrong; both work on a properly-typed model. Pick ONE trigger per run and never trust the 2xx alone — poll `publishStatus` or Trino-probe before declaring success. Mosaic endpoint lives under `/api/dataModels` (**top-level**, not `/api/model/dataModels`). |
| Publish status | `GET /api/dataModels/{modelId}/publishStatus` (per-table `completed`) | `HEAD /api/cubes/{id}` → `X-MSTR-CubeStatus` header (EnumDSSCubeStates bit vector); there is no `GET /api/cubes/{id}/status` | The Mosaic status is the documented completion signal; confirm with an independent probe (`reference_mosaic_publish_path.md`). |
| Execute / get data | `POST /api/v2/cubes/{modelId}/instances` → `GET …/instances/{instanceId}` (REST docs "Retrieve data from data models": a data model is read through the cube APIs) | `POST /api/v2/cubes/{id}/instances` (cube execution) | `POST /api/dataModels/{modelId}/instances` is the *publish* instance (header `X-MSTR-DataModelInstanceId`), not a data read (corrected 2026-10-05). |
| Create / edit metadata | `POST/PATCH /api/model/dataModels/{modelId}/...` (Modeling Service, changeset-scoped) | Project-level Modeling Service: `/api/model/attributes`, `/facts`, `/metrics`, `/tables`, `/filters`, `/transformations`, `/hierarchies`, `/customGroups`, `/prompts`, `/consolidations` (changeset-scoped; mstrio-py wraps them) | Same service, different scope: never send a classic object to a `/api/model/dataModels/...` path or the reverse. (Corrected 2026-10-05: an earlier row said classic schema has no REST write path.) |
| Security filter (create) | `POST /api/model/dataModels/{modelId}/securityFilters` under changeset | `POST /api/model/securityFilters` (project-level classic SF; `/api/securityFilters` is GET-only) | Different shape, different member-assignment path. Routing detail: `reference_strategy_surface_matrix.md`. |
| Security filter (assign members) | `PATCH /api/dataModels/{modelId}/securityFilters/{sfId}/members` | `PATCH /api/securityFilters/{sfId}/members` | Both share one op schema: `op` ∈ add/replace/remove/incr/addElement(s)/removeElement(s)/move/copy (no `replaceElements`), `path` enum `/members`. A live tenant accepted `/Members` (PascalCase) + `addElements` on the Mosaic path — record both — see `reference_mosaic_security_filter.md`. |
| Serve mode change | `PATCH /api/model/dataModels/{modelId}` body `{"dataServeMode":"in_memory|connect_live|off_memory"}` inside a changeset | No equivalent — classic cube has no serve-mode concept | After changing to `in_memory`, the model is *unpublished* until a Mosaic publish completes. |
| Relationships | `PUT /api/model/dataModels/{modelId}/attributes/{childId}/relationships` inside a changeset | Classic relationships live on project schema objects; different endpoints | See `reference_mosaic_rest_gotchas.md`. |
| ACL | `GET/PATCH /api/model/dataModels/{modelId}/objects/{oid}/acl?subType=` (Modeling, changeset) OR read via `GET /api/objects/{oid}?type=...&showACL=true` | `GET /api/objects/{oid}?type=` (read `acl[]`) / `PUT /api/objects/{oid}?type=` with an `acl` body (write) | There is no `/api/objects/{oid}/acl` sub-resource and no `/api/securityPermissions` path in the spec (corrected 2026-10-05). Rights masks: `reference_mosaic_acl.md`; routing detail in `reference_strategy_surface_matrix.md`. |

## Two asymmetries that keep tripping automation

1. **Mosaic modeling writes** use `/api/model/dataModels/...` (prefix `model/`).
   **Mosaic runtime reads/writes** (publish, publishStatus, instances, securityFilter member assignment) use `/api/dataModels/...` (no `model/`).
   If you see 404 on a path that exists in both shapes, try flipping the `model/` prefix.

2. **`/api/cubes/...` is almost never the right surface for a Mosaic data model.** Two exceptions: (a) the publish trigger `POST /api/cubes/{id}?cubeAction=publish`, which the Studio UI used for Mosaic models in 2026-04 tenant captures — internal + deprecated in the spec, so a fallback only, never alongside the documented `/api/dataModels` flow (see `reference_mosaic_publish_path.md`); (b) the user explicitly wants Intelligent Cube semantics (cache/hit/status) and the object is truly a classic cube. If in doubt, read `GET /api/objects/{id}?type=3` → `subtype` + `extType`. `subtype:779` + `extType:448` → Mosaic data model → classify before touching `/api/cubes/*`.

## Publish — pointer, not a copy

The full publish flow (documented 3-step Modeling flow with `X-MSTR-DataModelInstanceId` header + `tables[]` body + `publishStatus` polling + instance delete, the tenant-observed `/api/cubes` fallback, the never-fire-both-endpoints rule, dataType preconditions) lives in `reference_mosaic_publish_path.md`. The classification consequence for `build_mosaic.py publish`: detect subType + extType first; 779 + extType 448 → Mosaic publish per that file with a post-2xx confirmation (poll `publishStatus` or MCP/Trino smoke query); 776 → cube publish directly, no data-model instance needed (public `POST /api/v2/cubes/{id}`; the CLI's `_classic_cube_publish` still calls the internal/deprecated v1 `POST /api/cubes/{id}?cubeAction=publish`). Track helper quality in the gap register (`reference_strategy_automation_coverage.md`) — publish is at "captured fallback", not "wrapped helper", until the post-2xx confirmation lands.

The dated tenant-level QueryEngineServer stall narrative that originally motivated this file lives in `captures/2026-04-22-queryengine-publish-incident/README.md`.

## Decision template to apply before every Strategy call

Ask two questions:

> **Q1. Is the target a Mosaic data model, a classic cube, a classic project object, or an agent?**
> **Q2. Am I reading metadata (Modeling Service), writing metadata (Modeling Service), running the model, or administering it (project admin / security)?**

The answers pick the URL prefix (`/api/model/dataModels/...` vs `/api/dataModels/...` vs `/api/cubes/...` vs `/api/objects/...` vs `/api/securityFilters/...`). Write down the classification in the task output (even one line: *"Mosaic data model (779/448), runtime publish"*) so follow-up steps stay on the right surface.
