---
name: Strategy environment preflight probe
description: Before building, publishing, or running expensive automation, probe tenant health so you fail early instead of halfway through. Covers datasource reachability, project session cap, publish queue sanity, user privileges, tenant platform version, and driver availability.
type: reference
---

## Why probe first

Several automation failures look like bugs in a script but are tenant-state:
- Interactive-session cap already exhausted (`8004cb0a`, `-2147072486`) → changesets fail at open.
- Project not loaded on the IServer node → metadata reads return 404 on objects that actually exist.
- Publish queue stalled from a prior job → new publishes return 204 but never materialize.
- Stale datasource credentials → catalog endpoints 401 even though user login works.

A 90-second preflight that checks these avoids long diagnostic sessions.

## Preflight checklist

Run in order; stop at the first fail.

1. **Auth works**:
   `POST /api/auth/login` → expect 204 + `X-MSTR-AuthToken` header.
2. **Session health + capacity**:
   `GET /api/sessions` → confirm `fullName` matches the expected user; record `timeout`.
3. **Project reachable**:
   `GET /api/projects` → confirm the target project's `status==0` (active/loaded). Corrected 2026-10-05: **`-1` = offline (unloaded)**; positive values are idle states (1 exec-idle, 2 request-idle, 4 warehouse-exec-idle, 7 full-idle), `-2` offline-pending, `-3` error, `-4` online-pending (mstrio-py `ProjectStatus`). Load (admin) with `PATCH /api/monitors/projects/status?projectId=<id>` body `{"status":"loaded"}` (all nodes) or `PATCH /api/monitors/iServer/nodes/{node}/projects/{id}` (one node) — there is no `POST /api/projects/{id}?action=load`. Details: `reference_strategy_project_loading.md`.
4. **Datasource connectivity**:
   `POST /api/datasources/{id}/test` per datasource in use → expect 204 (there is no `/testConnection`; corrected 2026-10-05).
5. **Feature flags**:
   `GET /api/v2/configurations/featureFlags` → confirm in-memory publish / AI service / Trino federation are enabled on this tenant.
6. **Modeling-service identity token**:
   `POST /api/auth/identityToken` → expect 200 + `X-MSTR-IdentityToken`. Tenant-dependent: build_mosaic mints it for Mosaic changeset pipelines, drops it on a `8004cb09` 403 (`feedback_mosaic_identity_token_privilege_downgrade.md`); not used for classic/project writes.
7. **Gateways + drivers** (only before new datasource creation):
   `GET /api/gateways`, `GET /api/drivers` → confirm the target database driver is installed.
8. **Destination folder writeable** (only before model/object creation):
   `GET /api/folders/{destFolderId}` → confirm `acg` includes write bits; `POST /api/folders/` is a preflight alternative.
9. **Publish queue sanity** (only before in-memory Mosaic publish):
   `GET /api/v2/monitors/jobs?nodeName=<node>&projectName=<project>&objectType=cube` → confirm no long-running job for the same model (match `objectId`). Corrected 2026-10-05: the v1 `GET /api/monitors/jobs` is deprecated, and there is no `PUBLISH` job type — `type` is one of `interactive` / `subscription` / `predictive_cache` / `realtime`. Cube-cache state (`GET /api/monitors/caches/cubes?clusterNode=<node>&projectIds=<id>`, `state.processing`) is the other signal.

If step 9 is unavailable on the tenant (Monitor Jobs privilege), fall back to: attempt a publish on a known-good small Mosaic model (canary) and confirm every table reaches `status:"completed"` within 60s (the per-table enum has no `loaded`).

## Helper-integration idea

Add `python3 skills/build-mosaic-model/scripts/build_mosaic.py preflight --project-id ... --datasource-id ... --dest-folder ... --mode [build|publish|migrate]` that runs the relevant subset above and prints PASS/FAIL per check. Today this is an ad-hoc script.

## Related

- `feedback_build_mosaic_session_leak.md` — why step 2 matters.
- `reference_strategy_project_loading.md` — step 3 details.
- `reference_mosaic_publish_path.md` — step 9 + publish specifics + DataType preconditions (don't attempt publish before column types are clean).
