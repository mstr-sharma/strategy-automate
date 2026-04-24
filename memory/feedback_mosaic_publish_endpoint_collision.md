---
name: Never fire /api/cubes publish AND 3-step publish concurrently — the status endpoint locks out
description: Calling `POST /api/cubes/{id}?cubeAction=publish` AND `POST /api/dataModels/{id}/publish` on the same cube inside the same script both kicks off a publish job. `GET /api/dataModels/{id}/publishStatus` then returns `500 ERR001 iServerCode -2147072194` "is being published by job <N>" for the entire lifetime of THAT job, even though the cube finishes materializing in seconds. The script thinks publish is hung; Library UI shows it complete. Pick ONE publish trigger per run.
type: feedback
---

## Rule

When publishing an in-memory Mosaic data model, call **exactly one** of the two publish endpoints per run:

- `POST /api/cubes/{id}?cubeAction=publish` — UI-equivalent, returns 202 immediately, no instance needed. Poll by Trino probe or `GET /api/cubes/{id}`.
- `POST /api/dataModels/{id}/instances` + `POST /api/dataModels/{id}/publish` + `GET /api/dataModels/{id}/publishStatus` — three-step, uses instance id, only this returns per-table status.

Do NOT issue both. If you fire `/api/cubes` first and then follow up with the 3-step `publish` POST, Strategy sees two publish jobs racing on the same cube. The CubeServer serializes them (accepts the first, queues/rejects the second), and `publishStatus` against the LOSING instance id returns the "is being published by job N" 500 for the full duration of the winning job. Your polling loop sees the error continuously, times out, and reports failure — even though the cube is actually being published successfully.

## Observed

2026-04-23, studio.strategy.com, model `Tenant GPU Analysis-*`:
- `/api/cubes/{id}?cubeAction=publish` → 202 (started publish job 13507).
- `/api/dataModels/{id}/publish` fired 200ms later → 204 (second publish, queued/blocked).
- `GET /api/dataModels/{id}/publishStatus` with the 3-step instance id → **21 consecutive 500 responses over ~5 minutes**, all `iServerCode: -2147072194` "Cube report … is being published by job 13507". The script never saw a green status.
- User checked the Library UI: publish had completed **in seconds**. MCP Trino query confirmed the cube had 63,677 rows.

## Fix pattern

```python
# Single-trigger, Trino-probe publish
r = s.post(f"{BASE}/api/cubes/{MID}?cubeAction=publish")
assert r.status_code == 202

# Poll by checking the Trino/MCP catalog, not by 3-step status
deadline = time.time() + 600
while time.time() < deadline:
    time.sleep(15)
    probe = s.post(f"{MCP_BASE}/query",
                   json={"schema":"Shared Studio",
                         "query": f'SELECT count(*) FROM "{model_name.lower()}"'})
    if probe.ok and "count" in probe.json(): break
```

Or, if you need per-table status (incremental refresh / schema drift detection), use ONLY the 3-step flow — do NOT combine it with `/api/cubes`.

## Why this tripped the run

The script was defensive — it tried both paths to be robust against either one failing. In this tenant family BOTH paths succeed, but they serialize on the cube lock, and the losing instance's `publishStatus` call is the one the script polled. Net effect: a working publish looked like an infinite stall.

## Related memories

- `reference_mosaic_publish_path.md` covers the two endpoints' mechanics. Add a pointer from there to this memory.
- `feedback_mosaic_publishable_datatypes.md` covers the OTHER class of publish failure (actual parallel-mode stall -2147212544). Don't confuse the two iServerCodes: `-2147212544` = real stall (bad datatypes); `-2147072194` = job-in-progress lockout (you fired both endpoints).
