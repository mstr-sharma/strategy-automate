---
name: Strategy report + dossier creation via REST — what's actually available
description: What /api/reports, /api/dossiers, /api/documents, /api/v2/* actually support on current Library servers. Most "create from scratch" paths are unavailable; tenant-verified capabilities and the mstrio-py fallback.
type: reference
---

Verified on a Strategy ONE Library tenant, 2026.

## What REST does NOT support
- `POST /api/reports` with a grid definition — **rejected 500 "invalid name"** even with valid payload. The endpoint is there for execution flows, not object creation.
- `POST /api/v2/reports` — **404** on this tenant.
- `POST /api/v2/dossiers` — **404**.
- `POST /api/dossiers` — **405 Method Not Allowed**.
- `POST /api/documents` — **405**.
- `POST /api/v2/dashboards` — **404**.

Conclusion: **Creating a new report, dossier, or dashboard from scratch is not exposed over REST on current Library servers.** This is intentional — the object-authoring surface is Workstation and Library Web, not the public API.

## What REST DOES support
Execution and read-back against *existing* objects:

- `POST /api/reports/{id}/instances` — execute an existing report, with optional prompt answers.
- `GET /api/reports/{id}/instances/{instId}` — result grid.
- `PUT /api/reports/{id}/instances/{instId}/dataset` — swap dataset filters.
- `POST /api/cubes/{id}/instances` — execute an intelligent cube.
- `PUT /api/reports/{id}/instances/{instId}/prompts/answers` — answer prompts mid-execution.
- Dossier read/execute: `GET /api/v2/dossiers/{id}/definition` / `POST /api/v2/dossiers/{id}/instances`.

So the REST flow for automation is: someone authors a template object once (via Workstation), then every subsequent "validation run" is REST-only (clone → execute → compare).

## Workarounds for automation
1. **mstrio-py — dashboards/dossiers are NOT authorable.** Verified against mstrio-py 11.6.4.101 (2026-04-17): `from mstrio.project_objects.dashboard import Dashboard` exists, but the constructor loads existing objects only (`Dashboard(connection, name=None, id=None)`); there is no `create=True`, no `create()` classmethod, no `add_visualization` / `remove_visualization` / `create_visualization` / `delete_visualization` on `Dashboard`, `DashboardChapter`, or `ChapterPage`. `DashboardChapter`, `ChapterPage`, `PageVisualization`, `PageSelector`, `VisualizationSelector` are read-side dataclasses — they describe an already-authored dashboard, they don't build one. Public Dashboard mutations are limited to `alter` (name/description/folder/hidden/comments/owner), `delete`, `create_copy`, `create_shortcut`, `publish`/`unpublish`, `share_to`, ACL helpers, and cache ops. `code_snippets/dashboard.py` on GitHub confirms this shape. `mstrio.project_objects.dossier` still exists as a deprecated alias (1-year sunset) with the same limitation. **For reports,** `Report(create=True)` behavior was not re-verified at 11.6.4.101 — treat as unverified; assume the same Dashboard-style limitation until probed.
2. **Workstation command-line** — `mstrws --create report ...` / Workstation GUI is Strategy's officially supported dashboard-authoring surface but requires a local install, not a network API.
3. **Clone-and-rename (the only mstrio-py path that works for dashboards)** — author one template dashboard in Workstation, then `Dashboard(conn, id=TEMPLATE_ID).create_copy(name=..., folder_id=...)` per run. Rename/move/publish work; rebinding attributes/metrics or adding/removing visualizations does NOT.
4. **SuperCube + hand-authoring** — publish the attributes/metrics as a dataset via `mstrio.project_objects.datasets.super_cube.SuperCube.create(...)`, then a human drags it into a dashboard in Workstation once. Closest programmatic path; creates the data source, not the dashboard.
5. **Library Web internal REST (undocumented)** — the first-party UI authors dashboards over internal endpoints not in `/api/openapi.yaml`. Analogous to the modeling workspace paths captured in `reference_mosaic_ui_internal_endpoints.md`. Requires a Chrome MCP / HAR capture session against a live tenant; version-sensitive.
6. **Fall back to direct SQL / Trino federation** — for validation only, the fastest path is to execute the expected output against the warehouse directly and compare to the Mosaic Trino query. Skips the dashboard entirely. Lose the "user-visible Library artifact" but gain reliability.

## Why this matters for Claude

When the user says "create a dashboard/dossier with these objects," Claude's first reflex should NOT be to reach for REST or assume mstrio-py will author it. The correct flow is:

1. Confirm the user actually needs a saved Library object vs. just validation data.
2. If a saved object is needed:
   - **Dashboard / dossier** → state the gap. The supported paths are: (a) clone an existing template via `Dashboard.create_copy()`, (b) publish a SuperCube + hand-author once in Workstation, or (c) capture the Library Web internal endpoints and script against them (brittle). There is no "create dashboard from attribute+metric list" API as of mstrio-py 11.6.4.101.
   - **Report** → `mstrio.project_objects.report.Report` may still support authoring; verify before claiming. If not, same gap as dashboard.
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
