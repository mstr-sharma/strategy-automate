---
name: Use one shared requests.Session across all Mosaic build operations
description: Every CLI invocation of build_mosaic.py opens a fresh iServer interactive project session that parks for ~30 min even after DELETE /api/auth/login. Chaining many small commands trips the per-user-per-project cap (8004cb0a) long before reap. Do the whole pipeline (relationships → publish → SF → assign → validate) inside one long-lived requests.Session.
type: feedback
---

## Rule

When automating a Mosaic build end-to-end, do NOT chain `build_mosaic.py` subcommands as separate shell invocations (build → validate-model → publish → add-security-filter → api-call …). Each one logs in, opens an iServer project session keyed to `X-MSTR-ProjectID`, and that session stays parked on the server for ~30 minutes.

**How to apply:** Collapse the post-build steps (relationships via PUT, publish, SF create + commit, SF member assignment, Tommy-style user lookups, validation queries) into one Python script that opens one `requests.Session()` at the top and reuses it for everything. Pattern:

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

## Why

Observed on 2026-04-23 / studio.strategy.com: after ~10–12 `build_mosaic.py` invocations in 15 minutes (discovery + describe + build + validate-model + api-call × N + publish × 3), the next call returned 500 `8004cb0a` "Maximum number of interactive session per user for project exceeded." The `kill-sessions` helper only reaps auth tokens — its own docstring (`build_mosaic.py:356`) says so — and returned `killed=0` even while we were capped. Only options then are (a) wait ~25–30 min for iServer to reap, or (b) use an admin account to force-kill via the monitors endpoints. Neither is acceptable mid-build.

The existing `feedback_build_mosaic_session_leak.md` covered the symptom. This one codifies the preventive rule: **one session, one script**, not N CLI calls.

## How to apply (operational triggers)

- If a build is expected to need more than ~4 follow-up operations, write a single Python driver that logs in once and does rels + publish + SF + assign inside that one session.
- Always include a retry-with-backoff login wrapper that treats `8004cb0a` as transient — but the wrapper should be unnecessary when you're already using one session.
- When probing endpoints or pipelines in the same session, reuse the same session object; never create a new `requests.Session()` per helper call.
- When the retry loop backs off, sleep in 30s increments and give up after ~15 min — longer means you're waiting for reap anyway.

## What this does NOT fix

- The underlying iServer session leak. Strategy has not provided a cheap "close interactive project session" endpoint for non-admin users on Strategy ONE Cloud. If the cap is tripped by other processes or prior agent runs, you still have to wait.
- Admin `kill-sessions` via `/api/monitors/...` is privileged and not available in arsharma-style operator accounts on studio. Don't try it blindly.
