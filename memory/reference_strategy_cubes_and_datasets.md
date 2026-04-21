---
name: Strategy cube and dataset families
description: Distinguish Intelligent/OLAP cubes, Super Cube/MTDI Push Data datasets, runtime Cube API, and Mosaic model publish/materialization workflows.
type: reference
originSessionId: local-codex-2026-04-21
---
Use this whenever the user says cube, OLAP, Intelligent Cube, Super Cube, MTDI, Push Data, dataset, refresh, publish, cache, or data extraction.

## Intelligent Cube / OLAP cube

Official docs describe "Manage cube objects" as Modeling Service workflows for Intelligent Cube objects.

Core flow:

- Create definition: `POST /api/model/cubes`
- Read definition: `GET /api/model/cubes/{cubeId}`
- Update definition: `PUT /api/model/cubes/{cubeId}`
- Publish/materialize: `POST /api/v2/cubes/{cubeId}` in current docs; some tenants also support `POST /api/cubes/{cubeId}`.
- Execute/read data: `POST /api/cubes/{cubeId}/instances`, then `GET /api/cubes/{cubeId}/instances/{instanceId}`.
- Browse cube elements: `/api/cubes/{cubeId}/attributes/{attributeId}/elements` and instance-specific variants.
- Monitor cache: `/api/monitors/caches/...` and cube cache monitor endpoints.

Typical create body includes:

- `information.subType: "report_cube"`
- `template.rows`, `template.columns`, `template.pageBy`
- Optional `filter`
- `options.dataRefresh`, `dataPartition`, language options
- Optional `advancedProperties`
- FFSQL cube variants can include `sourceType: "custom_sql_free_form"` and table definitions.

## Super Cube / MTDI / Push Data dataset

Official docs call this external-data workflow the Push Data API and describe Super Cube/MTDI datasets under Dataset APIs.

Single-table workflow:

- Create and upload in one call: `POST /api/datasets`
- Update table data: `PATCH /api/datasets/{datasetId}/tables/{tableId}`
- Good for small/simple single-table datasets.

Multi-table/incremental workflow:

- Create dataset model/definition: `POST /api/datasets/models`
- Create upload session: `POST /api/datasets/{datasetId}/uploadSessions`
- Upload chunks: `PUT /api/datasets/{datasetId}/uploadSessions/{uploadSessionId}`
- Publish: `POST /api/datasets/{datasetId}/uploadSessions/{uploadSessionId}/publish`
- Poll status: `GET /api/datasets/{datasetId}/uploadSessions/{uploadSessionId}/publishStatus`
- Dataset publish/refresh/status endpoints include `/api/datasets/{datasetId}`, `/api/datasets/cubes/{id}/status`, `/api/datasets/{datasetId}/instances/{instanceId}/refresh`.

Dataset definitions include tables, column headers, dataset attributes, and dataset metrics. These are not the same as project schema attributes/metrics unless separately modeled.

## DDA and MDX cubes

The Cube API supports DDA and MDX cubes for runtime retrieval/execution in addition to Intelligent Cubes. Treat these as execution/data-access surfaces first:

- Confirm the cube type/subtype and datasource/MDX role before writing.
- Use `GET /api/cubes/{cubeId}` or object metadata to inspect.
- Some endpoints include `X-MSTR-MdxDbRoleId`; do not assume Intelligent Cube create/update bodies apply.

## Mosaic data models

Mosaic models are created and edited with `/api/model/dataModels`, not `/api/model/cubes`.

Important distinction:

- Semantic editing: `/api/model/dataModels/{dataModelId}/tables|attributes|metrics|factMetrics|relationships|securityFilters`.
- Data serve mode: `connect_live`, `in_memory`, and tenant-supported `hybrid`.
- Publish/materialization: on some tenants, in-memory Mosaic models are published through cube endpoints such as `POST /api/cubes/{modelId}`. Verify against live OpenAPI and tenant behavior.
- Query/semantic inspection: prefer Mosaic MCP (`get_semantics`, `query`) when connected; otherwise use REST cube/model APIs as available.

## mstrio-py package map

Relevant public repo modules/examples:

- `mstrio.project_objects.datasets.olap_cube`
- `mstrio.project_objects.datasets.super_cube`
- `mstrio.project_objects.datasets.cube_cache`
- `mstrio.api.cubes`
- `mstrio.api.datasets`
- `code_snippets/intelligent_cube.py`
- `code_snippets/create_super_cube.py`
- `code_snippets/cube_cache.py`
- `workflows/import_cube_data_into_dataframe.py`

Use wrappers for reads, cache operations, and Push Data ergonomics. For generated automation memory, still record the REST endpoint family used and the object IDs created or modified.
