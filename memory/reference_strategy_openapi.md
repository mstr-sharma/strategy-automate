---
name: Strategy OpenAPI reference
description: How agents should discover and use the machine-readable Strategy REST OpenAPI spec instead of scraping the Swagger UI.
type: reference
originSessionId: local-codex-2026-04-21
---
The Swagger / API Explorer page at `{Library}/api-docs/` is a JavaScript app. Do not scrape it as HTML.

Use the raw OpenAPI file:
- `https://demo.microstrategy.com/MicroStrategyLibrary/api/openapi.yaml`
- `https://studio.strategy.com/MicroStrategyLibrary/api/openapi.yaml`
- Local cached copy, when present: `/Users/<operator-user>/Desktop/Mosaic Build/openapi.yaml`

Verified 2026-04-21:
- content type: `application/yaml`
- `openapi: 3.0.1`
- `info.title: Strategy REST`
- `info.version: "2026"`
- studio tenant returned 652 paths and tags including Authentication, Data Models, Datasource Management, Cubes, Changesets, Security Filters.
- `/api-docs/swagger-config` returned 404.

Use the helper instead of manual curl:
```bash
cd "/Users/<operator-user>/Desktop/Mosaic Build"
python3 skill/scripts/build_mosaic.py openapi-summary --limit 80
python3 skill/scripts/build_mosaic.py openapi-search "dataModels" --context 2
python3 skill/scripts/build_mosaic.py openapi-summary --out /tmp/strategy-openapi.yaml
```

If a local `openapi.yaml` exists in the Mosaic Build root, treat it as a reference/cache, not as the source of truth. Refresh it from the tenant when endpoint behavior matters.

For one-off REST operations that are not wrapped yet:
```bash
python3 skill/scripts/build_mosaic.py api-call --method GET --path /api/projects
python3 skill/scripts/build_mosaic.py api-call --method PATCH --path /api/model/dataModels/<id> --json-file /tmp/body.json
```

For read-first automation flows:
```bash
python3 skill/scripts/build_mosaic.py search-objects --name "Object Name"
python3 skill/scripts/build_mosaic.py resolve-users --user person@example.com
python3 skill/scripts/build_mosaic.py get-model-object --kind legacy_attribute --object-id <id> --show-expression-as tokens
python3 skill/scripts/build_mosaic.py patch-model-object --kind legacy_attribute --object-id <id> --json-file /tmp/patch.json --before-out /tmp/before.json --yes
```

Important OpenAPI paths for Mosaic automation:
- `POST /api/model/changesets`, `POST /api/model/changesets/{changesetId}/commit`, `DELETE /api/model/changesets/{changesetId}`
- `POST /api/model/dataModels`, `GET/PATCH /api/model/dataModels/{dataModelId}`
- `GET/POST /api/model/dataModels/{dataModelId}/tables`
- `GET/POST /api/model/dataModels/{dataModelId}/attributes`, `PUT /api/model/dataModels/{dataModelId}/attributes/{attributeId}/relationships`
- `GET/POST /api/model/dataModels/{dataModelId}/metrics` for advanced metrics; tenant also accepts `/factMetrics` for fact metrics.
- `GET/POST /api/model/dataModels/{dataModelId}/factMetrics`
- `GET/POST /api/model/dataModels/{dataModelId}/securityFilters`
- `PATCH /api/dataModels/{dataModelId}/securityFilters/{securityFilterId}/members` for assigning members; body is JSON Patch style: `{operationList:[{op:"addElements",path:"/members",value:[ids...]}]}`.
- `PATCH /api/model/dataModels/{dataModelId}/objects/{objectId}/acl?subType=<objectSubType>` for ACL on model-contained objects.
- `PATCH /api/model/dataModels/{dataModelId}/objects/{objectId}/translations?subType=<objectSubType>` for name/description/form translations.
- `GET/PATCH /api/model/attributes/{attributeId}` for classic/legacy schema attributes outside a Mosaic data model; use changesets and request `showExpressionAs=tokens` when editing expressions.
- `GET/PATCH /api/model/metrics/{metricId}`, `/api/model/facts/{factId}`, `/api/model/tables/{tableId}` for classic schema objects.
- `GET/POST /api/users`, `GET/PATCH/DELETE /api/users/{id}`, `POST /api/users/{id}/addresses` for user management; dry-run and resolve exact duplicates before creating users.
- `POST /api/cubes/{cubeId}` publishes an in-memory cube/model on studio.strategy.com; public spec also lists data-model publish endpoints, but use the tenant-verified cube POST first.

When docs and tenant behavior disagree, prefer this order:
1. Tenant-verified gotcha in `feedback_mosaic_gotchas.md`
2. Live `openapi-summary` / `/api/openapi.yaml`
3. Official REST docs at `https://microstrategy.github.io/rest-api-docs/`
4. Clone-and-remap from a working object returned by `GET`
