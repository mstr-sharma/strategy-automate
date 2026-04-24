---
name: strategy-automation
description: Automate Strategy (formerly MicroStrategy) environments from natural-language requests. Use for any Strategy REST, Mosaic semantic model, datasource/catalog, project/folder/object, report/dashboard/document, cube/cache, security/governance, user/group, subscription, migration, monitoring, or mstrio-py task. Routes NLQ work to the local Strategy memory, OpenAPI spec, authenticated REST helper, Mosaic builder skill, MCP query tools, or mstrio-py as appropriate.
---

# Strategy Automation

Use this skill when the user asks to automate, inspect, build, modify, secure, publish, query, migrate, monitor, or administer anything in Strategy / MicroStrategy. The coverage goal is platform-wide automation wherever Strategy exposes an API, SDK, MCP, CLI, or reproducible hook; when no hook is verified, state the gap instead of improvising.

## First Move

1. Read `$REPO/memory/MEMORY.md`.
2. Identify the task family in `$REPO/memory/reference_strategy_automation_playbook.md`.
3. Read `$REPO/memory/reference_strategy_automation_coverage.md` for broad or audit-style requests, then classify coverage as wrapped helper, generic REST hook, specialized hook, captured fallback, or known gap.
4. Decide the product surface before choosing endpoints: classic project semantic layer/admin, Mosaic data model, runtime analytics, Push Data dataset, cube family, platform admin, or AI/agents. Read `reference_strategy_surface_matrix.md` for ambiguous attributes, metrics, prompts, filters, ACLs/object security, security filters, cubes, datasets, reports, dashboards, documents, users/groups, agents, or project-level requests.
5. Use live `{Library}/api/openapi.yaml` through the helper when endpoint details matter. Add `?visibility=all` when the Swagger UI shows more detail than the default spec. A local `openapi.yaml` may be generated for temporary caching, but it is not part of the lean repo.
6. Use credentials from environment (`MSTR_PASSWORD`) or user-provided secure runtime values. Never write secrets to memory, skills, config, or logs.

## Skill precedence (one-way — no loops)

This skill is the **NLQ classifier**. After classifying the surface, it hands off downward and does NOT take back control:

```
strategy-automation (this skill — classify)
  ├─► strategy-data-modeling (plan, Kimball-first)    ← all modeling work routes here
  │     └─► skill/SKILL.md (build-mosaic-model)
  │           └─► strategy-validation (verify)
  ├─► skill/SKILL.md directly                         ← only for post-build admin edits on known-good plans
  ├─► strategy-validation directly                    ← for data-correctness checks on an existing model
  └─► REST / mstrio-py / MCP                          ← for admin/runtime/non-modeling work
```

`strategy-data-modeling` does NOT route back here. Once a modeling task is classified, planning owns the handoff to build/validate.

## Tool Router

- **Any semantic-model design / review / migration / cleanup:** route to `strategy-data-modeling/SKILL.md`. That skill is Kimball-first and produces the model plan before any REST write. Do not re-implement modeling decisions in this skill.
- **Legacy-to-Mosaic migration:** `strategy-data-modeling/SKILL.md` owns the plan. It will use `strategy_semantic_inventory.py` or `strategy_semantic_mine.py` for discovery, then hand off to `skill/SKILL.md` for the build. Do not treat migration as a greenfield shared-column inference job unless no legacy semantic source exists.
- **Brand-new Mosaic model:** same — `strategy-data-modeling/SKILL.md` plans, `skill/SKILL.md` builds, `strategy-validation/SKILL.md` verifies.
- **Direct post-build edits on a known-good model (rename, ACL change, single-metric format fix):** `skill/SKILL.md` (build-mosaic-model) accepts those directly without re-planning.
- **Classic-to-modern modeling judgment:** read `reference_strategy_design_transition.md` before translating legacy project schema concepts into Mosaic/USL/AI-ready models.
- **Classic/project semantic-layer or admin workflows:** read `reference_strategy_legacy_semantic_admin.md`; use top-level `/api/model/...` changeset endpoints for legacy objects and `/api/users`, `/api/securityFilters`, `/api/usergroups`, `/api/objects` for admin/member operations.
- **Deep classic semantic inspection:** read `reference_strategy_tutorial_semantic_field_study.md`; use `skill/scripts/strategy_semantic_inventory.py` to inventory attributes, facts, metrics, filters, prompts, system hierarchy, user hierarchies, fact extensions, metric dimensionality/conditionality, and prompt/filter internals before cloning or modernizing.
- **Deep Mosaic semantic inspection / legacy↔Mosaic bridge:** read `reference_strategy_mosaic_field_study.md`; use `skill/scripts/strategy_mosaic_inventory.py` to inventory every Mosaic data model (subType 779) — tables, attributes, factMetrics, custom metrics, hierarchy, security filters, externalDataModels — and reference the classic→Mosaic translation matrix for object-by-object mapping. Use `/usr/bin/python3` on this workstation (Anaconda OpenSSL hangs on {MSTR_BASE host} TLS).
- **Legacy-to-Mosaic discovery:** read `reference_strategy_legacy_to_mosaic_mining.md`; use `skill/scripts/strategy_semantic_mine.py` to mine reports/documents into candidate tables or reverse from tables into attributes/facts/metrics/reports before building a Mosaic model.
- **Security filters:** if no Mosaic data-model ID is in the request, treat it as a classic project security filter: create definition with `/api/model/securityFilters`, assign users/groups with `/api/securityFilters/{id}/members`. Use `/api/model/dataModels/{id}/securityFilters` only for Mosaic data-model security filters.
- **Attributes and metrics:** route by container. Classic/project objects use `/api/model/attributes|metrics`; Mosaic-contained objects use `/api/model/dataModels/{id}/attributes|metrics|factMetrics`; Push Data dataset attributes/metrics live in `/api/datasets` definitions.
- **ACL/object security:** classic object ACL uses `GET/PUT /api/objects/{id}?type=...`; Mosaic-contained object ACL uses `/api/model/dataModels/{id}/objects/{objectId}/acl`; security roles/privileges are separate from ACL and security filters.
- **Cubes/datasets:** read `reference_strategy_cubes_and_datasets.md`; Intelligent/OLAP cubes, Super Cube/MTDI Push Data datasets, DDA/MDX runtime cubes, and Mosaic models use different endpoint families.
- **Legacy-vs-Mosaic surface guard (must-read before any publish/refresh/execute write):** read `reference_mosaic_vs_legacy_surfaces.md`. **Hard rule:** before hitting `/api/cubes/...`, `/api/dataModels/...`, or `/api/model/dataModels/.../publish`, classify the target via `GET /api/objects/{id}?type=3` → `subtype`. 779 → Mosaic data model (use `/api/dataModels/{id}/publish` + instance header + `tables[]` body + poll `/publishStatus`). 776 → classic Intelligent Cube (use `/api/cubes/...`). Never treat a legacy 2xx as evidence a Mosaic model is published. `build_mosaic.py publish` now routes by subType; do not bypass it with ad-hoc `/api/cubes/*` calls.
- **Reports/dashboards/documents runtime:** read `reference_strategy_runtime_analytics.md`; create instances, answer prompts, apply runtime filters, then fetch/export results.
- **Platform admin:** read `reference_strategy_admin_platform.md`; datasource admin, distribution/subscriptions, migrations/packages, monitors/caches, project load/unload, settings, search/browse, and object ownership have separate endpoint families.
- **AI/Agent/Bot:** read `reference_strategy_ai_agents.md`; prefer Auto Agent `/api/questions` and `/api/v2/bots` paths; treat `/api/bots` as legacy/deprecated unless required.
- **Validation/testing:** read `reference_strategy_validation_workflows.md`; do not run live write tests until the user signs off on the numbered workflows and cleanup behavior.
- **Data-correctness validation (post-build, pre-ship):** route through `strategy-validation/SKILL.md` and `reference_strategy_data_validation.md` (covers both the design-time 10-check suite and the runnable 5-query paired-query suite). Reference can be another Mosaic model, legacy/classic report, flat file, direct warehouse SQL, or a saved REST fixture — NOT Mosaic-to-Mosaic only. Required after every build per `feedback_consumer_grade_naming.md` item 8.
- **Drop-in ERDs, dictionaries, rosters, or legacy update briefs:** read `reference_strategy_intake_patterns.md`, normalize files to supported JSON/YAML/CSV/DBML/Mermaid/SQL formats, then resolve IDs before writing.
- **Any REST endpoint not wrapped yet:** use:
  ```bash
  cd "$REPO"
  python3 skill/scripts/build_mosaic.py openapi-search "<term>" --context 2
  python3 skill/scripts/build_mosaic.py api-call --method GET --path /api/projects
  ```
  This is a generic API hook, not proof that the workflow has a typed wrapper or full validation.
- **Users and access targets:** use `resolve-users` before ACL/security/user writes; use `create-users` for roster dry-runs and `--yes` only when the user clearly wants creation.
- **Existing or legacy schema objects:** use `search-objects`, then `get-model-object --show-expression-as tokens|tree`, then `patch-model-object --before-out ... --yes` after reviewing the payload.
- **Published-model semantic inspection/query:** use the Mosaic MCP tools when available (`get_projects`, `get_mosaic_models`, `get_semantics`, `query`), or Trino notes in memory.
- **Admin/read workflows with stable wrappers:** mstrio-py is acceptable for users/groups, security roles, schedules/subscriptions, caches, object search, and settings. Capture the equivalent REST path if it becomes a reusable workflow.
- **Unknown modeling payload:** `GET` a working object, clone/remap IDs, then `POST`/`PATCH` through Modeling Service.

## Operating Rules

- Prefer tenant-verified gotchas over public docs when they conflict.
- For classic/project workflows, do not automatically add `X-MSTR-IdentityToken`; `a verified Strategy Cloud tenant` showed it can break top-level Modeling Service reads with a false project error. Use identity token only when the selected surface/reference says it is required.
- For destructive operations, enumerate the target object IDs and ask once if the user did not explicitly request deletion/removal.
- Use changesets for Modeling Service writes, commit only after all referenced objects exist, and discard failed changesets.
- For schema/model writes, print or return the object URL, object IDs, and any skipped/failed operations.
- Keep durable lessons in `$REPO/memory/feedback_mosaic_gotchas.md` or a specific reference file.
- For platform coverage audits, update `$REPO/memory/reference_strategy_automation_coverage.md` and `$REPO/memory/reference_strategy_task_catalog.md` with any new wrapped helper, generic hook, specialized hook, captured fallback, or known gap.

## Memory Map

- Error-code index (grep first on any 4xx/5xx): `reference_strategy_error_codes.md`
- Kimball modeling foundations: `reference_data_modeling_foundations.md`
- Strategy schema object map: `reference_strategy_schema_objects.md`
- Attribute design: `reference_strategy_attribute_design.md`
- Fact and metric design: `reference_strategy_fact_metric_design.md`
- Relationship design: `reference_strategy_relationship_design.md`
- Hierarchy design: `reference_strategy_hierarchy_design.md`
- Time modeling: `reference_strategy_time_modeling.md`
- Mosaic modeling execution guidance: `reference_strategy_mosaic_modeling.md`
- Legacy semantic modeling and migration framing: `reference_strategy_legacy_semantic_modeling.md`
- Model + data validation: `reference_strategy_data_validation.md`
- Environment and credentials: `reference_strategy_env.md`
- Raw REST spec usage: `reference_strategy_openapi.md`
- Broad task routing: `reference_strategy_automation_playbook.md`
- Automation coverage contract: `reference_strategy_automation_coverage.md`
- Task-to-endpoint catalog: `reference_strategy_task_catalog.md`
- Drop-in ERD/dictionary/user-list/legacy-update intake: `reference_strategy_intake_patterns.md`
- Surface routing matrix: `reference_strategy_surface_matrix.md`
- Legacy/project semantic-layer and admin workflows: `reference_strategy_legacy_semantic_admin.md`
- Legacy-to-Mosaic mining: `reference_strategy_legacy_to_mosaic_mining.md`
- Tutorial semantic field study: `reference_strategy_tutorial_semantic_field_study.md`
- Mosaic field study + legacy↔Mosaic bridge: `reference_strategy_mosaic_field_study.md`
- Classic-to-modern design transition: `reference_strategy_design_transition.md`
- Cube and dataset families: `reference_strategy_cubes_and_datasets.md`
- Runtime analytics/prompts/filters/exports: `reference_strategy_runtime_analytics.md`
- Platform administration: `reference_strategy_admin_platform.md`
- AI agents/bots/chats: `reference_strategy_ai_agents.md`
- Live validation suite: `reference_strategy_validation_workflows.md`
- Mosaic modeling payloads: `reference_mosaic_modeling_concepts.md`
- Mosaic build CLI: `reference_mosaic_build_skill.md`
- mstrio-py role: `reference_mstrio_py.md`
