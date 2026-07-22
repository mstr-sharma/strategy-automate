---
name: REST-call timeouts + connect_live warehouse-resume hang prevention
description: Every Strategy REST call in a long pipeline MUST carry a client-side timeout. A synchronous connect_live execute (POST /api/v2/cubes/{id}/instances) holds the HTTP connection open while an auto-suspended warehouse resumes — observed blocking 10+ min with zero output, indistinguishable from a crash. Un-timed-out requests + end-of-batch-only logging hid it. Fixes: default timeout in the MSTR wrapper, bounded best-effort pre-warm kept OFF the critical path, per-sub-step progress logging, idempotent serve-mode recovery.
type: feedback
tags: [mosaic, rest, timeout, hang, connect_live, warehouse, prewarm, publish, observability]
---

## Incident (2026-06-17, Studio tenant)

An in-memory build's optional "pre-warm the warehouse" step flipped the model to `connect_live` and issued a rollup execute (`POST /api/v2/cubes/{id}/instances`). The Snowflake warehouse was auto-suspended. iServer held the HTTP connection open synchronously while the warehouse resumed; the client `requests` call had **no `timeout=`**, so it blocked **10+ minutes with zero log output** before being killed. Progress was logged only AFTER all four rollup views finished, so a hang inside view #1 was invisible — identical-looking to a crash or an infinite loop. Killing the run also stranded the model in `connect_live` (the flip-back never ran).

The 10 minutes were not totally wasted (the warehouse came up hot), but the correct path is to never let this hang happen.

## Root causes

1. **Un-timed-out HTTP call.** `requests` with no `timeout=` blocks until the server responds or the socket drops. A synchronous server-side wait (warehouse resume, long query) becomes an unbounded client hang.
2. **connect_live execute is synchronous and warehouse-sensitive.** Unlike publish (async — fire `/api/cubes` then poll), a `connect_live` cube/report execute generates live warehouse SQL and iServer holds the request while Snowflake resumes (first-query latency ~1–2 min, occasionally much longer). Using it as a "pre-warm" can hang on the very resume it is meant to trigger — i.e. the pre-warm is the slowest, most fragile call in the pipeline, and it sat on the critical path.
3. **Coarse-grained logging.** One summary line after a batch of sub-operations gives no signal about which sub-op is stuck.
4. **Serve-mode flip with no kill-safety.** The pre-warm flipped to `connect_live` and relied on a later flip-back; a hard kill (or crash) during the window strands the model in the wrong serve mode.

## Rules (apply to all Strategy automation)

1. **Every REST call carries a timeout.** Use a `(connect, read)` tuple, e.g. `(15, 300)`. Landed as a default in the `MSTR` HTTP wrapper (`skills/build-mosaic-model/scripts/build_mosaic.py`) via `kw.setdefault("timeout", DEFAULT_HTTP_TIMEOUT)`, overridable per call and via the `MSTR_HTTP_TIMEOUT` env var. No call may hang forever. Ad-hoc driver/finisher scripts that call `requests` directly must do the same.
2. **Pre-warm is best-effort and OFF the critical path.** The publish job itself resumes the warehouse, so budgeting execute-probe polling (10–15 min, see [[reference_mosaic_publish_path]]) is sufficient on its own. If you do pre-warm, time-box it (short read timeout + at most one or two tries) and continue on failure — never let pre-warm block the build. Prefer a lightweight catalog/sample query or a short-timeout connect_live probe over an unbounded synchronous execute.
3. **Log before AND after every slow sub-operation.** Emit "→ executing view X" before the call and "✓ view X: N rows" after, so a stuck step is identifiable in seconds. Never hide N sequential network calls behind a single end-of-batch summary.
4. **Run possibly-blocking ops in the background with a bounded monitor — never a no-timeout foreground call.** A 10-minute foreground call also blows the harness's own tool-call budget; background + a milestone monitor (or `until grep` task) gives visibility and a kill switch.
5. **Serve-mode flips must be idempotently recoverable.** Minimize time in a temporary serve mode; guarantee flip-back in `finally`; and make the RESUME path detect the live `dataServeMode` and restore the target mode (GET the model, see `connect_live`, flip to `in_memory`) so a killed/crashed run is trivially repaired. Better yet, prefer not to flip at all — publish + execute-probe needs no connect_live detour.

## Cross-refs

- [[reference_mosaic_publish_path]] — warehouse-resume-makes-publish-look-stalled + the execute-probe completion signal (the async path that does NOT hang).
- [[feedback_build_mosaic_session_leak]] — one-session/one-process; a killed mid-pipeline process also parks an iServer interactive session until the ~30-min reap.
