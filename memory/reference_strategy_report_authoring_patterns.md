---
name: Report / dashboard / dossier authoring — recommended patterns
subtype: stub
description: REST does NOT expose from-scratch creation of reports/dossiers/dashboards on current Strategy ONE tenants (see reference_strategy_report_dossier_creation.md). This memory documents the surviving authoring paths — mstrio-py object construction, clone-and-retarget from a template, execute-and-persist via /instances — and the trade-offs among them.
type: reference
---

## Why this exists

Users often say "generate a dashboard for X." The only repeatable automation paths are:

1. **mstrio-py template scaffolding** — use `mstrio.project_objects.Report`, `Dossier`, `Document` to build or modify objects. The wrapper fills in the definition XML/JSON so scripts don't have to hand-roll it.
2. **Clone-and-retarget from a template** — copy an existing published report/dossier via `/api/objects/{id}/copy?destinationFolderId=...`, then PATCH the filter/prompt defaults or underlying dataset binding. Works for Library dossiers where a template catalog already exists.
3. **Execute-and-save via `/instances`** — create a new instance of an existing report/document with prompt answers + runtime filters, then save the instance output as a new saved report. Does NOT create new layout/visualization — it only binds new runtime inputs to an existing template.

Do NOT expect the Mosaic Modeling Service to author reports. That service is schema-only; reports/dashboards are a separate object family (types 55 document, 58 dossier/dashboard) not writable through `/api/model/...`.

## Decision table

| User ask | Recommended path |
|---|---|
| "Create a new dashboard from scratch" | mstrio-py or Workstation; REST is insufficient. Surface as a known gap. |
| "Copy Report X into folder Y and re-point at new dataset" | `/api/objects/{id}/copy` + PATCH definition. |
| "Run Report X with these prompt answers and save output" | `/instances` flow → save instance as new object. |
| "Scheduled email of Dossier X" | See `reference_strategy_subscriptions_and_schedules.md`. |
| "Build an AI-generated dashboard" | `/api/aiservice/...` + Mosaic agent; treat as a generated artifact, not a curated dashboard. |

## Clone-and-retarget endpoint

```
POST /api/objects/{sourceId}/copy?destinationFolderId={folderId}&newName={name}&type={3|55|58|74|...}
-> { "id": "<newObjectId>", ... }
```

After copy, PATCH the needed slots:
- Dataset binding (for dossiers backed by Mosaic models) — dossier definition references model IDs; remap after copy.
- Prompt defaults — `PATCH /api/documents/{id}/prompts` with new default values.
- Filter definition — `PATCH /api/documents/{id}/definition` (structure varies by object family).

## Verified vs gap

- **Verified**: copy + rename (across documents, dossiers, reports, filters, custom groups).
- **Gap**: full from-scratch dashboard authoring via REST. Route to mstrio-py or escalate to Workstation.
- **Gap**: verified payload for dataset-rebind PATCH — needs to be captured when first exercised.

## Pointers

- `reference_strategy_runtime_analytics.md` — execute/export semantics.
- `reference_strategy_report_dossier_creation.md` — the REST surface gap analysis.
- `reference_mstrio_py.md` — when to use the Python wrapper over raw REST.
