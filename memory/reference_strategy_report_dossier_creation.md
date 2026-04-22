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
1. **mstrio-py** — the official Python SDK wraps internal endpoints that DO create reports/dossiers. Use `mstrio.project_objects.report.Report(create=True)` or the `OlapCube` / `SuperCube` classes. This is the recommended path for script-driven object authoring.
2. **Workstation command-line** — `mstrws --create report ...` is Strategy's headless authoring surface but requires a local install.
3. **Clone-and-rename** — find a template report/dossier of the right shape, `POST /api/reports/{id}/copy` (if exposed) or clone via Workstation, then patch its dataset definition via `PUT /api/reports/{id}` (limited). This bypasses the author-from-scratch gap.
4. **Fall back to direct SQL / Trino federation** — for validation only, the fastest path is to execute the expected output against the warehouse directly and compare to the Mosaic Trino query. Skips the dossier entirely. Lose the "user-visible Library artifact" but gain reliability.

## Why this matters for Claude

When the user says "create a dossier with these objects," Claude's first reflex should NOT be to reach for REST. The correct flow is:

1. Confirm the user actually needs a saved Library object vs. just validation data.
2. If a saved object is needed → route to `strategy-automation` skill with the mstrio-py path, not `build_mosaic.py`.
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
