---
name: build_mosaic.py leaks Intelligence Server sessions
description: The helper creates a session via POST /api/auth/login but never calls DELETE /api/auth/login on exit. Running many subcommands back-to-back trips the project's interactive-session cap with code 8004cb0a, blocking all subsequent modeling-service writes for ~30 minutes until sessions time out.
type: feedback
---

**Observed 2026-04-23.** After ~10–15 `build_mosaic.py` invocations against `studio.strategy.com` (`build`, `api-call`, `delete-model`, `publish`, `add-security-filter`, etc.), subsequent calls returned:

```
500 {"code":"ERR001","iServerCode":-2147072486,
     "message":"(Maximum number of interactive session per user for project exceeded
                while trying to login user <operator> to project Shared Studio.)"}
```

Modeling-Service wrapper returns the same with `8004cb0a`. Each helper run creates a Session + X-MSTR-AuthToken; `MSTR.logout()` exists in the script (`scripts/build_mosaic.py` line 199) but **no subcommand ever calls it**. The session then ages out after `timeout=1800s` (30 min, from `/api/sessions`).

**How to apply:**
- Fix: every subcommand in `cmd_*` should finish with `try/finally: m.logout()` or the top-level dispatcher should wrap execution in a try/finally that calls `m.logout()`. Do NOT swallow logout failures — stderr is fine, but log them so session leaks are visible.
- Workaround today: when writing ad-hoc Python against the Modeling Service, always end with `s.delete(f"{BASE}/api/auth/login")`. When chaining many helper calls, pause or script batched operations inside a single Python process so only one session is opened.
- If the cap is already hit, the only recovery is waiting ~30 minutes for timeout — there is no admin endpoint to force-clear a single user's sessions available to a non-admin token.
- This failure mode masks itself as a "changeset won't open" or "attribute PATCH returns 500"; check `iServerCode == -2147072486` or message containing "Maximum number of interactive session per user" before retrying.

**Related:** `reference_strategy_project_loading.md` notes that the session cap fires on project-scoped calls, not `/api/auth/login`. Confirmed again here — `GET /api/projects` succeeds under the cap, `POST /api/model/changesets` does not.

## 2026-04-23 update — partial fix landed

`main()` already wraps dispatch in `try/finally: m.logout()` (verified at script line 2703). So the Python-level token IS released on clean exit. The remaining leak source is that **project-scoped requests open a separate IServer interactive session** that the DELETE /api/auth/login cleanup does not immediately tear down — iServer reaps on its own ~30 min timer. This is why repeat `describe-table` calls still burn slots even though logout is called.

**New subcommands added (same commit as this memory update):**
- `describe-tables` (plural) — takes repeatable `--source instanceId:namespace:table`, does all describes in ONE login. Replaces the N-login-per-table pattern for preflight/discovery.
- `kill-sessions` — best-effort login/logout loop to reap stale tokens owned by this user. Does NOT clear project-interactive sessions held by the iServer; those still need the ~30 min reap.

**Operational rule:** whenever preflighting >1 table or running any multi-step discovery, use `describe-tables` (or write a single-process Python script that logs in once, does everything, logs out). Never loop `describe-table` from shell. Never chain `auth-probe → list-datasources → list-namespaces → list-tables → describe-table × N` in separate invocations on Studio — it will cap the user within 5-6 subcommands.

**Still missing:** an admin-scope force-close endpoint. If you hit the cap mid-workflow, there is no fast recovery; wait or contact a platform admin with `Bypass ACL` to reset the user.
