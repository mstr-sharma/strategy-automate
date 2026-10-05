---
name: Strategy report + dossier creation via REST — what's actually available
description: What /api/reports, /api/dossiers, /api/documents, /api/model/reports and /api/v2/* actually support on current Library servers. Reports CAN be created (POST /api/model/reports → /instances/save|saveAs) and dashboards can be built in memory (POST /api/dossiers/instances or /dossiers/draft/instances) and saved (documents …/instances/{id}/saveAs); the probed 404/405 paths below are the wrong doors, not proof of a gap.
type: reference
---

> **Current rule (corrected 2026-10-05):** from-scratch creation IS exposed over REST — documented in the REST docs and public in the tenant spec:
> - **Report:** `POST /api/model/reports` (Modeling Service; grid + dataSource + optional filter; REST docs "Create a new report", since 2021 Update 7) → `POST /api/model/reports/{id}/instances` → `POST /api/model/reports/{id}/instances/save` or `…/instances/saveAs` (`X-MSTR-MS-Instance` header).
> - **Dashboard:** `POST /api/dossiers/instances` (body `DashboardCreationInfo`, e.g. `{"objects":[{"id":"<report id>","type":3}]}`; REST docs "Create dashboard instances", since 2021 Update 10) or `POST /api/dossiers/draft/instances` (in memory over existing datasets) → `POST /api/documents/{id}/instances/{instanceId}/saveAs` (body `{name, folderId, description, overwrite}`) → 201 `{id}`. Dashboards and documents are object type 55 (type 58 is a security filter).
> - Instance creation for an existing dashboard is **v1** `POST /api/dossiers/{id}/instances`; there is no `POST /api/v2/dossiers/{id}/instances` (v2 has the definition / visualization reads).
> - The mstrio-py `Dossier` class was **removed in 11.5.3.101** (2025-03-21) — use `Dashboard`. There is no documented `mstrws` command-line authoring tool.
>
> What REST still does not do is fine-grained visualization CRUD on a saved dashboard (add / remove / rebind a viz) — that remains Workstation / Library Web. The sections below are the 2026-04 probe history; where they conflict with this box, the box wins.

Verified on a Strategy ONE Library tenant, 2026.

## What REST does NOT support (history — 2026-04 probes of the wrong paths)
- `POST /api/reports` with a grid definition — **rejected 500 "invalid name"** even with valid payload. That operation is `saveReport` ("Save the changes in the instance to report"), not a create endpoint.
- `POST /api/v2/reports` — **404** on this tenant.
- `POST /api/v2/dossiers` — **404**.
- `POST /api/dossiers` — **405 Method Not Allowed**.
- `POST /api/documents` — **405**.
- `POST /api/v2/dashboards` — **404**.

~~Conclusion: creating a new report, dossier, or dashboard from scratch is not exposed over REST.~~ **Superseded (corrected 2026-10-05):** these probes hit the wrong paths; reports are created through `/api/model/reports` and dashboards through `/api/dossiers/instances` / `/api/dossiers/draft/instances` + documents `saveAs` (box at the top).

Two dated corrections (2026-08-26/27, Strategy ONE Cloud env family):
- **Reports ARE creatable via the Modeling Service** — `POST /api/model/reports` (grid + dataSource + optional filter) followed by `POST /api/model/reports/{id}/instances/saveAs` with the `X-MSTR-MS-Instance` header. Verified repeatedly (see `reference_strategy_legacy_semantic_admin.md`). The 500s above were against `POST /api/reports`, which saves changes from an existing instance (`saveReport`) rather than creating a report.
- **The dashboard-authoring path is public and documented** (corrected 2026-10-05; this line used to call it a `?visibility=all` candidate): `POST /api/dossiers/instances` accepts `DashboardCreationInfo` (`{objects: [{id: <reportId>, type: 3}]}`) to build an in-memory dashboard around report(s), `POST /api/dossiers/draft/instances` builds one over existing datasets, and `POST /api/documents/{id}/instances/{mid}/saveAs` persists the instance to a folder. Not yet exercised on this tenant family. `POST /api/dashboards` (import a .mstr file) and `POST /api/dashboards/json` (dashboard view from a report) are both deprecated.

## What REST DOES support
Execution and read-back against *existing* objects:

- `POST /api/reports/{id}/instances` — execute an existing report, with optional prompt answers.
- `GET /api/reports/{id}/instances/{instId}` — result grid.
- `PUT /api/reports/{id}/instances/{instId}/dataset` — swap dataset filters.
- `POST /api/cubes/{id}/instances` — execute an intelligent cube.
- `PUT /api/reports/{id}/instances/{instId}/prompts/answers` — answer prompts mid-execution.
- Dossier read/execute: `GET /api/v2/dossiers/{id}/definition` / `POST /api/dossiers/{id}/instances` (v1 — there is no v2 instance-create; corrected 2026-10-05).

So the REST flow for automation is: someone authors a template object once (via Workstation), then every subsequent "validation run" is REST-only (clone → execute → compare).

## Workarounds for automation
1. **mstrio-py — dashboards/dossiers are NOT authorable.** Verified against mstrio-py 11.6.4.101 (2026-04-17): `from mstrio.project_objects.dashboard import Dashboard` exists, but the constructor loads existing objects only (`Dashboard(connection, name=None, id=None)`); there is no `create=True`, no `create()` classmethod, no `add_visualization` / `remove_visualization` / `create_visualization` / `delete_visualization` on `Dashboard`, `DashboardChapter`, or `ChapterPage`. `DashboardChapter`, `ChapterPage`, `PageVisualization`, `PageSelector`, `VisualizationSelector` are read-side dataclasses — they describe an already-authored dashboard, they don't build one. Public Dashboard mutations are limited to `alter` (name/description/folder/hidden/comments/owner), `delete`, `create_copy`, `create_shortcut`, `publish`/`unpublish`, `share_to`, ACL helpers, and cache ops. `code_snippets/dashboard.py` on GitHub confirms this shape. The deprecated `Dossier` class was **removed in mstrio-py 11.5.3.101** (corrected 2026-10-05 — an earlier line said `mstrio.project_objects.dossier` lingered as an alias). **For reports,** `Report(create=True)` behavior was not re-verified at 11.6.4.101 — but REST covers report creation directly (`POST /api/model/reports`, box at the top), so mstrio is not needed for it. For dashboards, REST now covers create-in-memory + `saveAs` (box at the top); mstrio still has no dashboard-authoring class.
2. **Workstation GUI** — Strategy's supported surface for full dashboard authoring (visualization layout, add/remove viz); requires a local install, not a network API. (Corrected 2026-10-05: there is no documented `mstrws` command-line authoring tool — the `mstrws --create report` example recorded here has no source in the product or REST docs; don't offer it.)
3. **Clone-and-rename (the only mstrio-py path that works for dashboards)** — author one template dashboard in Workstation, then `Dashboard(conn, id=TEMPLATE_ID).create_copy(name=..., folder_id=...)` per run. Rename/move/publish work; rebinding attributes/metrics or adding/removing visualizations does NOT.
4. **SuperCube + hand-authoring** — publish the attributes/metrics as a dataset via `mstrio.project_objects.datasets.super_cube.SuperCube.create(...)`, then a human drags it into a dashboard in Workstation once. Closest programmatic path; creates the data source, not the dashboard.
5. **Library Web internal REST (undocumented)** — the first-party UI authors dashboards over internal endpoints not in `/api/openapi.yaml`. Analogous to the modeling workspace paths captured in `reference_mosaic_ui_internal_endpoints.md`. Requires a Chrome MCP / HAR capture session against a live tenant; version-sensitive.
6. **Fall back to direct SQL / Trino federation** — for validation only, the fastest path is to execute the expected output against the warehouse directly and compare to the Mosaic Trino query. Skips the dashboard entirely. Lose the "user-visible Library artifact" but gain reliability.

## Why this matters for Claude

When the user says "create a dashboard/dossier with these objects," Claude's first reflex should NOT be to reach for REST or assume mstrio-py will author it. The correct flow is:

1. Confirm the user actually needs a saved Library object vs. just validation data.
2. If a saved object is needed:
   - **Dashboard / dossier** → REST: `POST /api/dossiers/instances` (around reports / cubes) or `POST /api/dossiers/draft/instances` (over existing datasets) → `POST /api/documents/{id}/instances/{instanceId}/saveAs`. That yields a saved dashboard built around the source objects with a server-generated layout (not yet exercised here); custom layouts still come from (a) cloning a template via `Dashboard.create_copy()` or `POST /api/objects/{id}/copy?type=55`, or (b) Workstation. mstrio-py has no dashboard-authoring class (11.6.9.101).
   - **Report** → REST `POST /api/model/reports` → `…/instances` → `…/instances/saveAs` (corrected 2026-10-05; earlier text said to verify mstrio's `Report` first).
3. If only validation data is needed → execute via REST `/instances` on an existing template or go direct-to-warehouse.

## Report execution pattern (the automated path that actually works)

```python
# Assume reportId comes from /api/searches or a known template
r = m.post(f"/api/reports/{reportId}/instances", json={})
instance_id = r.json()["instanceId"]
# Poll status until ready
while True:
    st = m.get(f"/api/reports/{reportId}/instances/{instance_id}/status").json()
    if st["status"] == 1: break
# Get the grid data
data = m.get(f"/api/v2/reports/{reportId}/instances/{instance_id}?limit=100").json()
# data['definition']['grid']['rows']/['columns'] + data['data']['headers'] + ['metricValues']
```

The JSON-Data envelope returned by `/api/v2/reports/{id}/instances/{instId}` has `data.headers` (attribute element strings) + `data.metricValues.raw` (2-D array) — this is what to compare against the Mosaic Trino result.
