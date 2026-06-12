# 2026-06-11 — Saama Pharma Clinical Observations build (Studio tenant)

**Status: COMPLETE — built, PUBLISHED (3000-row in-memory cube queryable), data-validated, ship-bar clean.** The publish "stall" was diagnosed end-to-end: `publishStatus` reports `status=1/tables:[]` even after the cube materializes, and publish jobs are slow/fragile against a cold (auto-suspended) Snowflake warehouse. Full incident log below.

## Delivered model

| | |
|---|---|
| Model | **Saama Pharma Clinical Observations** |
| model_id | `<model-id>` |
| URL | https://studio.strategy.com/MicroStrategyLibrary/app/library#/model/<model-id> |
| Project | Shared Studio (`<project-id>`) |
| Folder | My Reports (`<my-reports-folder-id>`) |
| Source | Synthetic Data (Snowflake, `<synthetic-data-ds-id>`), schema MCI_DEMO |
| Tables | 4 × SD_PHARMA_SAAMA_20260608_2319_* (CLINICAL_OBSERVATIONS fact; CLINICAL_TRIALS, PATIENTS dims; SAAMA_PRODUCTS snowflake parent) |
| Topology | Snowflake — Product Category > Product > Trial > Patient; observations fact at OBSERVATION_ID grain |
| Attributes | 13 (Product 4 forms, Patient 3 forms, Trial 2 forms; DESC-form report/browse displays; conformed Trial/Patient/Product verified spanning 3/2/2 tables) |
| Metrics | 6, all business-formatted (Avg Heart Rate, Avg Systolic BP, Avg Diastolic BP, Max Systolic BP, Observation Count, Patient Count) |
| Relationships | 13 explicit one_to_many (galaxy-safe, merged PUTs per child) |
| validate-model | **PASS** (warnings: W6 text-date grains ×4 — source stores dates as VARCHAR; W3 false-positive on PRODUCTS) |
| serve mode | in_memory |
| Publish | **CONFIRMED 15:50:30** — cube-execute probe 200, 3000-row view (trigger 15:45:23 against hot warehouse) |
| Data validation | **PASS** — base grid 3000 rows == REF comparator; Σ Observation Count by Trial (50) = 3000; Σ by Product across the snowflake chain (7) = 3000; Σ Patient Count by Gender (3) = 500 (= 6 obs/patient); vitals plausible (HR 75, BP 111/80). Three scripted FAILs in `validation.json` are artifacts of the metrics-only view quirk (below), not model defects. |

## Tenant rules applied (why this run looked different from April's)

1. **identity token OFF** for every call — `feedback_mosaic_identity_token_privilege_downgrade.md` (403 8004cb09 otherwise). Verified working: all Modeling writes succeeded with standard token + `X-MSTR-ProjectID`.
2. **ONE process / ONE session** for the whole build (`feedback_build_mosaic_session_leak.md`). Build ran 15:11:44–15:22:02 in a single session; no 8004cb0a.
3. **Publishable dataTypes at CREATE time** (`reference_mosaic_publish_path.md`): all 26 columns created as `utf8_char(32000,0)` / `int64(8,0)`; post-commit audit confirmed zero dirty types.
4. **Single publish trigger per run** (`/api/cubes` run 1; Modeling 3-step run 2 — never both in one run).

## Publish incident log (2026-06-11)

| Time | Event |
|---|---|
| 15:11:55 | `POST /api/cubes/{id}?cubeAction=publish` → **202** (UI-equivalent trigger; the path April 23 verified as reliable on this tenant family) |
| 15:12–15:22 | Poll `GET /api/cubes/{id}` ×60 — response is **definition-only** (`id`,`name`,`result.definition.availableObjects`); NO status/size/rowCount fields on this tenant → memory `reference_mosaic_publish_path.md` "poll by GET /api/cubes/{id}" is NOT viable here. Doc correction queued. |
| 15:23:56 | Decisive probe `POST /api/v2/cubes/{id}/instances` → **500 iServerCode -2147072488 "Intelligent Cube … is not published"** → the 202 job never materialized the cube (silent failure, no error surfaced). |
| 15:25:02 | Run 2 (single trigger): Modeling 3-step — instance 204 → `POST /api/dataModels/{id}/publish` (4 tables, refreshPolicy=replace) → 204 |
| 15:25:12+ | `publishStatus` poll: **status=1, tables=[] sustained** (the "silent no-op" signature previously attributed to dirty dataTypes — but our types are verified clean → a second stall cause exists on this tenant) |

### Hypotheses + canary results (15:35–15:40)
- **Privileges (eliminated).** `GET /api/sessions/privileges`: Publish Intelligent Cube (162), Web publish (164), Administer Cubes (144), Monitor Cubes (143), Use Mosaic Studio (316) ALL granted — 316 now even at USER level (the June 9 project-only state was upgraded since; identity-token downgrade rule may be moot going forward, but identity-off still works and remains the safe default here).
- **DataTypes (eliminated).** REF model `<ref-model-id>` (June 9, same warehouse tables) carries byte-identical types to ours: `int64(8,0)` + `utf8_char(32000,0)`.
- **Tenant publish path worked ≤June 9.** REF executes fine TODAY (`POST /api/v2/cubes/{ref}/instances` → 200, 3000-row view, dataServeMode=in_memory) — previously-published cubes serve; the failure is specific to NEW publish jobs.
- **H4 stale lock** — publishStatus stayed clean 200/status=1 (never -2147072194), so no actively-publishing competitor; job monitor returned 400 (params/privilege), no view into the queue.
- **Run 2 final:** 3-step Modeling publish polled 10 min: status=1, tables=[] from first to last sample. Job claims to run, never reports per-table progress, never errors.
- **Minimal canary build** (1 table / 1 attr / 1 metric, same DS, fresh model): run below.

### New tenant rule discovered while building the canary
- **`8004cf06` — "Attribute … cannot be saved because it has no report display"** at changeset COMMIT. Every attribute must get a `displays` PATCH (reportDisplays + browseDisplays) before commit on this tenant. The main driver always did this (ship-bar DESC displays), which is why the full build committed clean. Any minimal/maintenance script that creates attributes must do the same.

### Differential results (15:37–15:50) — VERDICT: tenant-side CubeServer publish jam
| Test | Result | Eliminates |
|---|---|---|
| 1-table in-memory canary publish (`canary_build.py`) | **TIMEOUT_status1** — same stall as the 4-table model | model shape / size / our payloads |
| connect_live canary, same DS + table | **LIVE_OK_rows=7** (execute 200; ~2 min first-query latency = Snowflake warehouse auto-resume) | warehouse health, DS connection, credentials |
| Fresh publish fired while warehouse HOT (`hot_warehouse_publish.py`, 15:45:23, <1 min after live query) | **stall (status=1, tables=[])** | warehouse-suspension handling |
| REF model (June 9) cube execute | 200, 3000-row view | cube-serving infra, privileges, dataTypes |

**RESOLUTION (15:50:30).** The execute probe after the hot-warehouse trigger returned **200 with the full 3000-row cube** — 9 seconds after `publishStatus` was still reporting `status=1, tables:[]`. Two root-cause findings replace the "tenant jam" hypothesis:

1. **`publishStatus` is unreliable on this tenant family.** It reported `status=1, tables:[]` for the ENTIRE life of a publish that succeeded — it never flipped to per-table `loaded`. Any poll loop keyed on it alone will mis-declare failure forever. The cube-execute probe (`POST /api/v2/cubes/{id}/instances?limit=1` → 200 vs `-2147072488`) is the only trustworthy completion signal observed.
2. **Cold Snowflake warehouse stretches publish invisibly.** Triggers fired against the auto-suspended warehouse (20:11:55Z, 20:25:02Z) showed nothing queryable for 12+ minutes (negative execute probe at 20:23:56Z). After the connect_live canary forced a warehouse resume (~2-min first query, 20:42–20:44Z), the 20:45:23Z trigger had the cube queryable by 20:50:30Z. Operational rule: pre-warm the warehouse (any small live query) before triggering, and budget 10–15 min of execute-probe polling before declaring failure. Cannot fully exclude that one of the earlier queued jobs eventually drained instead — but the warehouse-temperature correlation is exact, and either way the operational rules are identical (probe with execute; don't panic-retrigger; pre-warm).

### Validation of the published cube (15:53–16:04)
`validate_live.py` (run with `SKIP_FLIP=1` against the published cube — the connect_live flip fallback was unnecessary). Results: base grid 3000 rows; by-Trial 50 rows Σ=3000; by-Product 7 rows Σ=3000 (two-hop snowflake rollup exact); by-Gender 3 rows Σ Patient Count=500; per-row vitals plausible. **API quirk:** `requestedObjects` with metrics-only (no attributes) does NOT aggregate to a grand-total row — it returns the base-grain grid (3000 rows); aggregation happens only when ≥1 attribute is requested. The script's three "FAIL" lines compare against that broken totals view — recorded as artifacts, model verdict PASS.

## Durable fixes landed in the repo this session

1. `schema_object_translator.normalize_datatype` — completed the canonical publishable mapping: `decimal(P,S>0)→double(P,S)`, `time_stamp(8)→(26,6)`, `time_stamp(9)→(23,9)`, `date→(10,0)` (idempotent pass-through for already-clean shapes). Unit tests added (8 new cases); suite 115/115 green.
2. `build_mosaic.cmd_build` — table columns AND metric dataTypes now routed through `sot.normalize_datatype` (was: raw warehouse-catalog sentinels forwarded verbatim → the April publish stall root cause could recur on every plain `build` run).

## Tenant findings queued for memory updates

- `GET /api/cubes/{id}` is definition-only on this tenant family — cannot be used as a publish-status poll (contradicts one line of `reference_mosaic_publish_path.md`).
- `POST .../factMetrics` with `function:"count_distinct"` → 500 on this tenant; `count` accepted (driver fell back automatically).
- `POST /api/model/dataModels/{id}/hierarchies` AND `/userHierarchies` → 404 8004cc04 on this tenant build (cmd_build's auto-hierarchy would silently skip too; drill paths still work via relationships).
- Custom attribute-form categories (`CODE`, `LONGDESC`, `FIRSTNAME`) ARE accepted by the Modeling service (multi-form attributes with DESC displays work at CREATE time — no fragile post-PATCH needed).
- `-2147072488` = "cube not published" on execute — the definitive negative probe for publish completion.

## Files

- `discover.py` / `discovery.json` — tenant discovery (projects, folder, datasource, tables, columns)
- `build-plan.json` — business-logic translation artifact + assumptions log (pre-build, mandatory)
- `preflight.json` — preflight gate output (0 ERROR / 0 WARN / 9 INFO)
- `build_driver.py` — single-session build driver (the run that built the model)
- `driver_run1.log` — full run-1 log (build PASS, publish poll timeout)
- `driver_state.json` — all object IDs (tables, attributes, metrics) for resume
- `probe_publish.py` — cube-execute probe (returned -2147072488)
- `diagnose_publish.py` / `publish_diag.json` — 3-step publish diagnostic (run 2)
- `canary_probe.py` / `canary.json` — tenant-health canary (June 9 model execute + job monitor)
