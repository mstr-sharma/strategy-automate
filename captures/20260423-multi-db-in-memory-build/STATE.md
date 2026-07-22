# Tenant GPU Analysis — run state snapshot

**Paused at 22:11:53** (user request: "pause, I will inspect the tool").

## Model
- **model_id**: `7CA52A46A3C64754894BA4EB45BE428A`
- **name**: `Tenant GPU Analysis-20260423-211624`
- **URL**: https://<tenant>.strategy.com/MicroStrategyLibrary/app/library#/model/7CA52A46A3C64754894BA4EB45BE428A
- **project**: Shared Studio (`1FC5A43B374C963CC773C285DF86E2F6`)
- **destination folder**: `DC377018BD4CACD81B7E4CAEB8DB62B4` (Shared Reports/Collaboration/<operator>)
- **data-serve mode**: `in_memory`
- **description**: "GPU cluster analysis across tenants, hourly usage, service quality, and incidents. Tenants + hourly usage from Snowflake; service telemetry + incidents from PostgreSQL. Row-level security via Tenant."

## Tables
| Table | id | rows (approx) |
|---|---|---|
| incidents (Neon/public) | `84133D6FB6184BE5A4BA8FD43C9BDA16` | small |
| tenant_service_hourly (Neon/public) | `0536BC83ADC242CDB17518F7910F313A` | ~126k |
| TENANTS (<snowflake-db>/<snowflake-schema>) | `854074F02BEA4AF580B7B217C4791D1D` | 10 |
| USAGE_HOURLY (<snowflake-db>/<snowflake-schema>) | `FC75A50067A04CB58377121B1CF4AF46` | ~126k |

## Semantic objects (post-build + surgery)
- 22 attributes (conformed: Tenant on 4 tables, Cluster on 3, Service Timestamp on 2)
- 33 fact metrics (sum/avg per the modeling playbook)
- 16 attribute relationships committed (`changeset B877C189F6D6411CBEF2601AEC89E307`)

## Security
- **SF**: `A5F38FC12A104642A0A21849A2DE79D4` — name "Tenant = Acme Compute" (shape B element_list, `hAcme Compute`)
- **Assigned user**: <sf-assignee> — `DBE00854E14B8D8919D3FBADCA61894B`, abbreviation `<sf-assignee-login>` (HTTP 204 from `PATCH /api/dataModels/{id}/securityFilters/{sf}/members`)

## DataType cleanse
- Committed at 21:55:07 (changeset `2C2EEB593FDA478984CAB6E3CD7EBD57`)
- 62 columns re-typed across 4 tables (`variable_length_string` / `fixed_length_string` → `utf8_char(32000,0)`, `decimal scale=0` → `int64`, `decimal scale>0` → `double`, `binary` → `integer(2,0)`, `time_stamp` → `(26,6)` or `(23,9)`, `date` → `(10,0)`)

## Publish (paused in progress)
- **Job**: `13507` — started **22:06:36** via `POST /api/cubes/{id}?cubeAction=publish` (202 accepted) + `POST /api/dataModels/{id}/publish` (204)
- **Instance**: `661A3D41094B9B2B92F77DABBDBA3A09`
- Between 22:06:51 and 22:11:38, 21 polls of `GET /api/dataModels/{id}/publishStatus` all returned `500 ERR001 iServerCode -2147072194` — "Cube report … is being published by job 13507". This is NOT the parallel-mode stall (`-2147212544`) that blocked earlier attempts before the datatype cleanse.
- Interpretation: publish is running; the 3-step status endpoint can't report progress while the `/api/cubes` publish holds the cube lock. Either use UI to watch the cube OR probe via Trino (model won't appear in MCP `get_mosaic_models` until `loaded`).

## Known blockers (in order hit)
1. **Multi-DB `connect_live` forbidden** — switched to `in_memory` during build (memory pre-existing).
2. **`build_mosaic.py` conformance rejects duplicate names** (`8004e409`) — fixed via post-build PATCH to add multi-table expressions (see `surgery.py`).
3. **`build_mosaic.py` relationship pass hit `8004ccdb`** ("attribute appears in rel more than once") — the helper declared Tenant as child of 3 relationships using the same attribute id. Fixed with `rels.py` (grouped by child, one PUT per child with all parents).
4. **Interactive project session cap `8004cb0a`** — tripped after ~12 CLI invocations; 15 min of 30s-backoff until reap. Fixed by collapsing all follow-up work into ONE `requests.Session` (memory `feedback_one_session_per_build.md`).
5. **Parallel-mode stall `-2147212544`** on publish pre-cleanse — warehouse-catalog dataTypes silently break in-memory publish. Fixed with `cleanse.py`.
6. **SF create failed with `attribute_form_custom` (`8004c767`)** — Mosaic rejected the DESC form binding. Fixed with Shape B `predicate_element_list` using `hAcme Compute`.
7. **Model description length cap `8004cc10`** — ~250 char max. Shorter version accepted (memory `feedback_mosaic_description_length_cap.md`).
8. **Publish status polling blocked during in-flight publish** (ERR001 / -2147072194) — Strategy's status endpoint can't report while `/api/cubes` holds the lock. This is current state; cube may be finishing server-side.

## Durable memories added this run
- `memory/feedback_one_session_per_build.md`
- `memory/feedback_security_filter_naming.md`
- `memory/feedback_mosaic_description_length_cap.md`
- `memory/checklist_strategy_automation_modeling_playbook.md`

(All indexed in `memory/MEMORY.md`.)

## Elapsed (rough)
Session start 21:09:55. Pause at 22:11:53. **~62 min total.** Of that:
- Discovery + build: ~7 min
- Surgery + PATCH (conformance, description): ~3 min
- Relationship + publish design: ~2 min
- **Session-cap wait**: ~15 min
- Post-wait rels + SF/<sf-assignee> + cleanse: ~6 min
- **Publish + probe (still running when paused)**: ~6 min
- Durable memory authoring: ~3 min
- Waiting / other: ~20 min

## Resume checklist
1. Confirm cube shows up in MCP `get_mosaic_models` (Shared Studio catalog) OR poll `GET /api/dataModels/{id}/publishStatus` — once publish job 13507 releases the cube lock, status becomes queryable.
2. Smoke query via MCP `query`: `SELECT count(*) FROM "tenant gpu analysis-20260423-211624"`.
3. Run validation comparator (see `/tmp/expected.json` for pre-computed grand totals + by-tenant aggregates from `validation.csv`).
