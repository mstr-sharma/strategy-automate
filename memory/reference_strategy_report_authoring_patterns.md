---
name: Report / dashboard / dossier authoring — recommended patterns
subtype: stub
description: REST does NOT expose from-scratch creation of reports/dossiers/dashboards on current Strategy ONE tenants (see reference_strategy_report_dossier_creation.md). This memory documents the surviving authoring paths — mstrio-py object construction, clone-and-retarget from a template, execute-and-persist via /instances — and the trade-offs among them.
type: reference
---

## Why this exists

Users often say "generate a dashboard for X." The repeatable automation paths, honest about current surface (verified against mstrio-py 11.6.4.101, 2026-04-17):

1. **Dashboards / dossiers — authoring is NOT exposed.** `Dashboard` / `Dossier` classes load and manage existing objects; they do NOT create from attribute+metric lists, add/remove visualizations, or rebind datasets. `DashboardChapter`, `ChapterPage`, `PageVisualization` are read-side dataclasses only. The only mstrio-py mutation that produces a new saved dashboard is `Dashboard(conn, id=TEMPLATE).create_copy(...)` — everything else (layout, viz set, attribute/metric binding) must already exist in the template.
2. **Reports / documents — partially supported, verify before claiming.** `mstrio.project_objects.report.Report` and `Document` may expose authoring constructors on older docs, but this has not been re-verified at 11.6.4.101. Probe the class surface before writing automation that assumes `create=True` works.
3. **Clone-and-retarget from a template** — copy an existing published report/dashboard/dossier via `Dashboard.create_copy()` or `POST /api/objects/{id}/copy?destinationFolderId=...`, then PATCH the filter/prompt defaults or underlying dataset binding. Works for Library dashboards where a template catalog already exists. Rebinding attributes/metrics post-copy is NOT verified for dashboards — treat as likely-manual.
4. **SuperCube / OlapCube dataset publish** — `mstrio.project_objects.datasets.super_cube.SuperCube.create(...)` publishes the data; a human then hand-authors the dashboard in Workstation. Closest programmatic path; gets you the data source, not the viz layer.
5. **Execute-and-save via `/instances`** — create a new instance of an existing report/document with prompt answers + runtime filters, then save the instance output as a new saved report. Does NOT create new layout/visualization — it only binds new runtime inputs to an existing template.
6. **Library Web internal REST (undocumented)** — the first-party UI authors dashboards over endpoints not in `/api/openapi.yaml`. See `reference_mosaic_ui_internal_endpoints.md` for the capture pattern. Brittle and version-sensitive; the only path that delivers real viz CRUD.

Do NOT expect the Mosaic Modeling Service to author reports/dashboards. That service is schema-only; reports/dashboards are a separate object family (types 55 document, 58 dossier/dashboard) not writable through `/api/model/...`.

## Decision table

| User ask | Recommended path |
|---|---|
| "Create a new dashboard from scratch with these attributes and metrics" | **Known gap.** mstrio-py `Dashboard` does not expose authoring; public REST returns 404/405. Offer Workstation, clone-template, SuperCube+manual, or internal-REST capture. |
| "Add/remove a visualization on a dashboard" | **Known gap.** Not exposed by mstrio-py or public REST. Workstation or internal-REST capture only. |
| "Clone dashboard X into folder Y with a new name" | `Dashboard(conn, id=X).create_copy(name=..., folder_id=...)` — verified supported. |
| "Copy Report X into folder Y and re-point at new dataset" | `/api/objects/{id}/copy` + PATCH definition. Rebind verified for some object families; confirm for reports before shipping. |
| "Run Report X with these prompt answers and save output" | `/instances` flow → save instance as new object. |
| "Scheduled email of Dashboard X" | See `reference_strategy_subscriptions_and_schedules.md`. |
| "Build an AI-generated dashboard" | `/api/aiservice/...` + Mosaic agent; treat as a generated artifact, not a curated dashboard. |

## Clone-and-retarget endpoint

```
POST /api/objects/{sourceId}/copy?destinationFolderId={folderId}&newName={name}&type={3|55|58|74|...}
-> { "id": "<newObjectId>", ... }
```

After copy, PATCH the needed slots:
- Dataset binding (for dossiers backed by Mosaic models) — dossier definition references model IDs; remap after copy.
- Prompt defaults — `PATCH /api/documents/{id}/prompts` with new default values.
- Filter definition — `PATCH /api/documents/{id}/definition` (structure varies by object family).

## Verified vs gap

- **Verified**: copy + rename via `Dashboard.create_copy()` and `POST /api/objects/{id}/copy` (across documents, dossiers, reports, filters, custom groups).
- **Verified gap (2026-04, mstrio-py 11.6.4.101)**: from-scratch dashboard authoring, visualization add/remove, dataset-rebind on copied dashboard. None of these exist on `Dashboard`, `DashboardChapter`, `ChapterPage`, `PageVisualization`. Escalate to Workstation or internal-REST capture.
- **Unverified — probe before claiming**: whether `mstrio.project_objects.report.Report(create=True)` still supports authoring in current mstrio-py. Older memory assumed yes; not re-confirmed. Treat as gap until probed.
- **Gap**: verified payload for dataset-rebind PATCH on copied dashboard — needs to be captured when first exercised.

## Pointers

- `reference_strategy_runtime_analytics.md` — execute/export semantics.
- `reference_strategy_report_dossier_creation.md` — the REST surface gap analysis.
- `reference_mstrio_py.md` — when to use the Python wrapper over raw REST.
