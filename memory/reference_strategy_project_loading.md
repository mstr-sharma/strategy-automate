---
name: Strategy project loading + session cap gotchas
description: Two operational gotchas that quietly break Strategy automation scripts — projects listed by /api/projects that aren't actually loaded on any Intelligence Server, and the per-user interactive session cap that logs succeed under but every subsequent call fails.
type: reference
---

## Gotcha 1 — `/api/projects` lists unloaded projects

Symptom: `GET /api/projects` returns a project (e.g., `MicroStrategy One U12 Tutorial`, id `08BCDC39B04BC97FCCA626B40C1BCCFF`) with status `0`; every subsequent call against that project ID fails with:

```
404 ERR001 iServerCode -2147209151
There are no Intelligence Servers in the cluster with the project <ID> available.
It may be because (1) the projects are not loaded in the Intelligence Servers; (2) the projects are idle.
```

**Why:** `/api/projects` enumerates metadata-visible projects; project loading is a separate runtime operation. On Strategy Cloud tenants an admin can idle projects without removing them from metadata, so the listing stays.

**How to handle:**
- Always probe a project before using it: `GET /api/projects/{id}/settings` or `GET /api/searches/results?type=4&limit=1` (with `X-MSTR-ProjectID`). If either returns the `-2147209151` code, surface it to the user — don't retry.
- Admin-only: `POST /api/admin/projects/{id}` or `POST /api/monitors/projects/{id}/nodes/{node}/activate` to load. Without admin privs these return 401 HTML.
- Helper pattern: add a `probe_project(m, project_id)` utility to `build_mosaic.py` that returns `(loaded: bool, message: str)` before any script kicks off work.

## Gotcha 2 — Interactive session cap per user per project

Symptom: every `/api/datasources`, `/api/searches`, etc. returns `500 ERR001`:

```
(Maximum number of interactive session per user for project exceeded
 while trying to login user <User> to project <Project>.)
```

**Why:** Strategy Cloud enforces a governance cap. Every `POST /api/auth/login` creates a new session that consumes a slot; idle sessions remain until TTL. Iterative debug loops (write script, run, fix bug, re-run) burn through the slots fast because every run makes a fresh login.

**How to handle:**
- **Always `DELETE /api/auth/login` on exit.** Wrap scripts in `try/finally` and call `m.logout()` even on exceptions.
- Reuse the token within a run — don't re-login per call.
- If hit, either wait 5–10 minutes for TTL, or have an admin run `DELETE /api/sessions/{sessionId}` for your orphan sessions.
- The `build_mosaic.py` helper class (`MSTR`) already has `logout()`. Consuming scripts must call it — current failure mode is that a mid-script exception skips the logout and leaks the session.

## Contrast: `/api/auth/login` succeeds at session-cap

The cap only fires on project-scoped operations. The initial `/api/auth/login` returns `204` with tokens even when you're over the cap. The symptom only appears on the first call that requires the session to attach to a project — misleading because you see `auth-probe` succeed but the next call fails. Do not treat successful login as proof of a working session.
