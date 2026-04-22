---
name: Mosaic model batch API — bundled operations, partial success, HTTP 207
description: The Studio UI performs most model edits through `POST /api/model/batch`, bundling many sub-operations into one request with partial-success semantics. The endpoint returns HTTP 207 Multi-Status when any sub-op fails under `allowPartialSuccess=true`. Our helpers should migrate from per-object PUT/POST loops to the batch surface for performance and to match the UI's contract.
type: reference
---

## The endpoint

```
POST /api/model/batch?allowPartialSuccess={true|false}&showChanges={true|false}
Headers: X-MSTR-MS-Changeset: <cs>
Content-Type: application/json
```

Body (pending full capture — UI doesn't expose request bodies via MCP capture):

- A list of sub-operations, each with:
  - `op`: the operation name (create, update, delete, addRelationship, etc.)
  - `path`: the target object's location (JSON-Pointer-ish)
  - `value`: the payload for that sub-op
- Each sub-op can target any object class (attribute, fact metric, metric, relationship, table, filter).

Response:
- `HTTP 200` when all sub-ops succeed.
- `HTTP 207 Multi-Status` when `allowPartialSuccess=true` and some sub-ops failed — body contains per-op status codes and error bodies. Clients must iterate results and handle partial failure.
- `HTTP 400/500` when `allowPartialSuccess=false` and any sub-op fails — entire batch rolled back.

## Two modes observed in the UI

| Mode | When the UI uses it | Our helpers should |
|---|---|---|
| `allowPartialSuccess=true&showChanges=true` | Non-structural bulk metadata edits (rename, describe, format updates). Example: the 4 model-linking batch calls returned 207 meaning some sub-ops failed gracefully. | Use for batch-edit operations where best-effort is acceptable. Log the 207 response body so failed sub-ops are visible. |
| `allowPartialSuccess=false&showChanges=true` | Structural / cross-object edits where atomicity matters (relationship creation, attribute form binding). | Use when the post-state is invalid without all ops succeeding. |

`showChanges=true` returns the diff applied per sub-op (what changed on each object). `showChanges=false` is fire-and-forget — shorter response but harder to verify. The UI uses `showChanges=true` in every captured call.

## Observed throughput

In the auto-link capture (UI "Add Models" → parent):
- 4 batch calls in quick succession.
- 3 returned `207` (partial success).
- 1 returned `200`.

In intra-model join (user drags to join tables):
- 3 consecutive `POST /api/model/batch?allowPartialSuccess=false&showChanges=true` (200 each).

Distinct-count / cardinality profiling is NOT in the batch — those are separate `GET /pipelines/.../distinctCount` calls that run in parallel to batch writes.

## Why our helpers should migrate

Current `build_mosaic.py build` makes N+M+P separate POSTs per N attributes, M metrics, P relationships — each inside one changeset. That's slow and each per-op 500 kills the whole build. With batch:

1. One changeset.
2. One batch request with all ops.
3. Response tells us which specific sub-ops failed (if `allowPartialSuccess=true`) or rolls back atomically (if `=false`).

Specifically for **relationships**, batch replaces the problematic `PUT /attributes/{id}/relationships` which has "replaces full list" semantics (documented footgun in `reference_mosaic_rest_gotchas.md`). Batch sub-ops appear to be per-relationship add/remove, not per-child replace — no risk of wiping other parents.

## Migration plan

1. Add a helper `build_mosaic.batch_call(m: MSTR, cs: str, ops: list[dict]) -> list[dict]` that POSTs and parses 207 responses.
2. Rewrite `cmd_build`'s per-object loops to accumulate a `pending_ops` list and flush via one `batch_call`.
3. Rewrite the relationship pass to use `op: "addRelationship"` sub-ops inside batch, rather than PUT.
4. Keep the existing per-object paths as fallbacks for tenants where batch is disabled (probe via `GET /api/v2/configurations/featureFlags`).

## HTTP 207 handling

```python
def parse_batch_response(resp):
    """Parse a 200/207 batch response into per-op results."""
    if resp.status_code not in (200, 207):
        raise RuntimeError(f"batch failed: {resp.status_code} {resp.text[:400]}")
    body = resp.json()
    # Expected shape (to be verified with a captured body):
    #   {"results": [{"status": 200, "path": "...", "response": {...}}, {"status": 400, "error": {...}}]}
    results = body.get("results") or body.get("ops") or body.get("operations") or []
    passed = [r for r in results if 200 <= r.get("status", 500) < 300]
    failed = [r for r in results if r not in passed]
    return passed, failed
```

Fill in the exact response shape after capturing a batch body (use Chrome DevTools "Copy as cURL" on a UI batch call and paste the response JSON here).

## Open questions

- **Exact op vocabulary.** What sub-op names are valid? Confirmed pattern: create-like ops map to the same endpoints as per-object POSTs but inside the batch. The full list needs a DevTools capture.
- **Changeset interaction.** A batch inside a changeset behaves atomically at the changeset-commit boundary. What happens if you `allowPartialSuccess=true` but then commit the changeset — do the failed sub-ops' partial effects roll back or persist?
- **Rebase semantics with batch.** `POST /api/model/changesets/{cs}/operations?operationType=rebase` rebases the changeset onto a new model head. Batch ops inside a rebased changeset presumably get replayed — need to verify.
