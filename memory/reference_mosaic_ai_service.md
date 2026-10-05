---
name: Mosaic AI modeling service — automated PK detection, relationship inference, lookup-table and multi-form discovery
description: The Studio UI calls an AI service (captured in browser traces) under `/api/aiservice/model/*` for primary-key detection, relationship inference, lookup-table selection, multi-form-attribute discovery, metric recommendations, object linking and model overview text. None of these paths is in the tenant's OpenAPI spec, not even as internal (checked 2026-10-05) — treat them as unsupported UI internals: optional hints behind a heuristic fallback, never the primary source of truth.
type: reference
---

> **Status (corrected 2026-10-05):** the 2026 tenant spec (1,190 paths) has **no** `/api/aiservice/model/*` path and no `/api/model/batch`, public or internal — its only `aiservice` path is an internal dashboard-chat call. The workspace/pipeline calls in the trace below (`/api/dataServer/workspaces/...`) ARE public. Earlier versions of this note told helpers to make these AI calls the primary modeling source of truth; don't — they are UI internals that can vanish between builds. Use the documented Modeling Service for writes, and treat AI suggestions as optional input.

## Discovered endpoints (UI capture; not in the spec)

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
- `POST /api/nuggets/status/query` — AI indexing status (internal, tag Agent).
- `GET /api/iams` — **identity-provider configurations** (OAuth/IdP objects: vendor `IDPTYPE_OKTA` / `IDPTYPE_AZUREAD` / …, `initAuthUrl`, `tokenUrl`, `clientId`; internal, needs Configure Security). Not AI-related — earlier text called it an "Intelligent Agent Management Service" (corrected 2026-10-05).
- `POST /api/aiservice/...` (others) — `openapi-search` will not find them (absent from the spec); only a fresh UI capture shows what a tenant currently calls.

## When the UI calls them

Captured sequence during auto-model-build ("Building your Mosaic Model..."):

```
POST /api/dataServer/workspaces/{wsId}/pipelines            # workspace + pipelines first (public in the spec)
POST /api/model/batch?allowPartialSuccess=true              # imports metadata shells (absent from the spec)
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

Migration path (downgraded 2026-10-05 — the endpoints are not a supported contract):

1. Keep the heuristics (plus `--dictionary` / `--erd` overrides) as the build plan.
2. Optionally, behind a flag, call an AI endpoint after table hydration and use its answer only as a suggestion to compare against the heuristic plan.
3. Treat any non-2xx (including 404 on a tenant that never had the path) as "no suggestion", not as an error.

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
- AI services may be disabled or rate-limited per tenant. Check feature flags: `GET /api/v2/configurations/featureFlags` (internal; the v1 `/api/configurations/featureFlags` is deprecated) returns the tenant's capability matrix. (`/api/iams` is identity-provider config, not an AI switch.)
- The `GET /api/telemetry/usage-insights/model` endpoint returned 404 on our tenant — treat telemetry/usage-insights features as tenant-optional.
