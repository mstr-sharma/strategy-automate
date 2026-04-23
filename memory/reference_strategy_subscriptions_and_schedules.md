---
name: Strategy subscriptions, schedules, and distribution
subtype: stub
description: Stub reference for Strategy's delivery surface — email/file/history-list/print/mobile/cache subscriptions, schedule triggers, transmitter selection, recipient resolution. Captures the endpoint families; needs per-transmitter verified payloads added as they're exercised.
type: reference
---

Part of the platform coverage contract (see `reference_strategy_automation_coverage.md`). Not yet a wrapped helper — treat as **generic REST hook** until a typed wrapper ships in `skill/scripts/`.

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

### UMA 2026-04-23: report email subscription with immediate preview

Verified against UMA tenant `https://<env-id>.customer.cloud.microstrategy.com/MicroStrategyLibrary` in project `MicroStrategy Tutorial` for report `<report-id>` (`View Filter Report`).

Working `POST /api/subscriptions` body shape:

```json
{
  "name": "View Filter Report Monday Morning",
  "sendNow": true,
  "schedules": [
    { "id": "FF7BB3B311D501F0C00051916B98494F" }
  ],
  "contents": [
    {
      "id": "<report-id>",
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
      "id": "<user-id>",
      "type": "user",
      "includeType": "TO",
      "addressId": "<address-id>"
    }
  ],
  "delivery": {
    "mode": "EMAIL",
    "email": {
      "subject": "View Filter Report",
      "message": "Preview delivery for View Filter Report",
      "sendContentAs": "data"
    }
  }
}
```

Observed server response / behavior:

- `sendNow` is a write-only field on the `Subscription` body. On this tenant there was no separate `/api/subscriptions/{id}/sendNow` path in `/api/openapi.yaml`, so immediate preview should be requested during create/update, not assumed as a follow-up endpoint.
- Passing recipient `type:"user"` plus `addressId` worked, but the saved subscription normalized the recipient to `type:"personal_address"` with recipient `id` equal to the address ID, not the user ID.
- The server accepted `formatMode:"DEFAULT"` and `viewMode:"DEFAULT"` but persisted the report content as `formatMode:"CURRENT_PAGE"` and `viewMode:"BOTH"`. Treat the GET-after-create response as source of truth.
- A valid auth token alone was not enough for follow-up reads in ad hoc probes; the client needed the login session cookies (`JSESSIONID`, `iSession`) preserved as well. `requests.Session()` matched tenant behavior; bare header-only urllib probes returned `ERR009` session expired on subsequent calls.
- `GET /api/objects/{id}` on this tenant required `type` query param for classic objects; `GET /api/objects/{reportId}?type=3` worked for the report lookup.
- `GET /api/schedules` returned the reusable built-in schedule `Monday Morning` with ID `FF7BB3B311D501F0C00051916B98494F` and next delivery `2026-04-27T04:00:00+0000`.
- `GET /api/users/{userId}/addresses` returned the target email address. For user `<user-id>` (`arpan`), the default email address was `<address-id>` / `redacted@example.com`.

Follow-up hardening ideas:

- Add a typed `create-subscription` helper to `skill/scripts/build_mosaic.py` so the repo stops relying on ad hoc REST payload assembly for subscriptions/schedules.
- After helper creation, capture additional verified variants: prompt-bearing reports, dossier email deliveries, history list deliveries, and explicit send-preview status inspection if the tenant exposes run history endpoints.
