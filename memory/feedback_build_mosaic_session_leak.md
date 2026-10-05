---
name: iServer session cap + one-process rule for Mosaic builds
description: The per-user-per-project interactive-session cap (8004cb0a / iServerCode -2147072486). Root cause found 2026-10-05 — the scripts "logged out" with DELETE /api/auth/login, which does not exist (404), so every run left its session open until the ~30-min idle timer. Logout is now POST /api/auth/logout. Still prefer one process (and one session) per pipeline; kill-sessions can disconnect stale connections with a monitoring privilege.
type: feedback
tags: [mosaic, build, publish, session-management, error-code]
---

## Root cause (found 2026-10-05)

Every script here ended its session with `DELETE /api/auth/login`. The REST API has no such operation — it answers **404** — so no run ever logged out, and each one held its project-interactive session until the idle timer (~30 min). Five or six quick commands filled the cap. The only logout is **`POST /api/auth/logout`**; `strategy_auth.sign_out()` now sends it for every session a script created (sessions shared with a browser or cached for reuse are left open on purpose). The older explanation below — "logout releases the token but not the iServer session" — was built on that 404 and is superseded; re-verify before relying on it.

## Rule — one session, one process

When automating an end-to-end Mosaic build, prefer not to chain `build_mosaic.py` subcommands as separate shell invocations (build → validate-model → publish → add-security-filter → api-call …). Each invocation signs in and opens a project-interactive session keyed to `X-MSTR-ProjectID`. With working logout this no longer piles up, but one process is still fewer logins, and a crashed run still holds its session until the idle timer.

**Pattern:** collapse the pipeline into one long-lived `requests.Session()` in one Python process that logs in once and reuses the session object for everything.

```python
s = requests.Session()
r = s.post(f'{BASE}/api/auth/login', json={...})
s.headers['X-MSTR-AuthToken'] = r.headers['X-MSTR-AuthToken']
s.headers['X-MSTR-ProjectID'] = PID
it = s.post(f'{BASE}/api/auth/identityToken')
s.headers['X-MSTR-IdentityToken'] = it.headers['X-MSTR-IdentityToken']
# ... every subsequent call uses s.* ...
s.post(f'{BASE}/api/auth/logout')   # at end — the only logout endpoint
```

## Failure signature

```
500 {"code":"ERR001","iServerCode":-2147072486,
     "message":"(Maximum number of interactive session per user for project exceeded
                while trying to login user <full name> to project <project name>.)"}
```

Modeling-Service wrapper returns the same condition with `8004cb0a`. If present, **stop retrying immediately** — every retry keeps the timeout window from starting. Wait the full 30 minutes from the LAST attempted project-scoped call.

## Why — iServer session ≠ auth token

- `main()` wraps dispatch in `try/finally: m.logout()` (`skills/build-mosaic-model/scripts/build_mosaic.py`, `main()`), which now sends `POST /api/auth/logout` and also discards any changeset left open.
- Project-scoped requests run in an iServer interactive session for that project; a session that is never logged out reaps on the ~30-min idle timer. (Until 2026-10-05 that was every session — see Root cause.)
- The cap is a project setting ("maximum interactive sessions per user"): the product default is 20; the cloud tenants observed here set about 5.
- **Which calls count:** anything touching `/api/objects/...`, `/api/model/...`, `/api/dataModels/...`, `/api/cubes/...`.
- **Which calls don't count:** `/api/projects`, `/api/datasources`, `/api/users`, `/api/auth/*`.

`kill-sessions` lists your open connections through the user-connection monitor (`GET /api/monitors/userConnections`) and disconnects them with `--yes` (`DELETE /api/monitors/userConnections/{id}`). That needs a monitoring/administration privilege; without it the tenant answers 403 and stale sessions end on the idle timer. Your browser sessions are connections too — filter with `--project` / `--idle-minutes` before `--yes`.

## How to apply — operational rules

1. **Never chain `build` → `publish` → `add-security-filter` → `set-acl` as separate shell invocations.** Even if each subcommand has its own try/finally logout, the project-interactive sessions accumulate at the iServer tier and won't reap in time. Use one of:
   - `build-from-config` subcommand (handles security_filter, acl, publish, certify in the same process — one session, clean exit).
   - A single ad-hoc Python block that imports `build_mosaic` as a module (or instantiates `MSTR` directly) and does build/publish/SF/ACL back-to-back inside a single `with` / try-finally. Do NOT `subprocess.run(...)` the helper repeatedly from that script — that re-opens a new session each time.
2. **Avoid `publish` entirely when the only consumer is the Trino layer.** For `connect_live` models, publish is a no-op. For `in_memory` models, check whether the downstream task actually needs the materialized cube (Trino query, dashboard, subscription) — if the user only needs the model to exist + security filter assigned, skip publish until asked.
3. **Save the model_id immediately after build and treat it as idempotent.** If you hit the cap between build and publish, wait ~30 min then re-invoke publish alone — don't re-run build.
4. **Suppress the classify preflight on known-Mosaic models.** In ad-hoc scripts, skip `classify_object_surface` and call `_mosaic_publish_verified()` directly when you already know the model is subType 779 (e.g., you just created it). One fewer project-scoped call = one fewer session.
5. **Use `describe-tables` (plural) for discovery.** It takes repeatable `--source instanceId:namespace:table` and does all describes in ONE login. Never loop `describe-table` (singular) from the shell.
6. **Proactively check open sessions before risky writes.** `GET /api/sessions` describes only the current session; to count your connections use `build_mosaic.py kill-sessions` (lists them; needs a monitoring privilege) or `GET /api/monitors/userConnections`.
7. **Order of operations to minimize cap pressure:** discovery (`list-datasources`, `list-namespaces`, `describe-tables` plural) → `build-from-config` with all post-build ops folded in → validate via Trino (separate, single session). Do not interleave `api-call` probes against `/api/model/...` between steps.

## Recovery when the cap is already hit

- Wait ~25–30 min for iServer to reap. There is NO fast recovery from a non-admin token.
- With a monitoring privilege: `build_mosaic.py kill-sessions --project "<project>"` lists them, `--yes` disconnects them.
- Without it, an admin can disconnect them (Monitors → User Connections, or the same REST calls).

## Build → publish sequencing is the #1 repeat offender

`build_mosaic.py build` already opens 4–6 project-scoped sessions (datasource resolution, describe-table × N, changeset open, commit, relationships changeset). A follow-on `build_mosaic.py publish --model-id ...` then issues a fresh `classify_object_surface()` → `GET /api/objects/{id}?type=3` — project-scoped, opens another session, trips the cap.

**Fix pattern:** do publish inside the same process as build. Do not exit Python between build and publish.

## Related

- `reference_strategy_project_loading.md` — confirms that session cap fires on project-scoped calls, not on `/api/auth/login`.
- `reference_mosaic_publish_path.md` ("Never fire both publish endpoints") — the OTHER publish failure mode (firing both publish endpoints concurrently); distinct iServerCode `-2147072194`.
- `feedback_mosaic_multi_db_connect_live.md` — multi-DB builds force `in_memory`, which forces publish, which is the session-cap fragile step.

## Helper-script features that implement this rule

- **`publish --skip-classify`** — skips the project-scoped `GET /api/objects/{id}?type=3` classification call. Use it when chaining build→publish in the same session on a known-Mosaic model; saves one project-scoped call against the cap.
- **`describe-tables` (plural)** — batch discovery inside one login. Replaces the N-login-per-table anti-pattern.
- **`build-from-config`** — runs build + security filters + ACL + publish + certify inside a single process, one login, one clean logout.

## Remaining helper-script gaps

- `kill-sessions` needs a monitoring privilege most operator accounts lack; its `--help` says so.
