---
name: Strategy subscriptions, schedules, and distribution
subtype: stub
description: Stub reference for Strategy's delivery surface — email/file/history-list/printer/mobile/cache/cloud-drive subscriptions, schedule triggers, transmitter selection, recipient resolution — plus the documented scheduled Mosaic refresh (a `data_model` subscription with `refreshCondition`). Captures the endpoint families; needs per-transmitter verified payloads added as they're exercised.
type: reference
---

Part of the platform coverage contract (see `reference_strategy_automation_coverage.md`). Not yet a wrapped helper — treat as **generic REST hook** until a typed wrapper ships in `skills/build-mosaic-model/scripts/`.

## Endpoint families (corrected 2026-10-05 against the tenant spec)

- `GET/POST /api/subscriptions` — list/create subscriptions; `GET/PUT/PATCH/DELETE /api/subscriptions/{id}`, `GET …/{id}/status`, `POST /api/subscriptions/query` (cross-project). Delivery `mode` enum for `POST /api/subscriptions` (spec, 2026-10-05): `EMAIL`, `HISTORY_LIST`, `CACHE`, `FTP`, `FILE`, `MOBILE`, `ONEDRIVE`, `SHAREPOINT`, `S3`, `GOOGLEDRIVE`, `GCS`. (`PRINTER`, `SNAPSHOT`, `PERSONAL_VIEW`, `SHARED_LINK` appear only on the recipient/address endpoints.) Content `type` includes `data_model` for Mosaic refresh (below).
- `GET/POST /api/schedules`, `GET/PUT/DELETE /api/schedules/{id}` (also `GET /api/v2/schedules`) — time / event triggers (`time_based`, `event_based`); `POST /api/events/{id}/trigger` fires an event-based schedule.
- `GET/POST /api/transmitters`, `GET/PUT/DELETE /api/transmitters/{id}` — delivery transmitters; devices via `GET/POST /api/v2/devices`.
- `GET/POST /api/contacts`, `POST /api/contacts/query`; `GET/POST /api/contactGroups`, `POST /api/contactGroups/query` — recipient directory (there is no `/api/contact_collections`).
- `POST /api/subscriptions/{id}/send` (also `/api/v2/subscriptions/{id}/send`) → 202 — run an existing subscription now; the optional body carries prompt answers (`{contentId, instanceId}`) for prompted content. There is no `/sendNow` path; `sendNow: true` on create/update also sends.
- `DELETE /api/subscriptions/{id}` — remove (unsubscribe).
- Data alerts are subscriptions too (`alert: true`, read-only on the `Subscription` body).

## Key knowledge gaps (flag to fill on next live use)

- Verified payload shape per delivery type (email: subject, body, attach-format — file: path template, format, overwrite policy).
- Prompt answer persistence inside a subscription (how `promptAnswers` is attached; cube vs report differences).
- Recipient handling for Mosaic-derived content (do Mosaic dashboards route through `/api/subscriptions` at all, or only published reports/documents/dossiers?). Mosaic model *refresh* does route through it — see below.
- Cache-update subscription vs cube refresh overlap.

## Routing rules (corrected 2026-10-05)

- **Mosaic model refresh on a schedule IS a subscription** (REST docs `mosaic/publish/schedule-refresh-a-data-model`, available since August 2025). Earlier text said to avoid `/api/subscriptions` and drive `POST /api/dataModels/{id}/publish` from an external scheduler — wrong. `POST /api/subscriptions` with:

  ```json
  {"name": "<name>", "sendNow": false,
   "schedules": [{"id": "<schedule id>"}],
   "contents": [{"id": "<data model id>", "type": "data_model",
                 "refreshCondition": {
                   "tables": [{"id": "<table id>", "refreshPolicy": "upsert"}],
                   "filters": [{"type": "refresh", "qualification": {"tree": {"type": "predicate_form_qualification", "...": "..."}}}]}}],
   "delivery": {"mode": "HISTORY_LIST"}}
  ```

  `refreshCondition.tables[].refreshPolicy` takes the publish policies (`add` / `update` / `upsert` / `replace` / …); or set `refreshCondition.datasetRefreshPolicy` as the default for every table (required when `tables` is empty — it then also covers tables added later). `filters` is optional (attribute form qualifications). Update with `PUT /api/subscriptions/{id}`, read back with `GET /api/subscriptions/{id}`. A one-off refresh is still the publish flow in `reference_mosaic_publish_path.md`.
- **Report/dossier delivery** → classic subscriptions path.
- **Classic cube refresh on a schedule** → a `CACHE`-mode subscription on the cube.
- **Data alerts** → alert subscriptions (same `/api/subscriptions` surface); see `reference_strategy_monitoring_jobs_alerts.md` for the monitor side.

## mstrio-py coverage

Subscriptions are one of the more stable mstrio-py wrappers. For scripted creation of recurring deliveries against classic reports/documents, `mstrio.distribution_services.subscription` is the pragmatic path — capture the REST equivalent on first use so it can be hooked directly later. See `reference_mstrio_py.md`.

## Pending: verified reference payloads

When exercising any of the below, capture the body and append to this file under a "Verified payloads" section, then mark the stub tag closed:

- Email subscription against a dossier with prompt answers.
- File subscription to `%FILELOCATION%` with CSV + header.
- History list subscription with format=`pdf`.
- Mobile subscription.
- Cache-update subscription on a classic cube.

## Verified payloads

### Report email subscription with immediate preview (verified 2026-04-23)

Working `POST /api/subscriptions` body shape for a single-report email subscription sent immediately via `sendNow`:

```json
{
  "name": "<subscription display name>",
  "sendNow": true,
  "schedules": [
    { "id": "<schedule-object-id>" }
  ],
  "contents": [
    {
      "id": "<report-object-id>",
      "type": "report",
      "projectId": "<project-id>",
      "personalization": {
        "formatType": "PDF",
        "formatMode": "DEFAULT",
        "viewMode": "DEFAULT"
      }
    }
  ],
  "recipients": [
    {
      "id": "<user-object-id>",
      "type": "user",
      "includeType": "TO",
      "addressId": "<user-address-id>"
    }
  ],
  "delivery": {
    "mode": "EMAIL",
    "email": {
      "subject": "<email subject>",
      "message": "<email body>",
      "sendContentAs": "data"
    }
  }
}
```

Resolve the ID placeholders at run time:
- `<schedule-object-id>` — `GET /api/schedules`; pick by `name` (common built-in: `Monday Morning`). Schedule IDs are tenant-scoped; do not reuse across tenants.
- `<project-id>` — `GET /api/projects`; match by `name`.
- `<report-object-id>` — `GET /api/objects/{id}?type=3` to confirm, or search the target folder.
- `<user-object-id>` and `<user-address-id>` — `GET /api/users?nameBegins=…` and `GET /api/users/{userId}/addresses`; the default address is flagged on the response.

Observed server behaviors (tenant-family: Strategy ONE Cloud, library version current on 2026-04-23 — recheck on tenants with different iServer build):

- `sendNow` is a **write-only** field on the `Subscription` body. There is no `/api/subscriptions/{id}/sendNow` path, but an existing subscription can be run later with `POST /api/subscriptions/{id}/send` (→ 202; also v2) — corrected 2026-10-05; the 2026-04 note said a follow-up send endpoint did not exist.
- Passing recipient `type:"user"` plus `addressId` is accepted on write, but the saved subscription **normalizes** the recipient to `type:"personal_address"` with `id` equal to the address ID, not the user ID. Always re-read via `GET` after create if downstream code depends on the recipient shape.
- `formatMode:"DEFAULT"` and `viewMode:"DEFAULT"` are accepted on write but **persisted** as `formatMode:"CURRENT_PAGE"` and `viewMode:"BOTH"`. Treat the GET-after-create response as source of truth.
- A bare auth-token header is not enough for follow-up reads — the client must preserve the login session cookies (`JSESSIONID`, `iSession`). `requests.Session()` in Python matches tenant behavior; bare `urllib` probes return `ERR009 session expired` on subsequent calls.
- `GET /api/objects/{id}` requires the `type` query param for classic objects (e.g. `?type=3` for reports).

Follow-up hardening (recorded as a gap, not yet implemented):

- Add a typed `create-subscription` helper to `skills/build-mosaic-model/scripts/build_mosaic.py` (or a sibling) so subscription payloads stop being assembled ad hoc. Helper should take `--report-id`, `--project-id`, `--schedule`, `--recipient-user`, and resolve addresses server-side.
- After helper creation, capture additional verified variants under `captures/`: prompt-bearing reports, dossier email deliveries, history-list deliveries, and explicit send-preview status inspection when the tenant exposes run-history endpoints.
