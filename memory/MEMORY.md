## Meta, env, and operating rules
- [User profile](user_profile.md) — Strategy Sales Engineer persona; values terse, working-code outputs across Mosaic + classic semantic layer.
- [Repo layout + purpose](project_mosaic_build.md) — what this repo does, where each skill / script / memory lives, how to extend it.
- [Environment configuration](reference_strategy_env.md) — env-var convention (`MSTR_BASE`, `MSTR_USER`, `MSTR_PASSWORD`, `MSTR_PROJECT_ID`/`MSTR_PROJECT_NAME`, `MSTR_DEST_FOLDER_ID`); no hardcoded tenants in the repo.
- [Environment preflight probe](reference_strategy_environment_probe.md) — 9-step tenant health check before build/publish/migrate; avoids halfway failures.
- [Generalize durable artifacts](feedback_generalize_durable_artifacts.md) — every skill, memory, script, and example must be tenant- / DB- / user-agnostic; concrete values go in env, flags, or `captures/`, never in durable text.
- [Automation playbook](reference_strategy_automation_playbook.md) — NLQ-to-action loop, safety model, tool routing, verification expectations.
- [Automation coverage contract](reference_strategy_automation_coverage.md) — complete-platform automation goal, coverage levels, platform-family checklist, and known-gap rules.
- [Task catalog](reference_strategy_task_catalog.md) — common Strategy requests mapped to REST / MCP / mstrio / helper surfaces.
- [Intake patterns](reference_strategy_intake_patterns.md) — turn drop-in ERDs, data dictionaries, user/email rosters, and legacy-object change requests into safe Strategy actions.
- [Surface matrix](reference_strategy_surface_matrix.md) — route ambiguous nouns (attributes, metrics, security filters, ACLs, cubes, datasets, Mosaic models, AI agents) to the right surface.
- [OpenAPI reference](reference_strategy_openapi.md) — raw `/api/openapi.yaml` discovery, key Modeling / Data Model / ACL / security endpoints, how to probe them.
- [mstrio-py reference](reference_mstrio_py.md) — when to use the official Python wrapper vs direct REST.
- [Mosaic MCP tools](reference_mcp_tools.md) — `get_projects`, `get_mosaic_models`, `get_semantics`, `query`; connected via Claude/Codex connector config.
- [Project loading + session cap](reference_strategy_project_loading.md) — `/api/projects` lists unloaded projects; probe before use. Interactive session cap fires on project-scoped calls, not `/api/auth/login` — always `DELETE /api/auth/login` on exit.

## Data modeling foundations and review
- [Data modeling foundations](reference_data_modeling_foundations.md) — durable dimensional-modeling principles: business process, grain, dimensions, facts, metrics, bridge logic, and anti-patterns.
- [Strategy schema object map](reference_strategy_schema_objects.md) — Strategy object map: tables, attributes, forms, facts, metrics, relationships, hierarchies, transformations, and security fit.
- [Strategy attribute design](reference_strategy_attribute_design.md) — attribute design rules, forms, conformance, role-playing dimensions, SCDs, degenerate dimensions, and naming guidance.
- [Strategy fact and metric design](reference_strategy_fact_metric_design.md) — fact and metric modeling rules, additive behavior, ratio safety, count patterns, and governed measure guidance.
- [Strategy relationship design](reference_strategy_relationship_design.md) — relationship cardinality, bridge logic, orphan detection, hierarchy fit, and Mosaic relationship write safety.
- [Strategy hierarchy design](reference_strategy_hierarchy_design.md) — user hierarchy design, drill paths, entry points, subject-area separation, and hierarchy anti-patterns.
- [Strategy time modeling](reference_strategy_time_modeling.md) — calendar / fiscal modeling, date roles, transformations, and comparative-period validation.
- [Strategy Mosaic modeling](reference_strategy_mosaic_modeling.md) — Mosaic-specific build sequence, conformance, relationship sequencing, changesets, and validation expectations.
- [Strategy legacy semantic modeling](reference_strategy_legacy_semantic_modeling.md) — classic semantic-layer inventory, migration mapping, legacy object interpretation, and report-driven preservation rules.
- [Strategy model validation](reference_strategy_model_validation.md) — minimum model validation suite, comparator strategy, tolerance handling, and failure triage.
- [Strategy model design checklist](checklist_strategy_model_design.md) — pre-build modeling checklist for grain, dimensions, metrics, relationships, time, and governance.
- [Strategy model build checklist](checklist_strategy_model_build.md) — build-execution checklist for discovery, changesets, sequencing, publish, and validation handoff.
- [Strategy model review checklist](checklist_strategy_model_review.md) — post-build review checklist for business fit, rollups, hierarchy behavior, validation, and documented risks.
- [Automation modeling playbook](checklist_strategy_automation_modeling_playbook.md) — pre-build design pass tying foundations/attribute/fact/relationship/hierarchy memories to concrete build steps. Apply BEFORE `build_mosaic.py build`.

## Mosaic modeling (design-time)
- [Mosaic build skill](reference_mosaic_build_skill.md) — location + subcommand list for the build helper script.
- [Mosaic preflight check (build-skill gate)](reference_mosaic_preflight_skill.md) — reference for `skill/scripts/preflight_model_check.py`, invoked as step 6 of the `build-mosaic-model` flow. 6 categories: naming, attr-vs-metric, datatype, joinability, blueprint-fit, governance. ERROR findings stop the build.
- [Mosaic REST API map](reference_mosaic_rest_api.md) — verified endpoint paths (auth, datasources, catalog, data models, changesets, security, translations).
- [Mosaic modeling concepts](reference_mosaic_modeling_concepts.md) — attributes, metrics (compound/conditional/level/transformation), relationships, filters, transformations — payload shapes.
- [Mosaic build config schema](reference_mosaic_config_schema.md) — declarative config fields and post-build derived-metric workflow.
- [Mosaic relationship archetypes](reference_mosaic_relationship_archetypes.md) — 6 canonical patterns (star, snowflake, bridge, composite-FK, descriptive, date-hierarchy) with encoding and failure modes.
- [Business-logic translation](reference_mosaic_business_logic_translation.md) — intent → entities/grain/metrics/aggregation/relationships; intake ladder, per-column decision matrix, aggregation-function table, inspection-only inference path, red flags.
- [Business-logic pass mandatory](feedback_business_logic_pass_mandatory.md) — never run build without the translation artifact + assumptions log; auto-inference ships semantically wrong models under 2xx status.
- [Mosaic derived metrics](reference_mosaic_derived_metrics.md) — compound/conditional/level metric shapes captured from the UI (ratio, filter-scoped, level).
- [Mosaic AI modeling service](reference_mosaic_ai_service.md) — `/api/aiservice/model/*` — primary keys, linking, lookup table, multi-form attributes, relationships, metrics recommendations.
- [Mosaic batch API](reference_mosaic_batch_api.md) — `POST /api/model/batch` bundles many sub-ops per changeset; `allowPartialSuccess=true` → HTTP 207 with per-op status.
- [Mosaic UI internal endpoints](reference_mosaic_ui_internal_endpoints.md) — workspace/pipeline write surface, changeset rebase, AI service hooks, executive-summary flag.
- [Mosaic model linking (data-mesh)](reference_mosaic_model_linking.md) — "Add Models" is a schema import with disambiguation, NOT a stored link; federation is by shared attribute name at query time.
- [Legacy project as Mosaic blueprint](feedback_mosaic_legacy_as_blueprint.md) — mirror the existing semantic model's shape instead of inferring from columns; avoids locale dupes, missing entities, cartesians.

## Mosaic runtime (publish, ACL, security)
- [Mosaic publish path verified](reference_mosaic_publish_path.md) — `POST /api/cubes/{id}?cubeAction=publish` (Strategy ONE Cloud UI path) + Modeling-native 3-step flow; always poll `publishStatus` or Trino-smoke before declaring success.
- [Mosaic vs Legacy surface delineation](reference_mosaic_vs_legacy_surfaces.md) — subType 779/776 classification, endpoint-pair cheat sheet, asymmetric `/api/model/dataModels` vs `/api/dataModels` paths.
- [Mosaic security filter create + assign](reference_mosaic_security_filter.md) — Modeling-scoped create + top-level `/api/dataModels/.../securityFilters/{sfId}/members` PATCH (the asymmetry is the trap).
- [Mosaic ACL read + write](reference_mosaic_acl.md) — Modeling-scoped `PATCH /api/model/dataModels/{mid}/objects/{oid}/acl` + legacy-style `showACL=true` GET.
- [Mosaic build validation](reference_mosaic_build_validation.md) — runnable post-build checklist invoked via `build_mosaic.py validate-model`; F/W checks and diff/regression mode.
- [Rollup-consistency validation](reference_rollup_consistency_validation.md) — Trino query pattern that proves joins + relationships are correct via same-total rollups across every attribute level.
- [Mosaic clone-and-remap pattern](reference_mosaic_clone_pattern.md) — cloning a reference model into a new one: fresh ids with REF dataTypes, text-only `column_reference` tokens, display PATCH post-create, commit order.
- [Strategy object cloning (generalized)](reference_strategy_object_cloning.md) — clone-and-remap across Mosaic, classic, dossier, cube, user object families.

## Mosaic build-quality rules (ship-bar feedback)
- [Consumer-grade naming rules](feedback_consumer_grade_naming.md) — attribute/form/metric naming, descriptions, formatting, no-hardcoded-identities, verify-with-query before ship.
- [Mosaic build quality rules](feedback_mosaic_build_quality.md) — 11 durable rules from the TPC-H side-by-side: form names, auto-hierarchy limits, FK coverage, composites, dates, aggregation, read-back, orphans, descriptions, diff-mode QA.
- [Mosaic forms + metric formats](feedback_mosaic_forms_and_formats.md) — every attribute's report/browse display must be its DESC form; every metric must carry a currency/percent/integer/fixed format. ID-as-display + Generic-number are never shippable.
- [Mosaic gotchas (general)](feedback_mosaic_gotchas.md) — precedence/encoding bugs and the clone-and-remap pattern for unknown payloads.
- [Mosaic REST payload gotchas](reference_mosaic_rest_gotchas.md) — verified shapes for model/table/attribute/metric POSTs, column-objectId ephemerality, pipeline physical-table shape, EOT token requirement, Trino column naming.
- [Mosaic publishable dataTypes](feedback_mosaic_publishable_datatypes.md) — warehouse-catalog types silently break in-memory publish on Strategy ONE Cloud; clone UI-created types (`utf8_char`, `integer`, `double`, `int64`, `time_stamp`) instead.
- [Multi-DB connect_live forbidden](feedback_mosaic_multi_db_connect_live.md) — Mosaic rejects ≥2 DB instances under connect_live (code 8004d232); use in_memory or split.
- [Conformance is case-sensitive + same-name-only](feedback_build_mosaic_conforming_attr_rules.md) — mixed-case warehouses or differently-named FKs yield an under-joined model silently; declare relationships explicitly.
- [Mosaic relationship wiring recipe](feedback_mosaic_relationship_wiring.md) — six-step recipe: attribute plan → dictionary conformance via identical `name` → relationships for non-shared attrs only → post-build expression verify → PATCH-before-PUT → Trino rollup check. Avoids 8004ccdb / 8004ccc7 / disconnected-star failures on multi-DB builds.
- [build_mosaic.py session leak + batched describe](feedback_build_mosaic_session_leak.md) — iServer holds a project session independent of DELETE /api/auth/login; use `describe-tables` (plural) helper to stay under the cap; NEVER chain build→publish→SF as separate shell invocations on Strategy ONE Cloud tenants (cap trips before publish's classify preflight can complete).
- [One session per build](feedback_one_session_per_build.md) — rels/publish/SF/assign/validate must run inside ONE long-lived `requests.Session()`, not chained CLI invocations; N CLI calls = N parked iServer project sessions and a guaranteed cap trip.
- [Security filter naming](feedback_security_filter_naming.md) — every SF name must describe the qualification (e.g. "Tenant = NovaForge AI"), not the user/date; keeps the security rule readable when membership rotates.
- [Mosaic description length cap](feedback_mosaic_description_length_cap.md) — data-model description is ~250 char; PATCH fails 8004cc10 above that. Keep short; detail goes in an external README.
- [Mosaic publish endpoint collision](feedback_mosaic_publish_endpoint_collision.md) — never fire `/api/cubes?cubeAction=publish` AND `/api/dataModels/{id}/publish` together; the losing instance's `publishStatus` returns 500 -2147072194 for the job's whole lifetime even while the cube finishes in seconds.

## Classic / legacy, AI, runtime, and admin
- [Legacy semantic / admin workflows](reference_strategy_legacy_semantic_admin.md) — classic project semantic layer + admin; distinguishes legacy SFs from Mosaic data-model SFs and AI/agent surfaces.
- [Legacy-to-Mosaic mining](reference_strategy_legacy_to_mosaic_mining.md) — discover candidate Mosaic tables/objects from legacy reports/documents, or reverse from table dependencies.
- [Design transition knowledge](reference_strategy_design_transition.md) — conceptual bridge from classic project schema design to modern Mosaic / USL / AI / MCP / governed model automation.
- [Tutorial semantic field study](reference_strategy_tutorial_semantic_field_study.md) — live REST inventory of Tutorial attributes, facts, metrics, filters, prompts, hierarchies, fact extensions, plus Mosaic translation rules.
- [Mosaic field study + legacy bridge](reference_strategy_mosaic_field_study.md) — live REST inventory of Mosaic data models and the object-by-object classic→Mosaic translation matrix.
- [Cube and dataset families](reference_strategy_cubes_and_datasets.md) — Intelligent/OLAP cubes, Super Cube/MTDI Push Data datasets, runtime Cube API, and Mosaic publish/materialization nuances.
- [Runtime analytics](reference_strategy_runtime_analytics.md) — report/cube/dashboard/document execution, prompt answers, runtime filters, exports, JSON Data API boundaries.
- [Report/dossier creation surface](reference_strategy_report_dossier_creation.md) — REST does NOT expose from-scratch creation of reports/dossiers/dashboards on Strategy ONE tenants; only execution against existing templates.
- [Report/dashboard/dossier authoring patterns](reference_strategy_report_authoring_patterns.md) — use mstrio-py, clone-and-retarget, or execute-and-save paths.
- [Admin platform workflows](reference_strategy_admin_platform.md) — datasource admin, distribution/subscriptions, migrations/packages, monitors/caches, search/browse, settings, project administration.
- [Subscriptions and schedules](reference_strategy_subscriptions_and_schedules.md) — delivery surface (email/file/cache/mobile) + schedules; verified payload shapes + observed server-side normalizations.
- [Package & migration lifecycle](reference_strategy_package_migration.md) — migrations/packages between projects and tenants (stub + known hooks).
- [Monitoring, jobs, alerts, caches](reference_strategy_monitoring_jobs_alerts.md) — job monitor, cache ops, alerts, and Mosaic/classic refresh triggers.
- [AI agents](reference_strategy_ai_agents.md) — Auto Agent vs deprecated Bot APIs, question/chat flows, agent config/training, nuggets/learnings, AI indexing.

## Validation
- [Data validation (paired-query)](reference_strategy_data_validation.md) — pluggable reference sources (Mosaic, legacy report, flat file, warehouse SQL, REST fixture), 5-query minimum suite.
- [Live validation suite](reference_strategy_validation_workflows.md) — non-Mosaic / non-AI validation suite with 10 workflows, runner command, cleanup rules, live-API gotchas.

## Field captures (capture targeting)
- [Chrome MCP network capture](reference_chrome_mcp_capture.md) — `read_network_requests` is opt-in per tab and only records after the first invocation. ARM the capture *before* the user interacts.
- [Local skill bundles](reference_local_skill_bundles.md) — `skills/strategy-brand` + `skills/strategy-product-knowledge` — read before brand deliverables or Strategy product content.
