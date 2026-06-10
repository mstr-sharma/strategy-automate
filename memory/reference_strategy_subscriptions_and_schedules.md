---
name: Strategy subscriptions, schedules, and distribution
subtype: stub
description: Stub reference for Strategy's delivery surface — email/file/history-list/print/mobile/cache subscriptions, schedule triggers, transmitter selection, recipient resolution. Captures the endpoint families; needs per-transmitter verified payloads added as they're exercised.
type: reference
---

Part of the platform coverage contract (see `reference_strategy_automation_coverage.md`). Not yet a wrapped helper — treat as **generic REST hook** until a typed wrapper ships in `skills/build-mosaic-model/scripts/`.

## Endpoint families

- `GET/POST /api/subscriptions` — list/create subscriptions. Delivery types: `EMAIL`, `FILE`, `PRINT`, `HISTORY_LIST`, `CACHE_UPDATE`, `MOBILE`, `PUSH_NOTIFICATION`.
- `GET /api/schedules` — list time/event triggers (`time_based`, `event_based`).
- `GET /api/transmitters` — available delivery transmitters (email server, file location, etc.).
- `GET /api/contacts`, `GET /api/contact_collections` — recipient directory. Classic contacts + linked user accounts.
- `POST /api/subscriptions/{id}/sendNow` — force immediate run.
- `DELETE /api/subscriptions/{id}` — remove.

## Key knowledge gaps (flag to fill on next live use)

- Verified payload shape per delivery type (email: subject, body, attach-format — file: path template, format, overwrite policy).
- Prompt answer persistence inside a subscription (how `promptAnswers` is attached; cube vs report differences).
- Recipient handling for Mosaic-derived content (do Mosaic dashboards route through `/api/subscriptions` at all, or only published reports/documents/dossiers?).
- Cache-update subscription vs cube refresh overlap.

## Routing rules

- **Mosaic model refresh on a schedule** → do NOT use `/api/subscriptions` with `CACHE_UPDATE`. Use the Mosaic-native `POST /api/dataModels/{id}/publish` with `refreshPolicy:"add"|"replace"|"update"|"upsert"` triggered from an external scheduler (or the UI's schedule panel). See `reference_mosaic_publish_path.md`.
- **Report/dossier delivery** → classic subscriptions path.
- **In-app alerts** → route through `reference_strategy_monitoring_jobs_alerts.md` (separate surface from subscriptions).

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

- `sendNow` is a **write-only** field on the `Subscription` body. There is no separate `/api/subscriptions/{id}/sendNow` path in `/api/openapi.yaml` on this tenant family — immediate preview must be requested during create/update, not as a follow-up endpoint.
- Passing recipient `type:"user"` plus `addressId` is accepted on write, but the saved subscription **normalizes** the recipient to `type:"personal_address"` with `id` equal to the address ID, not the user ID. Always re-read via `GET` after create if downstream code depends on the recipient shape.
- `formatMode:"DEFAULT"` and `viewMode:"DEFAULT"` are accepted on write but **persisted** as `formatMode:"CURRENT_PAGE"` and `viewMode:"BOTH"`. Treat the GET-after-create response as source of truth.
- A bare auth-token header is not enough for follow-up reads — the client must preserve the login session cookies (`JSESSIONID`, `iSession`). `requests.Session()` in Python matches tenant behavior; bare `urllib` probes return `ERR009 session expired` on subsequent calls.
- `GET /api/objects/{id}` requires the `type` query param for classic objects (e.g. `?type=3` for reports).

Follow-up hardening (recorded as a gap, not yet implemented):

- Add a typed `create-subscription` helper to `skills/build-mosaic-model/scripts/build_mosaic.py` (or a sibling) so subscription payloads stop being assembled ad hoc. Helper should take `--report-id`, `--project-id`, `--schedule`, `--recipient-user`, and resolve addresses server-side.
- After helper creation, capture additional verified variants under `captures/`: prompt-bearing reports, dossier email deliveries, history-list deliveries, and explicit send-preview status inspection when the tenant exposes run-history endpoints.
