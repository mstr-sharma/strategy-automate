---
name: build_mosaic.py leaks Intelligence Server sessions
description: The helper creates a session via POST /api/auth/login but never calls DELETE /api/auth/login on exit. Running many subcommands back-to-back trips the project's interactive-session cap with code 8004cb0a, blocking all subsequent modeling-service writes for ~30 minutes until sessions time out.
type: feedback
---

**Observed 2026-04-23 on a Strategy ONE Cloud tenant (studio.strategy.com).** After ~10–15 `build_mosaic.py` invocations (`build`, `api-call`, `delete-model`, `publish`, `add-security-filter`, etc.), subsequent calls returned:

```
500 {"code":"ERR001","iServerCode":-2147072486,
     "message":"(Maximum number of interactive session per user for project exceeded
                while trying to login user <full name> to project <project name>.)"}
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

## 2026-04-23 update — build → publish sequencing is the #1 repeat offender

**Pattern observed (Strategy ONE Cloud tenant, second session-cap incident in the same day):**
`build_mosaic.py build …` (successful, commits, returns model_id)
→ within ~2 min, `build_mosaic.py publish --model-id …`
→ `publish` starts by calling `classify_object_surface()` which issues `GET /api/objects/{id}?type=3` — this is **project-scoped** and opens a fresh interactive IServer session each helper invocation.
→ Because the build already opened 4–6 project-scoped sessions (datasource resolution, describe-table × N, changeset open, commit, relationships changeset), the publish's classify call trips `-2147072486` = `8004cb0a`. Recovery is a ~30-min wait.

**Why:** the default project interactive-session cap on most Strategy ONE Cloud tenants is 5 per user, and iServer does not reap them on `DELETE /api/auth/login` — only on a 30-min idle timer. Each helper invocation that touches `/api/objects/...`, `/api/model/...`, `/api/dataModels/...`, or `/api/cubes/...` counts; `/api/projects`, `/api/datasources`, `/api/users`, `/api/auth/*` do NOT count.

**How to apply — operational rules when you're already past discovery:**
1. **Never chain `build` → `publish` → `add-security-filter` → `set-acl` as separate shell invocations.** Even if each subcommand has its own try/finally logout, the project-interactive sessions accumulate at the iServer tier and won't reap in time. Use one of:
   - `build-from-config` subcommand (handles security_filter, acl, publish, certify in the same process — one session, clean exit).
   - A single ad-hoc Python block that imports `build_mosaic` as a module (or instantiates `MSTR` directly) and does build/publish/SF/ACL back-to-back inside a single `with`/try-finally. Do NOT `subprocess.run(...)` the helper repeatedly from that script — that re-opens a new session each time.
2. **Avoid `publish` entirely when the only consumer is the Trino layer.** For `connect_live` models, publish is a no-op. For `in_memory` models, check whether the downstream task actually needs the materialized cube (Trino query, dashboard, subscription) — if the user only needs the model to exist + security filter assigned, skip publish until the user asks for it.
3. **Save the model_id immediately after build and treat it as idempotent.** If you hit the cap between build and publish, wait ~30 min then re-invoke publish alone — don't re-run build.
4. **Suppress the classify preflight on known-Mosaic models.** In ad-hoc scripts, skip `classify_object_surface` and call `_mosaic_publish_verified()` directly when you already know the model is subType 779 (e.g., you just created it). One fewer project-scoped call = one fewer session.
5. **Proactively probe session count before risky writes.** `GET /api/sessions` is not project-scoped; if you see a high session count and a long-running `dateCreated`, pause.
6. **Order of operations to minimize cap pressure**: discovery (list-datasources, list-namespaces, describe-tables plural) → build-from-config with all post-build ops folded in → validate via Trino (separate, single session). Do not interleave `api-call` probes against `/api/model/...` between the steps.

**Failure signature to grep for:** `iServerCode":-2147072486` OR `"Maximum number of interactive session per user"`. If present, **stop retrying immediately** — every retry keeps the timeout window from starting. Wait the full 30 minutes from the LAST attempted project-scoped call.

**Helper-script gap (known):** `publish` subcommand does not accept a `--skip-classify` flag. Adding one is the single highest-value hardening; until then, route through `build-from-config` or an inline Python block.
