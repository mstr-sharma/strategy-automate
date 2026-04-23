---
name: Mosaic in-memory publish requires clean pipeline dataTypes (not warehouse-catalog types)
description: Confirmed 2026-04-23 on studio.strategy.com — when the publishable columns carry warehouse-catalog sentinels (precision=-1 or scale=-2147483648, `variable_length_string`, `fixed_length_string`, `binary`, `unsigned`, `decimal` with warehouse precision), the Mosaic in-memory publish accepts the request but the cube never materializes (status=1 with empty tables, or -2147212544 stall). A reference model built by the UI wizard shows normalized types (`utf8_char(32000,0)`, `integer(4,0)`, `integer(2,0)`, `double(P,S)`, `int64(8,0)`, `date(10,0)`, `time_stamp(26,6)` or `(23,9)`) — cloning those dataTypes into an otherwise-identical model fixes publish end-to-end.
type: feedback
---

## What happens if you skip this

`build_mosaic.py build` reads warehouse column metadata via `/api/datasources/{id}/catalog/tables/{tid}` and forwards those `dataType` objects verbatim into the new physical table's `physicalTable.columns[]` and pipeline. Two symptoms follow:

1. The helper's `publish` subcommand and the Mosaic 3-step flow (`POST /api/dataModels/{id}/instances` → `POST /api/dataModels/{id}/publish` → poll `publishStatus`) return 2xx and then either:
   - `status=1` with `tables:[]` forever (nothing happens — IServer silently no-ops), or
   - `-2147212544` QueryEngine parallel-mode stall that the 2026-04-22 memory attributed to the tenant. We now know at least part of that stall was the dataType shape, not tenant health — a REF model built the same day with clean types publishes fine.
2. The UI's "Publish" button, which routes through `POST /api/cubes/{modelId}?cubeAction=publish` (202 Accepted), also works on these clean-typed models. On dirty-typed models the UI still hits `/api/cubes` but the resulting job errors inside the CubeServer component.

## Canonical dataType mapping (warehouse → Mosaic in-memory)

Apply this when building a physical table to publish. Source values come from `/api/datasources/{id}/catalog/tables/{tid}`; target values are what the UI-created reference model (REF) used.

| Source `type` | Source shape | → Target `type` | Target precision | Target scale |
|---|---|---|---|---|
| `variable_length_string` | precision=-1, scale=-MIN_INT | `utf8_char` | 32000 | 0 |
| `fixed_length_string` | precision=any, scale=-MIN_INT | `utf8_char` | 32000 | 0 |
| `integer` | precision=4, scale=-MIN_INT | `integer` | 4 | 0 |
| `binary` | precision=1, scale=-1 | `integer` | 2 | 0 |
| `unsigned` | precision=1, scale=-MIN_INT | `integer` | 2 | 0 |
| `decimal` | precision=P, scale=0 | `int64` | 8 | 0 |
| `decimal` | precision=P, scale=S (S>0) | `double` | P | S |
| `time_stamp` | precision=8 | `time_stamp` | 26 | 6 |
| `time_stamp` | precision=9 | `time_stamp` | 23 | 9 |
| `date` | precision=0, scale=-MIN_INT | `date` | 10 | 0 |

`-MIN_INT` above = `-2147483648` (Java `Integer.MIN_VALUE`, meaning "not set" in the warehouse catalog payload).

## Where the dataType lives

Two places must stay in sync on every table:

1. `physicalTable.columns[i].dataType` — the public column definition.
2. `physicalTable.pipeline` (JSON string) — the pipeline spec has its own `rootTable.children[*].columns[*].dataType` AND `sourceDataType`. Both need the cleaned type.

Aligning them by column name is the safe pattern — before POSTing the table, walk the pipeline, ensure the `id` of each pipeline column matches `physicalTable.columns[i].information.objectId`, and ensure both `dataType` and `sourceDataType` carry the target shape.

## The clean-types-via-clone pattern

The fastest way to fix an already-built dirty-typed model is to clone a known-good reference:

1. Fetch REF model via `GET /api/model/dataModels/{refId}?showExpressionAs=tokens`, then for each table `GET /api/model/dataModels/{refId}/tables/{tid}?showColumns=true`.
2. Deep-copy each table body; strip `information.objectId`/`information.dateCreated` and the pipeline's `id`/`rootTable.id`/`children[*].id`/`columns[*].id` — mint fresh UUIDs. Keep column NAMES identical so `physicalTable.columns` and the pipeline's column list still zip by name.
3. Keep every `dataType`/`sourceDataType` from REF unchanged — this is the whole point.
4. POST each rebuilt table to the new model inside a changeset.
5. Clone attributes and fact metrics too, using text-only `column_reference` tokens (`{"type":"column_reference","value":"COL_NAME"}` — no `target.objectId`) so Mosaic re-binds to the new column ids by name on commit. Do NOT carry REF's `expressionId`/`target.objectId` values — those will collide.
6. Commit tables + attributes + metrics in ONE changeset. The "table has no attribute/metric" commit check (`8004e42f`) requires at least one attribute or metric per table to be created before commit.
7. Follow up with a second changeset for relationships and a third for security filters.

See `memory/reference_mosaic_publish_path.md` for the verified publish trigger sequence once the model exists with clean types.
