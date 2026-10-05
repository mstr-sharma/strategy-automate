---
name: Report / dashboard / dossier authoring — recommended patterns
subtype: stub
description: Authoring paths for reports / dashboards and their trade-offs. Corrected 2026-10-05 — REST DOES create reports (POST /api/model/reports → /instances/save|saveAs) and in-memory dashboards (POST /api/dossiers/instances or /dossiers/draft/instances → documents saveAs); what is missing is visualization-level CRUD. Also covers clone-and-retarget, mstrio-py, and execute-and-persist via /instances (see reference_strategy_report_dossier_creation.md).
type: reference
---

> **Correction (2026-10-05):** earlier versions said REST cannot create reports or dashboards. Reports: `POST /api/model/reports` → `POST /api/model/reports/{id}/instances` → `…/instances/save` or `…/instances/saveAs` (`X-MSTR-MS-Instance`). Dashboards: `POST /api/dossiers/instances` (`DashboardCreationInfo`) or `POST /api/dossiers/draft/instances` → `POST /api/documents/{id}/instances/{instanceId}/saveAs`. Instance creation for an existing dashboard is v1 `POST /api/dossiers/{id}/instances`. Dashboards/documents are type 55; type 58 is a security filter. mstrio-py's `Dossier` class was removed in 11.5.3.101. The gaps below that still hold are visualization add/remove/rebind on a saved dashboard.

## Why this exists

Users often say "generate a dashboard for X." The repeatable automation paths, honest about current surface (verified against mstrio-py 11.6.4.101, 2026-04-17):

1. **Dashboards / dossiers — mstrio-py does not author them (REST can create one in memory and `saveAs` it — box above).** The `Dashboard` class (the `Dossier` class is gone since 11.5.3.101) loads and manages existing objects; they do NOT create from attribute+metric lists, add/remove visualizations, or rebind datasets. `DashboardChapter`, `ChapterPage`, `PageVisualization` are read-side dataclasses only. The only mstrio-py mutation that produces a new saved dashboard is `Dashboard(conn, id=TEMPLATE).create_copy(...)` — everything else (layout, viz set, attribute/metric binding) must already exist in the template.
2. **Reports — REST creates them** via the Modeling Service (`POST /api/model/reports` → instance → `save`/`saveAs`; box above). Whether mstrio-py's `Report` exposes `create=True` was not re-verified at 11.6.4.101, but it is not needed for this.
3. **Clone-and-retarget from a template** — copy an existing published report/dashboard/dossier via `Dashboard.create_copy()` or `POST /api/objects/{id}/copy?type=<type>` with body `{name, folderId}`, then PATCH the filter/prompt defaults or underlying dataset binding. Works for Library dashboards where a template catalog already exists. Rebinding attributes/metrics post-copy is NOT verified for dashboards — treat as likely-manual.
4. **SuperCube / OlapCube dataset publish** — `mstrio.project_objects.datasets.super_cube.SuperCube.create(...)` publishes the data; a human then hand-authors the dashboard in Workstation. Closest programmatic path; gets you the data source, not the viz layer.
5. **Execute-and-save via `/instances`** — create a new instance of an existing report/document with prompt answers + runtime filters, then save the instance output as a new saved report. Does NOT create new layout/visualization — it only binds new runtime inputs to an existing template.
6. **Library Web internal REST (undocumented)** — the first-party UI authors dashboards over endpoints not in `/api/openapi.yaml`. See `reference_mosaic_ui_internal_endpoints.md` for the capture pattern. Brittle and version-sensitive; the only path that delivers real viz CRUD.

Do NOT expect the Mosaic *data-model* endpoints (`/api/model/dataModels/...`) to author reports/dashboards. Reports are written through the Modeling Service's own `/api/model/reports`; dashboards and documents (both object type 55 — type 58 is a security filter; corrected 2026-10-05) go through `/api/dossiers/...` and `/api/documents/...`.

## Decision table

| User ask | Recommended path |
|---|---|
| "Create a new report from these attributes and metrics" | `POST /api/model/reports` → `POST /api/model/reports/{id}/instances` → `…/instances/saveAs` (`X-MSTR-MS-Instance`). |
| "Create a new dashboard from scratch with these attributes and metrics" | Build a report or dataset first, then `POST /api/dossiers/instances` (around the report) or `POST /api/dossiers/draft/instances` (over datasets) → `POST /api/documents/{id}/instances/{instanceId}/saveAs`. Layout is server-generated; for a designed layout offer Workstation or clone-template. (Corrected 2026-10-05: earlier text called this a known gap.) |
| "Add/remove a visualization on a dashboard" | **Known gap.** Not exposed by mstrio-py or public REST. Workstation or internal-REST capture only. |
| "Clone dashboard X into folder Y with a new name" | `Dashboard(conn, id=X).create_copy(name=..., folder_id=...)` — verified supported. |
| "Copy Report X into folder Y and re-point at new dataset" | `/api/objects/{id}/copy` + PATCH definition. Rebind verified for some object families; confirm for reports before shipping. |
| "Run Report X with these prompt answers and save output" | `/instances` flow → save instance as new object. |
| "Scheduled email of Dashboard X" | See `reference_strategy_subscriptions_and_schedules.md`. |
| "Build an AI-generated dashboard" | Library's AI authoring in the UI; the `/api/aiservice/...` calls behind it are not in the spec (corrected 2026-10-05), so treat the output as a generated artifact, not a scriptable contract. |

## Clone-and-retarget endpoint

```
POST /api/objects/{sourceId}/copy?type={3|55|...}        # 3 = report/cube, 55 = dashboard/document
body: {"name": "<new name>", "folderId": "<destination folder id>"}
-> 201 { "id": "<newObjectId>", ... }
```
(Corrected 2026-10-05: the copy takes `type` as the only query parameter and `{name, folderId}` in the body — there are no `destinationFolderId` / `newName` parameters; type 58 is a security filter and 74 is not a cube type.)

After copy, PATCH the needed slots:
- Dataset binding (for dossiers backed by Mosaic models) — dossier definition references model IDs; remap after copy.
- Prompt defaults / filter definition — unverified: the spec has only `GET /api/documents/{id}/prompts` and `GET /api/documents/{id}/definition` (no PATCH; noted 2026-10-05). For a report, edit through the Modeling Service (`GET/PUT /api/model/reports/{id}`) instead.

## Verified vs gap

- **Verified**: copy + rename via `Dashboard.create_copy()` and `POST /api/objects/{id}/copy` (across documents, dossiers, reports, filters, custom groups).
- **Verified gap (2026-04, mstrio-py 11.6.4.101)**: visualization add/remove and dataset-rebind on a copied dashboard (from-scratch creation is covered by REST — box at the top). None of these exist on `Dashboard`, `DashboardChapter`, `ChapterPage`, `PageVisualization`. Escalate to Workstation or internal-REST capture.
- **Unverified — probe before claiming**: whether `mstrio.project_objects.report.Report(create=True)` still supports authoring in current mstrio-py. Not a gap either way: REST `POST /api/model/reports` creates reports.
- **Gap**: verified payload for dataset-rebind PATCH on copied dashboard — needs to be captured when first exercised.

## Pointers

- `reference_strategy_runtime_analytics.md` — execute/export semantics.
- `reference_strategy_report_dossier_creation.md` — the REST surface gap analysis.
- `reference_mstrio_py.md` — when to use the Python wrapper over raw REST.
