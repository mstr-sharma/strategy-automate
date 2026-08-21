---
name: Mosaic YAML / OSI / dbt interchange
description: Feature matrix + caveats for moving Mosaic semantic models in/out of Strategy as native YAML, OSI YAML, or Git — and how that bridges to dbt's OSI support.
type: reference
---
Use when the user asks to import/export a Mosaic model as YAML, round-trip semantics with dbt, or interoperate via OSI (Open Semantic Interchange). Verify status against the live `whats_new.htm` before promising GA — these features move fast.

## Three distinct portability surfaces (do not conflate)

| Surface | Direction | Status (as of 2026-06) | Creates a NEW model? | Where |
| --- | --- | --- | --- | --- |
| **Native Mosaic YAML** | export + restore | GA (Mar 2026) | **No — restore-only.** Help text: "Creating new models or modifying objects directly from a YAML file is not supported." | Library → Data pane → right-click model / Info icon → **Export to YAML file** / **Restore from YAML File** |
| **Git save/restore** | save + restore | GA (Mar 2026) | No — same restore semantics, Git-backed | Mosaic model menu → Git |
| **OSI YAML** (`.osi.yaml`) | import + export | **Preview (Jun 2026)** | **Yes — import materializes external semantics** | Framed around Snowflake OSI data; preserves model info between Snowflake ↔ Strategy |

- Native-YAML restore upload cap defaults to 10 MB (`modelservice.yaml.max-size-mb` in `modelservice.conf`).

### What "import/restore a YAML" actually creates (the crux — separate 3 layers)
1. **Physical substrate** = datasource connection (database instance) + the warehouse tables. **NEVER created by any YAML path.** The YAML *references* these; they must already exist and be connected in the target tenant. True for native YAML, OSI import, and `build-from-config` alike.
2. **Semantic layer** = attributes, metrics, relationships, hierarchies. This is what a YAML can carry/recreate.
3. **Model object** = the Mosaic container.

Per-path behavior:
- **Native YAML restore**: model object (3) must ALREADY exist — you right-click an *existing* model → Restore from YAML; it reverts/overwrites the semantic layer (2). You cannot hand-author a YAML to make a new model ("Creating new models or modifying objects directly from a YAML file is not supported"). Pure backup/rollback/version-control. Help page is silent on (1) but architecture makes it mandatory.
- **OSI import (preview)**: can bring in an external semantic layer (2) and stand up model content, but maps onto EXISTING schema/data (1) — messaging is "map to existing schema attributes," "preserve" semantics Snowflake↔Strategy. Not a warehouse/connection provisioner.
- **The real from-scratch builders are NOT a YAML import**: Mosaic Studio (AI-assisted, auto-generates attrs/hierarchies/metrics from data) or the REST API / this repo's `build_mosaic.py` `build`/`build-from-config`. `build-from-config` takes a YAML *recipe* but executes live REST creates against tables that must already exist — it is a build script, not a portable model file.
- **REST endpoints exist as of 2026-08-17 (studio tenant, verified working):** native YAML = `POST /api/model/dataModels/{id}/export` (documented in openapi.yaml; requires `X-MSTR-MS-Changeset` header — open a non-schemaEdit changeset first; returns `application/yaml` ONLY with an explicit `Accept: application/yaml` request header — a JSON-defaulting session gets the same model as JSON, verified 2026-08-20 DevOpsCo export; both endpoints honor the header, YAML bodies open with a `---` doc marker so the `version:` line is line 2). OSI = `POST /api/model/dataModels/{id}/osi/export` — **UNDOCUMENTED** (absent from openapi.yaml; found by probing path candidates after the UI grew an 'Export to OSI YAML File' action). Same changeset header; returns OSI **v0.1.1** (`semantic_model:` root — the dbt-ingestible version, NOT public OSI v1.0), byte-identical to the UI download, filename convention `<Model>-osi.yml`. Beware: `POST .../export?format=osi` silently returns NATIVE yaml (param ignored) — check the first line (`version: "1.1"` native vs `version: "0.1.1"` OSI). All five solutions-demo repo models exported both formats this way in one session. If automation is needed, run `openapi-search "yaml"` / `"osi"` / `"restore"` against the live tenant (needs creds) to find the model-service path, then wrap via `api-call`. The repo helper has **no** OSI/dbt/native-YAML command as of this writing — only `build-from-config` (its own private YAML schema, builds via live REST against warehouse tables, not a portable definition file).

## dbt side of OSI (the bridge has a gap)

- OSI spec itself is **YAML** (`.osi.yaml`); v1.0 finalized ~2026-01-27. Top-level: `semantic_model` (containers) → `datasets` (fact/dim) → `fields`/`dimensions`, `measures`/`metrics`, `relationships`. Repo: github.com/open-semantic-interchange/OSI. Strategy joined the OSI working group Dec 2025.
- **dbt currently CONSUMES OSI, as JSON not YAML**: docs say OSI documents are `.json` files, versions **0.1.0 / 0.1.1 only**, placed in an `OSI/` dir (or `osi-paths` in `dbt_project.yml`), parsed on `dbt compile`/`dbt run`. Dataset sources must resolve to dbt **models** (not sources/seeds/snapshots). Unsupported constructs → warning `I078`, parsing continues. Output lands in `semantic_manifest.json` / `osi_document.json`.
- **dbt does NOT document an OSI export** of its native (MetricFlow) semantic models. So a clean `dbt → OSI → Strategy` round-trip is not first-class: you either hand-author/convert the OSI doc, or go through Snowflake as the hub (Strategy's import is explicitly "Snowflake OSI data").
- **Version/format mismatch is the real trap**: public OSI is YAML v1.0; dbt ingests JSON v0.1.x. Expect to convert format AND down/up-level the version when bridging.

## Practical routing today

- **Strategy → dbt**: export OSI YAML from Strategy (preview) → convert to OSI 0.1.x JSON if needed → drop in dbt `OSI/` → `dbt compile`.
- **dbt → Strategy**: no native dbt OSI export → author/convert an OSI YAML (commonly via Snowflake as hub) → import into Strategy (preview).
- **Strategy ↔ Strategy backup/migration**: use native YAML or Git restore (GA), not OSI.
- See [[reference_strategy_design_transition.md]] (YAML/Git lifecycle as a first-class success criterion) and [[reference_strategy_openapi.md]] for the endpoint-discovery path.
