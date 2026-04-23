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
