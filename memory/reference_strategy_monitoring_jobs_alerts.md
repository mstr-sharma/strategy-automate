---
name: Strategy monitoring, jobs, alerts, caches
subtype: stub
description: Stub reference for job submission/polling, alerts, cache/cube refresh triggers, scheduler integration, and admin monitors. Part of platform automation coverage; no typed wrapper yet.
type: reference
---

Treat as **generic REST hook** until exercised.

## Endpoint families (rewritten 2026-10-05 against the tenant spec)

The earlier list here (`GET /api/monitors/caches`, `POST /api/monitors/caches/{id}?action=…`, `GET /api/monitors/sessions`, `POST /api/alerts`, `GET /api/alerts/{id}/history`, `POST /api/cubes/{id}/refresh`) named paths that do not exist in the spec. Real families — cluster node names come from `GET /api/monitors/iServer/nodes`:

**Caches**
- `GET /api/monitors/caches/contents?clusterNode=<node>&projectId=<id>` — report / document / dashboard content caches. `clusterNode` is **required**; filters on status, type, owner, size; `limit` ≤ 1000.
- `PATCH /api/v2/monitors/caches/contents?clusterNode=<node>` body `{operationList:[{op:"replace"|"remove", path:"/contentCaches/{combinedId}[/status/loaded|/status/invalid]", value}]}` → 202 — load / unload / invalidate / remove content caches (the v1 `PATCH /api/monitors/caches/contents` is deprecated).
- `GET /api/monitors/caches/cubes?clusterNode=<node>&projectIds=<id>` (`clusterNode` **required**) → `GET /api/monitors/caches/cubes/{id}`.
- `PATCH /api/monitors/caches/cubes/{id}` with header `Prefer: respond-async` and body `{state:{…}}` → 202 + `manipulationId` (poll `GET /api/monitors/caches/cubes/manipulations/{id}/status`); `DELETE /api/monitors/caches/cubes/{id}` → 204.
- Per object: `GET/DELETE /api/monitors/caches/report/{id}`, `GET/DELETE /api/monitors/caches/document/{id}`. Project element/object cache purge: `DELETE /api/monitors/projects/{projectId}/caches/{element|object|report|all}`.

**Jobs**
- `GET /api/v2/monitors/jobs?nodeName=<node>` (filters `projectName`, `type` ∈ interactive / subscription / predictive_cache / realtime, `status`, `objectType`, `user`, …) → `GET /api/v2/monitors/jobs/{id}`; `GET …/jobs/{id}/queries` for realtime jobs.
- Cancel: `DELETE /api/v2/monitors/jobs/{id}` or `POST /api/v2/monitors/cancelJobs` body `{jobIds:[…]}` (200, or 207 on partial success).
- v1 `GET /api/monitors/jobs`, `DELETE /api/monitors/jobs/{id}` and `POST /api/monitors/cancelJobs` are deprecated.

**Sessions**
- `GET /api/monitors/userConnections?clusterNode=…&projectId=…` (cross-user, admin) → `DELETE /api/monitors/userConnections/{id}` (204) to disconnect one. There is no `/api/monitors/sessions`.

**Alerts**
- Data alerts are **subscriptions**: `Subscription.alert` (read-only boolean) marks an alert subscription; list/edit them through `/api/subscriptions` (`reference_strategy_subscriptions_and_schedules.md`). There is no `/api/alerts`. `GET /api/telemetry/alerts` (+ `/{alertId}/details`, `PUT …/actions`) belongs to the Telemetry tag, not to data alerts.

**Refresh**
- Mosaic model: the documented `/api/dataModels/{id}` flow — `POST …/instances` → `POST …/publish` with per-table `refreshPolicy` (`add` / `update` / `upsert` / `replace` / …) → `GET …/publishStatus` → delete the instance (`reference_mosaic_publish_path.md`).
- Classic / MTDI cube: `POST /api/v2/cubes/{id}` (202 + job id). Incremental refresh is an object: `POST /api/model/incrementalRefresh` (define) + `POST /api/incrementalRefresh/{irrId}` (run). There is no `/api/cubes/{id}/refresh`.

**Verified tenant observations (2026-10-01)**
- `GET /api/monitors/jobs?nodeName=<node>&projectId=<id>` — job records carry `sql`, `template`, `filter` while the job runs; needs the **Monitor Jobs** privilege (ERR014 -2147213784 otherwise). That is the deprecated v1 monitor — use `GET /api/v2/monitors/jobs` (filter `projectName`) for new work.
- `GET /api/monitors/caches/cubes?clusterNode=<node>&projectIds=<id>` → `GET /api/monitors/caches/cubes/{cacheId}` — detail carries `jobExecutionStatistics` (pass counts, durations, `dbInstanceNames`, `accessedTables`, `queryPasseInfos[].sqlStatement`) for the last publish job; cache id = base64 of `<cacheId>:<projectId>:<node>`, match on `source.id`. See `reference_strategy_sql_visibility.md`.

## Routing rules (corrected 2026-10-05)

- **Mosaic model data refresh** → the documented data-model publish flow; `POST /api/cubes/{id}?cubeAction=publish` (what the UI fired in 2026-04 captures) is internal + deprecated — fallback only (see publish-path memory).
- **Classic cube refresh** → `POST /api/v2/cubes/{id}`, or run an incremental refresh report.
- **Schedule that re-publishes nightly** → a subscription on a schedule (`reference_strategy_subscriptions_and_schedules.md`): for a Mosaic model, `POST /api/subscriptions` with `contents:[{type:"data_model", refreshCondition:{tables:[{id, refreshPolicy}]}}]` and delivery mode `HISTORY_LIST`; for a classic cube, a cache-update (`CACHE`) subscription.
- **Alert on a metric threshold** → an alert subscription (`/api/subscriptions`), not `/api/alerts`.

## Critical gotchas to capture

- Alert threshold qualification shape (element list vs form qualification) — likely mirrors security-filter qualification syntax.
- Job cancellation behavior on a half-done cube refresh (does partial data persist?).
- Session-monitor cleanup vs the interactive-session cap documented in `feedback_build_mosaic_session_leak.md`.

## Pending verified payloads

- Metric-threshold alert definition body.
- Cache-invalidate return semantics (async job id vs synchronous 204).
- Running-job cancel success rate.
