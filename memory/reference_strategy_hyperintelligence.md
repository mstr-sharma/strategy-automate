---
name: Strategy HyperIntelligence REST surface
description: Verified /api/hyper/* endpoint family for listing cards, reading keyword inventories, instantiating/filtering card content, layouts/templates, enable-disable, favorites, plus the embedding SDK bundle path and session/header gotchas.
type: reference
---
## Where the endpoints live

The Hyper family is **hidden from the default OpenAPI spec** — fetch `{Library}/api/openapi.yaml?visibility=all` (~186k lines vs default). Tags: `Hyper`, `Library` (favorites), `Cards` (separate KPI-card feature).

Verified live 2026-08-28 on a Strategy Cloud tenant (13 cards, "BTC Card" test subject) except where noted.

## Search / discovery side

| Endpoint | What it does | Verified |
| --- | --- | --- |
| `GET /api/hyper/cards` | Card inventory for the project in `X-MSTR-ProjectID` (name, id, projectId, defaultCardStatus, certifiedInfo) | ✓ |
| `GET /api/searches/results?type=3` + filter `subtype==781` | Hyper cards are ordinary objects: type 3 (report), subtype **781** `report_hyper_card` — standard object search finds them | ✓ |
| `GET /api/hyper/cards/{cardId}/instances/{instanceId}/mainAttribute/elements` | The **keyword inventory** clients match against page text; returns per-element `formValues` = [Alternate Keyword, Keyword] | ✓ |
| `POST /api/hyper/cards/{cardId}/attributes/{attributeId}/elements/search` | Server-side element/keyword match; body is an Expression: `{operator:"Contains"/"BeginsWith", operands:[{type:"form",attribute:{id},form:{id}},{type:"constant",dataType:"Char",value:"…"}]}` | ✗ 500 I-Server memory-limit error on both attempts (endpoint parses body — a wrong form id gives a schema error instead) |

## Surfacing side

| Endpoint | What it does | Verified |
| --- | --- | --- |
| `POST /api/hyper/cards/{cardId}/instances` | Create in-memory instance → `instanceId` + full result: `definition` (attributes+forms, metrics, thresholds, sorting) + hierarchical `data.root` tree | ✓ |
| `POST /api/hyper/cards/{cardId}/cardInstances` | One-shot instance **with view-filter Expression body** → "gateway JSON" the Hyper clients render; body e.g. `{operator:"In",operands:[{type:"attribute",id},{type:"elements",elements:[{id:"hBitcoin;<attrId>"}]}]}`; response includes `source` = underlying cube | ✓ |
| `PUT /api/hyper/cards/{cardId}/instances/{instanceId}` | Manipulate live instance: change template, view filters, metric limits, thresholds (`includeThresholds`, `previewData`, `hyperViewFilter` params) | — |
| `GET /api/hyper/cards/{cardId}/instances/{instanceId}/layout` | Visual layout: template name/version, formats, share actions, and `linkedBot` (cards can bind an Auto bot: botId+projectId, subtype 14087) | ✓ |
| `GET /api/hyper/templates` and `GET /api/hyper/templates/{t}/layouts/{l}/thumbnails/{th}` | Template/layout gallery with tooltips + thumbnails | ✓ |

## Management side

- `PUT /api/hyper/cards/{cardId}/defaultCardStatus?cardStatus=…` — enable/disable the card in the project (what makes clients pick it up). Not exercised (mutation).
- `GET /api/library/hyperCards/favorites`, `PATCH` same path — per-user favorites.
- `GET /api/hyper/configuration` — hyperWeb extension settings (overlay-highlighting rules, disabled-websites globs). ✓
- `GET /api/cards/{id}` (tag `Cards`, "kpi card definition") **404s for hyper cards** — it serves the separate Library KPI-card feature, not subtype-781 cards.
- **No card create/update in the public REST spec** — cards are authored in Workstation.

## Gotchas

- **Instances are session-bound.** A login-per-call helper (e.g. `build_mosaic.py api-call`) kills the instance between calls — run create→read flows in one authenticated session.
- **`X-MSTR-ProjectID` is required** on `/api/hyper/*` writes/instances ("Project ID cannot be null or empty" otherwise).
- Keyword attribute forms: `Keyword` form is universal ID `45C11FA478E745FEA08D781CEA190FE5`; the alternate-keyword form id is card-specific.

## Embedding SDK (productized consumer of these APIs)

`{Library}/static/hyper/sdk/js/mstr_hyper.bundle.js` (≈6.5 MB, confirmed present) — the HyperIntelligence embedding SDK for surfacing cards in your own web app: it downloads enabled cards' keywords, scans/highlights host-page DOM text, and pops the card on hover. Use it instead of hand-rolling the match loop when embedding in a demo app.
