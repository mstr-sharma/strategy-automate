---
name: Strategy runtime analytics, prompts, filters, and exports
description: Clarify report/cube/dashboard/document execution, runtime filters/prompts, exports, and JSON Data API behavior.
type: reference
originSessionId: local-codex-2026-04-21
---
Use this when the user asks to run, fetch data from, filter, prompt, export, refresh, or inspect reports, cubes, dashboards/dossiers, or documents. This is a **runtime analytics** lane, not a semantic-model editing lane.

## Runtime vs definition

- Runtime instance APIs create or manipulate a temporary execution instance. They do not create project metrics/attributes/filters or Mosaic model objects.
- Modeling APIs create/change definitions (`/api/model/...` or `/api/model/dataModels/...`).
- Object APIs rename/move/secure/certify metadata objects (`/api/objects/...`).

## Reports and cubes

Use the JSON Data API style flow:

- Report instance: `POST /api/reports/{reportId}/instances`, then fetch pages/definitions/results from report instance endpoints.
- Cube instance: `POST /api/cubes/{cubeId}/instances`, then `GET /api/cubes/{cubeId}/instances/{instanceId}`.
- Runtime filtering can include view filters, metric limits, and requested objects.
- For report vs cube requested objects: reports return the original template when `requestedObjects` is null; cube instances tend to include all attributes/metrics in the working set when `requestedObjects` is omitted. Verify in live tenant behavior for ad hoc requests.
- Instance filters are not persisted to metadata.

## Dashboards/dossiers/documents

Strategy docs use both dashboard and dossier naming; the REST API still exposes many `/api/dossiers/...` and `/api/documents/...` paths.

- Create dashboard/dossier instance: `POST /api/dossiers/{dossierId}/instances`.
- Filter dashboard instance: `PUT /api/dossiers/{dossierId}/instances/{instanceId}/filters`.
- Document instance: `POST /api/documents/{id}/instances`.
- Tenant-verified shape: document instance creation can return HTTP 201 with `mid` instead of `instanceId`; use `mid` as the instance identifier for follow-up export calls.
- Dashboard/document visual data: `GET /api/documents/{id}/instances/{instanceId}/layouts/{layoutKey}/visualizations/{visualizationKey}` and dossier visualization/page endpoints.
- Definition/hierarchy: `GET /api/documents/{id}/definition`, `GET /api/dossiers/{dossierId}/definition`, instance definition endpoints.
- Dashboard import/export/in-memory creation can also use `/api/dashboards...` and `/api/dossiers/instances`; inspect OpenAPI for the exact tenant variant.

## Prompts

Two different things share "prompt" language:

- **Prompt object definition:** created/updated through Modeling Service, e.g. `/api/model/prompts`. This changes reusable metadata.
- **Prompt answer at runtime:** supplied to a report/dashboard/document instance. This changes the instance answer, not the prompt object.

Runtime endpoints include:

- `GET /api/documents/{id}/prompts`
- `GET /api/documents/{id}/instances/{instanceId}/prompts`
- `GET /api/documents/{id}/instances/{instanceId}/prompts/{promptIdentifier}/elements`
- `GET /api/documents/{id}/instances/{instanceId}/prompts/{promptIdentifier}/objects`
- `PUT /api/documents/{id}/instances/{instanceId}/prompts/answers`
- `POST /api/documents/{id}/instances/{instanceId}/promptsAnswers`
- `POST /api/dossiers/{dossierId}/instances/{instanceId}/answerPrompts`
- `POST /api/documents/{id}/instances/{instanceId}/rePrompt`

Prompt APIs can read definitions, answer with explicit values, answer defaults, close optional prompts without answers, and reset/re-prompt depending on prompt type.

## Filters

Keep these separate:

- **Project filter object:** `/api/model/filters`.
- **Mosaic data-model filter or security filter:** `/api/model/dataModels/{id}/...`.
- **Runtime view filter / metric limit / template limit:** part of an instance request or dashboard filter manipulation. Not persisted.
- **Security filter:** row-level access restriction assigned to users/groups.

For dashboards/dossiers, `GET /api/dossiers/{dossierId}/definition` can reveal chapter-level filters; visualization endpoints can reveal filters applied to a specific visualization.

## Exports

Common export patterns:

- Document/dashboard PDF: `POST /api/documents/{id}/instances/{instanceId}/pdf`, then result/status endpoint when asynchronous.
- Document Excel: `POST /api/documents/{id}/instances/{instanceId}/excel`.
- Document/dashboard CSV or visualization CSV/PDF: `/api/documents/{id}/instances/{instanceId}/csv`, `/visualizations/{nodeKey}/csv`, `/visualizations/{nodeKey}/pdf`.
- Dashboard file import/export paths may live under `/api/dashboards`.

Always create or reuse the correct instance first, especially for prompted content.

## Verification checklist

- Confirm content object type and project ID.
- Create instance and check status before fetching result/export files.
- For prompted content, read prompts before answering, then verify the instance is no longer in prompt status.
- For filters, explicitly note whether the filter was runtime-only or persisted metadata.
- Clean up/delete instances when the API supports it and the workflow created temporary state.
