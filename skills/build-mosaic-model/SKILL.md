---
name: build-mosaic-model
description: Build a Strategy Mosaic (MicroStrategy) semantic model from scratch against live warehouse tables. Use when the user asks to "build a mosaic model", "create a semantic model in Strategy", or provides a DB instance + schema + tables and wants a model wired up. Handles auth, warehouse-table discovery, model/table/attribute/metric creation, relationships, ACL, security filters, publish, and post-build edits via `scripts/build_mosaic.py` against the Strategy REST API. Kimball-first: expects star / snowflake / galaxy topology with conformed dimensions.
---

# Build a Strategy Mosaic model from scratch

This skill is the **execution layer** for Mosaic data-model creation and modification. The **planning layer** is `skills/strategy-data-modeling/SKILL.md` — route through it first unless the user gave you a complete pre-planned build.

**Out of scope for this skill** — route to `skills/strategy-automation/SKILL.md` and `memory/reference_strategy_surface_matrix.md`:
- Classic / project semantic-layer objects (legacy attributes, project metrics/facts/filters, project security filters)
- Runtime analytics (reports, dashboards, documents, prompt answers, exports)
- AI / Agent / Bot work
- Non-Mosaic cube / dataset work (Intelligent Cube, OLAP cube, Super Cube, MTDI, Push Data)
- Subscriptions, users, groups, roles, VLDB, object administration

## Load these memory files on entry

Every one of these owns a piece of the build surface; this skill delegates the detail to them. Load before synthesizing any payload.

- `memory/reference_strategy_error_codes.md` — grep this **FIRST** on any 4xx/5xx before looking anywhere else.
- `memory/reference_data_modeling_foundations.md` — Kimball: grain, conformed dims, star/snowflake/galaxy/bridge topology, additivity classes.
- `memory/reference_mosaic_business_logic_translation.md` — intent → build plan; the mandatory pre-build artifact.
- `memory/feedback_business_logic_pass_mandatory.md` — non-optional rule.
- `memory/feedback_mosaic_relationship_wiring.md` — conformed-dim recipe + the `8004ccdb` / `8004ccc7` / `8004e409` failure modes + fix pattern.
- `memory/feedback_build_mosaic_session_leak.md` — one-session-one-process rule; the single most common cause of mid-build failure.
- `memory/reference_mosaic_rest_api.md` — verified endpoint paths (auth, datasources, catalog, data models, changesets, security, translations).
- `memory/reference_mosaic_modeling_concepts.md` — payload shapes for attributes, metrics (compound / conditional / level / transformation), relationships, filters, transformations.
- `memory/reference_mosaic_publish_path.md` — the one publish file: 3-step flow, do-not-fire-both rule, dataType publish-readiness gate (prevents iServerCode -2147212544 stalls).
- `memory/reference_mosaic_vs_legacy_surfaces.md` — subType 779 vs 776 classification before any publish/refresh/execute write.
- `memory/reference_strategy_object_cloning.md` — clone-and-remap procedure when a payload shape is unknown.
- `memory/feedback_mosaic_ship_bar.md` — ship-bar checklist: naming, DESC-form report/browse displays, metric format tokens, description length cap, SF naming.

## User inputs

- **DB instance name** (looked up by name, resolved to `dbInstanceId`)
- **Schema** (warehouse namespace)
- **Table names** (may span multiple DB instances; each `(instance, schema, table)` triple is treated independently but all tables land in one model)
- Optional: derived metrics, security filters / ACL grants or denies, `data_serve_mode` (`connect_live | in_memory | hybrid`), translations, certification, publish / refresh instructions.

**Destination folder and project** are read from env vars (`MSTR_BASE`, `MSTR_PROJECT_ID`/`MSTR_PROJECT_NAME`, `MSTR_DEST_FOLDER_ID`). See `memory/reference_strategy_env.md`.

## Deliverable

A committed Mosaic data model containing:

- One logical table per input physical table
- Attributes (one per ID/key/text column, multi-table expressions for conformed dims)
- Fact metrics (aggregation function chosen per column semantics — never blanket SUM)
- Relationships (inferred from shared keys + ERD/dictionary overrides)
- Security filters, ACL grants/denies, translations, certification as requested
- Optional publish (for in-memory) or serve-mode switch
- Model URL: `{BASE}/app/library#/model/{modelId}`

## Execution flow — single process, single session

**Always use `scripts/build_mosaic.py`**. Do not re-implement REST calls inline. Chain the pipeline in one Python process — see `memory/feedback_build_mosaic_session_leak.md`.

1. **Confirm env.** Credentials must come from `MSTR_PASSWORD` or `--password`; no hardcoding.
2. **Auth (handled by script).** `POST /api/auth/login` for `X-MSTR-AuthToken`; `POST /api/auth/identityToken` for `X-MSTR-IdentityToken` (required for Modeling Service writes on Mosaic data models; do NOT add to classic/project workflows).
3. **Resolve DB instance.** `list-datasources --name <substr>`; fail loud on ambiguity.
4. **Discover warehouse tables.** `describe-tables` (plural — one login per run). Endpoints are `GET /api/datasources/{id}/catalog/namespaces/{namespaceId}/tables` and `GET /api/datasources/{id}/catalog/tables/{tableId}` with base64 namespace/table IDs. Use `discover` for live path variants if on an unfamiliar iServer build.
5. **Translate business logic → build plan.** Produce the artifact described in `memory/reference_mosaic_business_logic_translation.md`: topology declaration, table-role classification (fact/dim/bridge/etc.), grain per fact, conformed-dim enumeration, attribute plan, metric plan (with additivity), relationships, assumptions log. Mandatory even with no supplied context — inspection-only inference is still a pass, not a skip.
6. **Preflight gate (ERROR-severity = stop).**
   ```bash
   python3 scripts/preflight_model_check.py \
     --instance "<DB Instance>" --schema <SCHEMA> \
     --tables <T1> <T2> ... \
     [--blueprint /tmp/blueprint.json] \
     --out /tmp/preflight.json --fail-on ERROR
   ```
   Exit code 1 = fix input before calling `build`. See `memory/reference_mosaic_preflight_skill.md`.
7. **Build.** Either:
   - `build --name ... --source "INSTANCE:SCHEMA:T1,T2,..." --dictionary /tmp/dict.json [--erd /tmp/erd.dbml] [--data-serve-mode ...] [flags for SF/ACL/translate/certify/publish]`, OR
   - `build-from-config --config spec.yaml` for declarative multi-step builds (preferred when applying SF + ACL + publish + certify).
8. **Verify conformance.** For every attribute you expect to be a conformed dim, `get-model-object --kind attribute --model-id ... --object-id ...` and confirm `forms[*].expressions[*].tables` covers every expected table. If missing, PATCH before writing relationships. See `memory/feedback_mosaic_relationship_wiring.md`.
9. **Relationships (second changeset).** Issue only the PUTs that pass the step-3 and step-5 prerequisites in the wiring recipe.
10. **Quality gate.** `validate-model --model-id M [--strict-orphans] [--diff-against OTHER_ID] [--json]` — enforces the rules in `feedback_mosaic_build_quality.md`. Exits non-zero on failure.
11. **Publish (in-memory only).** `publish --model-id M`. ONE trigger per run — never fire `/api/cubes` AND `/api/dataModels/{id}/publish` together (see `memory/reference_mosaic_publish_path.md`). For `connect_live` models, skip publish — it's a no-op.
12. **Validate data correctness.** Route through `skills/strategy-validation/SKILL.md` with a trusted comparator. A build without validation is not shippable.
13. **Print the model URL.**

## Naming, descriptions, and inputs from ERDs / dictionaries

The skill uses a three-tier fallback for every attribute + metric:

1. **Explicit override** — `--dictionary path.{json,yaml,csv}` entry for `TABLE.COLUMN`.
2. **ERD relationships** — `--erd path.{json,yaml,dbml,mmd,sql}` (repeatable) overrides shared-column inference.
3. **Inference** — friendly-title-case column name; metric name `Total <Col> (<Short Table>)`; shared-column → `one_to_many` with child table as the join table.

Supported ERD formats (parsed by `load_erd`): JSON/YAML list of `{parent,child,relationship_table,type}`; DBML `Ref:`; Mermaid `erDiagram`; SQL DDL `REFERENCES`.

Supported dictionary formats (parsed by `load_dictionary`): JSON/YAML with `attributes`, `metrics`, `relationships`, `tables`; CSV with `table, column, kind, name, description, function`.

If the user supplies an **image ERD**, Claude reads it in-session, converts to the supported format, saves to `/tmp/<model>.erd.json`, and passes via `--erd`.

**Descriptions are Claude's responsibility.** Auto-generate business descriptions from column/table semantics before the build runs — never ship mechanical "Column X from table Y" descriptions when domain knowledge yields something meaningful. Only fall back to the generic template when the column name is truly opaque.

## User + access preflight

Before any ACL / security-filter / user writes:

```bash
python3 scripts/build_mosaic.py resolve-users --user <name-or-email>   # or --file users.csv
python3 scripts/build_mosaic.py search-objects --name "<Object>"        # get object IDs
python3 scripts/build_mosaic.py get-model-object --kind legacy_attribute --object-id ATTR_ID --show-expression-as tokens --out /tmp/before.json
```

Only PATCH after the exact ID and body are reviewed:

```bash
python3 scripts/build_mosaic.py patch-model-object \
  --kind legacy_attribute --object-id ATTR_ID \
  --json-file /tmp/attribute.patch.json \
  --before-out /tmp/attribute.before.json \
  --yes
```

Modeling Service `PATCH` replaces top-level fields — start from a current `GET`, keep everything that must survive, verify with another `GET`.

## Invocation examples

Single source:

```bash
python3 scripts/build_mosaic.py \
  --instance "Snowflake Prod" --schema SALES \
  --tables CUSTOMER ORDER LINEITEM \
  --name "Sales Mosaic"
```

Multi-source (forces `in_memory`; see `feedback_mosaic_multi_db_connect_live.md`):

```bash
python3 scripts/build_mosaic.py \
  --source "Snowflake Prod:SALES:CUSTOMER,ORDER" \
  --source "Postgres Billing:FIN:INVOICE" \
  --name "Customer 360" \
  --data-serve-mode in_memory
```

## Subcommand reference

Full subcommand index lives in `memory/reference_mosaic_build_skill.md`. Start there when you don't know which subcommand to run.

## Auto-detected schema topology

The skill auto-classifies topology from column-name patterns. Override with `--dictionary` + `--erd` when needed.

- **Star** — one fact, many dims, no sub-dim chains.
- **Snowflake** — dim chains naturally emerge when a dim's PK appears in another dim; auto-creates a user-defined hierarchy for the longest chain.
- **Galaxy / constellation** — conformed dim (a non-PK descriptor in ≥2 tables) is promoted to one multi-table attribute.
- **Noise columns** (skipped): `SOURCE_SYSTEM`, `LOAD_TIMESTAMP`, `LAST_UPDATED_AT`, `INGESTION_DATE`, `LOAD_DATE`, `ETL_BATCH_ID`, `DW_CREATED_AT`, `DW_UPDATED_AT` when present in 3+ tables.
- **Bridge / junction** (all-FK tables) — not auto-wired as `many_to_many`; dictionary/ERD must declare.
- **Non-Kimball (OBT / EAV / graph)** — stop and confirm with the user; reshape upstream.

## Path drift — when an endpoint 404s

Strategy REST paths drift between versions. If a call 404s:

1. `openapi-summary` to fetch live `{Library}/api/openapi.yaml`.
2. `openapi-search "<term>"` (with `?visibility=all` if Swagger UI shows more than the default spec).
3. `discover` for live catalog variants (`/api/datasources` vs `/api/dbobjects/databaseInstances`, `/catalog/tables` vs `/tables` vs `/namespaces/{ns}/tables`).
4. Update constants at the top of the helper script; update the corresponding memory file with the tenant-specific finding.

## Failure modes to watch

- **Silent under-joined model** (no error, `forms[].expressions` doesn't span all expected tables) — `feedback_mosaic_relationship_wiring.md`.
- **Session cap trip** (`8004cb0a`, iServerCode `-2147072486`) mid-pipeline — `feedback_build_mosaic_session_leak.md`.
- **Publish stall** (iServerCode `-2147212544` or `-2147072194`) — `reference_mosaic_publish_path.md` ("DataType preconditions" and "Never fire both publish endpoints" respectively).
- **Duplicate attribute name** (`8004e409`) — conformed dim not declared; see wiring recipe.
- **Form PATCH failure** (`8004cc63`, `8004cd0a`) — fix form names at CREATE time, not post-hoc PATCH.
- **Description too long** (`8004cc10`) — keep under ~250 chars (`feedback_mosaic_ship_bar.md`).

Every one of these has a row in `memory/reference_strategy_error_codes.md`. Grep there before retrying.
