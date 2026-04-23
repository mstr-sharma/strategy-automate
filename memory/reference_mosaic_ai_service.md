---
name: Mosaic AI modeling service — automated PK detection, relationship inference, lookup-table and multi-form discovery
description: The Studio UI has a full AI service that automates modeling decisions our helpers currently do heuristically. Endpoints under `/api/aiservice/*` cover primary-key detection, relationship inference, lookup-table selection, multi-form-attribute discovery, metric recommendations, object linking, and model overview text. Use these as the primary modeling source of truth; fall back to heuristics only when the AI is unavailable or returns low confidence.
type: reference
---

## Discovered endpoints

All captured from Studio UI "Building your Mosaic Model..." flow and subsequent edits. Verified `POST` with model-specific bodies. All return 200 with recommendation payloads or are fire-and-forget.

| Endpoint | Purpose | Notes |
|---|---|---|
| `POST /api/aiservice/model/tables/primaryKeys` | Predict PK column per table | Input: workspace/pipeline or table refs. Output: inferred PK column per table with confidence. |
| `POST /api/aiservice/model/objects/linking` | Infer relationships between unlinked objects | Input: model id. Returns candidate parent→child relationships with join tables. |
| `POST /api/aiservice/model/objects/lookupTable` | Pick the best lookup table for each attribute | Input: attribute refs. Output: per-attribute lookup-table recommendation. |
| `POST /api/aiservice/model/objects/multiFormAttributes` | Detect multi-form attribute candidates | Called per-table. Identifies when an ID column plus descriptor columns should be folded into a single multi-form attribute instead of N separate attributes. Solves the "locale-variant explosion" pain. |
| `POST /api/aiservice/model/objects/relationships` | Suggest additional relationships | Post-build refinement; different from `linking` which is initial. |
| `POST /api/aiservice/model/objects/metrics/recommendations` | Suggest derived metric formulas | Fires when opening the metric editor. |
| `POST /api/aiservice/model/overview` | Generate executive-summary description | Returns markdown-formatted business description. Stored back on the model (`executiveSummary` field). |

Additional AI-adjacent endpoints:
- `POST /api/nuggets/status/query` — AI indexing status.
- `GET /api/iams` — Intelligent Agent Management Service enumeration.
- `POST /api/aiservice/...` (others) — probe via `openapi-search` on the running tenant; this family grows fast.

## When the UI calls them

Captured sequence during auto-model-build ("Building your Mosaic Model..."):

```
POST /api/dataServer/workspaces/{wsId}/pipelines            # workspace + pipelines first
POST /api/model/batch?allowPartialSuccess=true              # imports metadata shells
POST /api/aiservice/model/tables/primaryKeys                # AI picks PKs
POST /api/aiservice/model/objects/linking                   # AI infers relationships
POST /api/model/batch?allowPartialSuccess=false             # commits structural edits
POST /api/aiservice/model/objects/lookupTable               # AI picks lookup tables
POST /api/aiservice/model/objects/multiFormAttributes       # AI folds descriptor columns into forms (×N tables)
```

Pattern: hydrate metadata → call AI service → commit structural edits → call more AI services for finer decisions.

## Recommended usage from our helpers

`build_mosaic.py build` currently duplicates much of this work heuristically:
- Shared-column inference → duplicates `POST /api/aiservice/model/objects/linking`
- Column-name role classification → duplicates `POST /api/aiservice/model/tables/primaryKeys` and `POST /api/aiservice/model/objects/multiFormAttributes`
- Lookup-table selection heuristic → duplicates `POST /api/aiservice/model/objects/lookupTable`

Migration path:

1. In `build` after table hydration, call the AI services with the workspace/pipeline refs.
2. Treat their responses as the default build plan.
3. Apply the existing heuristics ONLY for columns the AI didn't return (fallback), or when the AI's confidence is below a threshold.
4. Allow the user to override both via `--dictionary` / `--erd`.

The existing preflight check script (`preflight_model_check.py`, invoked by the `build-mosaic-model` skill) should also consult `POST /api/aiservice/model/objects/multiFormAttributes` before emitting the "LOCALE_COLUMN_EXPLOSION" ERROR — the AI may already be handling it.

## Payload shapes (pending capture)

Bodies are not captured from MCP (extension returns only URL/status). Use DevTools "Copy as cURL" on one successful call per endpoint to recover the body shape, then document here. Until then:

- All endpoints expect JSON bodies.
- All run in the context of an existing workspace + changeset (the UI opens both before calling AI endpoints).
- Expect responses with `recommendations[]` or `suggestions[]` lists; each item carries a confidence score and the target objectIds.

## Governance / safety

- The AI service calls DO produce persisted metadata changes (via the subsequent batch calls). Treat them as write operations for audit purposes even though the AI endpoint itself is read-shaped.
- The exec summary is AI-generated text — do not rely on it for automation decisions, only for human-readable model descriptions.
- `cognitiveSearchFlags=1` on `/api/searches/results` enables semantic search backed by the same indexing layer. Useful when the user types "find models about supplier risk" — the cognitive index matches beyond literal tokens.

## Fallback / robustness

- If `/api/aiservice/*` returns non-2xx, fall back to the heuristic build plan silently. Log but don't fail.
- Some tenants have `/api/iams` disabled or AI services rate-limited. Check feature flags: `GET /api/v2/configurations/featureFlags` returns the tenant's AI capability matrix.
- The `GET /api/telemetry/usage-insights/model` endpoint returned 404 on our tenant — treat telemetry/usage-insights features as tenant-optional.
