---
name: Strategy monitoring, jobs, alerts, caches
subtype: stub
description: Stub reference for job submission/polling, alerts, cache/cube refresh triggers, scheduler integration, and admin monitors. Part of platform automation coverage; no typed wrapper yet.
type: reference
---

Treat as **generic REST hook** until exercised.

## Endpoint families

- `GET /api/monitors/caches` — cache inventory (report, cube, dossier caches).
- `POST /api/monitors/caches/{id}?action=invalidate|delete|load` — cache operations.
- `GET /api/monitors/jobs` — job monitor (running + recent).
- `DELETE /api/monitors/jobs/{id}` — cancel a running job.
- `GET /api/monitors/sessions` — user session monitor (cross-user view for admins).
- `POST /api/alerts` — alert definition (threshold on metric, schedule, recipients).
- `GET /api/alerts/{id}/history` — fired-alert log.
- `POST /api/dataModels/{id}/publish` with `refreshPolicy:"update"|"upsert"` — Mosaic incremental refresh (pairs with `reference_mosaic_publish_path.md`).
- `POST /api/cubes/{id}/refresh?refreshType=add|replace|update|upsert|incremental` — classic cube refresh.

## Routing rules

- **Mosaic model data refresh** → `POST /api/dataModels/{id}/publish` or UI's `/api/cubes/{id}?cubeAction=publish` (see publish-path memory).
- **Classic cube refresh** → `/api/cubes/{id}/refresh`.
- **Schedule that re-publishes nightly** → create a Schedule (`reference_strategy_subscriptions_and_schedules.md`) that triggers a cache/refresh subscription or an external scheduler calling the publish endpoint.
- **Alert on a metric threshold** → `/api/alerts` with threshold definition + delivery (email/push).

## Critical gotchas to capture

- Alert threshold qualification shape (element list vs form qualification) — likely mirrors security-filter qualification syntax.
- Job cancellation behavior on a half-done cube refresh (does partial data persist?).
- Session-monitor cleanup vs the interactive-session cap documented in `feedback_build_mosaic_session_leak.md`.

## Pending verified payloads

- Metric-threshold alert definition body.
- Cache-invalidate return semantics (async job id vs synchronous 204).
- Running-job cancel success rate.
