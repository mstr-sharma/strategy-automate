---
name: Mosaic UI internal REST endpoints
description: Endpoints the Studio / Admin & Modeling UI uses that are not in the public OpenAPI surface Claude normally uses. Captured via browser network trace; treat as tenant-internal contracts that can shift between versions.
type: reference
---

## How these were discovered

Captured from Chrome Network panel while a user edited a Mosaic data model in Strategy Studio. The `/api/openapi.yaml` the repo's helper normally uses does NOT document these paths. They are what the first-party UI actually calls. Treat as production-grade (the UI ships them) but version-sensitive.

## Workspace / pipeline — the UI's write surface

The UI does NOT write attributes, tables, or relationships directly against `/api/model/dataModels/{id}/...`. Instead it operates on a **workspace** (ephemeral editing sandbox) containing **pipelines** (per-table edit sessions). Writes go to the workspace/pipeline; commit materializes them into the model.

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/dataServer/workspaces` | Open a workspace for the current user/session. Returns `workspaceId`. |
| POST | `/api/dataServer/workspaces/{wsId}/pipelines/{pipelineId}/relationships` | Add/edit relationships on a specific pipeline (table) within the workspace. |
| GET | `/api/dataServer/usage/users/{userId}` | Per-user dataServer usage stats (quotas?). |

Implication: automation scripts can *probably* bypass this and write directly to `/api/model/dataModels/.../...` (which is what our `build_mosaic.py` does), but the UI's approach is interesting because:
- It allows *partial* edits to be rolled back without touching the committed model.
- It probably avoids the "PUT replaces full relationships list" footgun because relationships are pipeline-scoped.

## Batch API (the single biggest efficiency win)

```
POST /api/model/batch?allowPartialSuccess=true&showChanges=true
```

Returns 200. The UI bundles many operations (create multiple attributes, set multiple forms, tweak multiple metrics) into ONE round-trip with partial-success semantics: each sub-op reports its own status, success of one doesn't block others.

`showChanges=true` returns the diff that was applied; `showChanges=false` is fire-and-forget (also seen in capture).

**For our helper scripts:** consider adopting this. Currently `build_mosaic.py build` makes N POSTs per N objects within a changeset; a single batched POST would be faster and more atomic.

## Changeset rebase (conflict resolution)

```
POST /api/model/changesets/{csId}/operations?operationType=rebase&dataModelId={modelId}
```

We did not know this existed. The UI invokes it when a user's open changeset conflicts with a concurrent commit on the same model — the Mosaic server rebases their pending operations onto the new head. Analogous to `git rebase`.

Other `operationType` values likely exist (`cherry-pick`, `squash`?). Probe the OpenAPI before assuming.

## Changeset flags used by the UI

- `POST /api/model/changesets?enableOperationHistory=true` — the UI opens changesets with an operation-history flag so undo/redo works across the editing session. Our helpers don't set this.

## Model-level flags

- `PATCH /api/model/dataModels/{id}?showExecutiveSummary=true` — when the UI patches the model, it can request the server regenerate an AI executive summary inline. The summary is presumably stored back on the model for subsequent reads.

## AI service hooks

These power the UI's "Auto" / "Suggest" features:

| Method | Path | Trigger |
|---|---|---|
| POST | `/api/aiservice/model/objects/linking` | AI-auto-detect relationships between unlinked objects |
| POST | `/api/aiservice/model/overview` | AI-generate model overview/description |
| GET | `/api/model/diagnostics/status` | Model diagnostics health check |
| POST | `/api/nuggets/status/query` | AI indexing / "nuggets" status |
| GET | `/api/iams` | IAMs (Intelligent Agent Management Service) enumeration |

The `aiservice` family is brand-new to this repo's knowledge base. Automation that wants to "build a model like a human would" should probably call `aiservice/model/objects/linking` after table import instead of re-implementing shared-column inference in the helper.

## Platform / discovery reads triggered on model-editor open

- `GET /api/v2/configurations/featureFlags` — tenant-wide feature flags; check before assuming an endpoint/shape is available.
- `GET /api/gateways` — datasource gateways list (cloud connectivity).
- `GET /api/drivers` — installed driver list (JDBC/ODBC adapters available for datasource creation).
- `GET /api/folders/preDefined/73` — **new predefined folder id** (we previously documented 7 = PublicObjects, 8 = SchemaObjects, 9 = My Objects, etc.). `73` is model-editor-related; meaning unknown without further probing.
- `GET /api/library/dataModels/favorites` — per-user model favorites (Library home page).

## Search-related type codes observed

- `type=779` — data model (matches our existing docs)
- `type=776` — logical table (matches)
- `type=23042` — **unknown**, returned by model-picker search alongside 779/776. Candidate: data model "shortcut" or "alias"; probe via `/api/objects/{id}?type=23042` on a known instance.
- `type=14088` — **unknown**, used in `SUPPORTED_REPORTS_IN_LIBRARY_ONLY` filter search. Candidate: a report/dashboard composite subtype.

Both type codes are likely documented in the OpenAPI spec under `ObjectType` enums; worth a `yq`-style grep of the spec.

## Fact metric expression read with `showPotentialTables`

```
GET /api/model/dataModels/{mid}/factMetrics/{fmId}/fact/expressions/{exprId}?showPotentialTables=true&showExpressionAs=tokens
```

`showPotentialTables=true` is a new query param that returns the list of *additional* logical tables a fact expression could be bound to (beyond the ones currently bound). The UI uses this to populate the "available tables" dropdown in the metric expression editor.

For our build helpers, this is the right read to pair with a metric edit when you want to preserve UI-consistent behavior — e.g., when adding a new fact expression the UI would let a user bind to tables X, Y, Z because the ID column exists there.

## What to do with this memory

When building an automation flow that must mirror the UI experience (e.g., a "build a model the way the GUI would have" script), prefer these UI-internal endpoints over the raw Modeling Service. When building something the user never interacts with through the UI (pure automation, CI gates), the direct Modeling endpoints documented in `reference_mosaic_rest_api.md` are fine.

## Known gaps from this capture

Even though the user "did a lot of actions", the MCP browser-extension capture went dark mid-session — we are missing the specific payloads for:
- Metric creation / edit (what the batch body actually contains for a fact metric)
- Table add with Snowflake vs Postgres (does the UI use the same `importSource` shape we do, or a different one?)
- Security filter creation in UI (vs the `md_security_filter` shape we reverse-engineered)
- ACL edits on Mosaic objects (whether the UI exposes this at all)
- Model linking / data-mesh (the UI affordance exists, API shape unknown)

These are the highest-value next captures. Use Chrome DevTools HAR export or Copy-as-cURL instead of MCP for those specific flows — MCP capture proved unreliable across tab boundaries.
