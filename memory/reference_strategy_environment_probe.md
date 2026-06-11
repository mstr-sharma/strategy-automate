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
   `GET /api/projects` → confirm the target project's `status==0` (loaded). `status==1` means unloaded; load via `POST /api/projects/{id}?action=load` (admin).
4. **Datasource connectivity**:
   `POST /api/datasources/{id}/testConnection` per datasource in use → expect 200.
5. **Feature flags**:
   `GET /api/v2/configurations/featureFlags` → confirm in-memory publish / AI service / Trino federation are enabled on this tenant.
6. **Modeling-service identity token**:
   `POST /api/auth/identityToken` → expect 200 + `X-MSTR-IdentityToken`. Required for Mosaic writes; not required for classic/project writes.
7. **Gateways + drivers** (only before new datasource creation):
   `GET /api/gateways`, `GET /api/drivers` → confirm the target database driver is installed.
8. **Destination folder writeable** (only before model/object creation):
   `GET /api/folders/{destFolderId}` → confirm `acg` includes write bits; `POST /api/folders/` is a preflight alternative.
9. **Publish queue sanity** (only before in-memory Mosaic publish):
   `GET /api/monitors/jobs?jobTypes=PUBLISH` → confirm no stuck publish for the same model.

If step 9 is unavailable on the tenant, fall back to: attempt a publish on a known-good small Mosaic model (canary) and confirm it reaches `status:"loaded"` within 60s.

## Helper-integration idea

Add `python3 skills/build-mosaic-model/scripts/build_mosaic.py preflight --project-id ... --datasource-id ... --dest-folder ... --mode [build|publish|migrate]` that runs the relevant subset above and prints PASS/FAIL per check. Today this is an ad-hoc script.

## Related

- `feedback_build_mosaic_session_leak.md` — why step 2 matters.
- `reference_strategy_project_loading.md` — step 3 details.
- `reference_mosaic_publish_path.md` — step 9 + publish specifics + DataType preconditions (don't attempt publish before column types are clean).
