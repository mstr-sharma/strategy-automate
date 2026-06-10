---
name: iServer session cap + one-process rule for Mosaic builds
description: Chaining build_mosaic.py subcommands as separate shell invocations trips the per-user-per-project interactive-session cap (8004cb0a / iServerCode -2147072486). DELETE /api/auth/login releases the auth token but NOT the iServer project-interactive session, which reaps on a ~30-min idle timer. Preventive rule — do the whole pipeline (discovery → build → relationships → publish → SF → assign → validate) inside ONE long-lived requests.Session in ONE Python process.
type: feedback
tags: [mosaic, build, publish, session-management, error-code]
---

## Rule — one session, one process

When automating an end-to-end Mosaic build, do NOT chain `build_mosaic.py` subcommands as separate shell invocations (build → validate-model → publish → add-security-filter → api-call …). Each invocation opens an iServer project-interactive session keyed to `X-MSTR-ProjectID`, and that session stays parked on the server for ~30 minutes even after a clean logout.

**Pattern:** collapse the pipeline into one long-lived `requests.Session()` in one Python process that logs in once and reuses the session object for everything.

```python
s = requests.Session()
r = s.post(f'{BASE}/api/auth/login', json={...})
s.headers['X-MSTR-AuthToken'] = r.headers['X-MSTR-AuthToken']
s.headers['X-MSTR-ProjectID'] = PID
it = s.post(f'{BASE}/api/auth/identityToken')
s.headers['X-MSTR-IdentityToken'] = it.headers['X-MSTR-IdentityToken']
# ... every subsequent call uses s.* ...
s.delete(f'{BASE}/api/auth/login')   # at end
```

## Failure signature

```
500 {"code":"ERR001","iServerCode":-2147072486,
     "message":"(Maximum number of interactive session per user for project exceeded
                while trying to login user <full name> to project <project name>.)"}
```

Modeling-Service wrapper returns the same condition with `8004cb0a`. If present, **stop retrying immediately** — every retry keeps the timeout window from starting. Wait the full 30 minutes from the LAST attempted project-scoped call.

## Why — iServer session ≠ auth token

- `main()` already wraps dispatch in `try/finally: m.logout()` (`skill/scripts/build_mosaic.py`, `main()`). The Python-level auth token IS released on clean exit.
- BUT **project-scoped requests open a separate iServer interactive session** that `DELETE /api/auth/login` does not immediately tear down. iServer reaps on its own ~30-min idle timer.
- The default project interactive-session cap on most Strategy ONE Cloud tenants is ~5 per user per project.
- **Which calls count:** anything touching `/api/objects/...`, `/api/model/...`, `/api/dataModels/...`, `/api/cubes/...`.
- **Which calls don't count:** `/api/projects`, `/api/datasources`, `/api/users`, `/api/auth/*`.

The `kill-sessions` helper only reaps auth tokens (its docstring says so — `cmd_kill_sessions()` in `skill/scripts/build_mosaic.py`). It cannot reap iServer project-interactive sessions from a non-admin token.

## How to apply — operational rules

1. **Never chain `build` → `publish` → `add-security-filter` → `set-acl` as separate shell invocations.** Even if each subcommand has its own try/finally logout, the project-interactive sessions accumulate at the iServer tier and won't reap in time. Use one of:
   - `build-from-config` subcommand (handles security_filter, acl, publish, certify in the same process — one session, clean exit).
   - A single ad-hoc Python block that imports `build_mosaic` as a module (or instantiates `MSTR` directly) and does build/publish/SF/ACL back-to-back inside a single `with` / try-finally. Do NOT `subprocess.run(...)` the helper repeatedly from that script — that re-opens a new session each time.
2. **Avoid `publish` entirely when the only consumer is the Trino layer.** For `connect_live` models, publish is a no-op. For `in_memory` models, check whether the downstream task actually needs the materialized cube (Trino query, dashboard, subscription) — if the user only needs the model to exist + security filter assigned, skip publish until asked.
3. **Save the model_id immediately after build and treat it as idempotent.** If you hit the cap between build and publish, wait ~30 min then re-invoke publish alone — don't re-run build.
4. **Suppress the classify preflight on known-Mosaic models.** In ad-hoc scripts, skip `classify_object_surface` and call `_mosaic_publish_verified()` directly when you already know the model is subType 779 (e.g., you just created it). One fewer project-scoped call = one fewer session.
5. **Use `describe-tables` (plural) for discovery.** It takes repeatable `--source instanceId:namespace:table` and does all describes in ONE login. Never loop `describe-table` (singular) from the shell.
6. **Proactively probe session count before risky writes.** `GET /api/sessions` is not project-scoped; if you see a high session count and a long-running `dateCreated`, pause.
7. **Order of operations to minimize cap pressure:** discovery (`list-datasources`, `list-namespaces`, `describe-tables` plural) → `build-from-config` with all post-build ops folded in → validate via Trino (separate, single session). Do not interleave `api-call` probes against `/api/model/...` between steps.

## Recovery when the cap is already hit

- Wait ~25–30 min for iServer to reap. There is NO fast recovery from a non-admin token.
- `kill-sessions` reaps auth tokens only; returns `killed=0` on the project-interactive sessions that matter.
- A platform admin with `Bypass ACL` privilege can force-reset the user's sessions via `/api/monitors/...`, but that is a privileged operation and not available to typical operator accounts.

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

- `kill-sessions` does not attempt to close project-interactive sessions — it can't, without admin privilege. `--help` output should say this more loudly; some operators still expect it to fix a capped state.
