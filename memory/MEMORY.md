## Meta, env, and operating rules
- [User profile](user_profile.md) — Strategy Sales Engineer persona; values terse, working-code outputs across Mosaic + classic semantic layer.
- [Repo charter + how to extend](project_mosaic_build.md) — complete Strategy platform automation; how skills/scripts/memory interact; how to add a new surface without bloat.
- [Environment configuration](reference_strategy_env.md) — env-var convention (`MSTR_BASE`, `MSTR_USER`, `MSTR_PASSWORD`, `MSTR_PROJECT_ID`/`MSTR_PROJECT_NAME`, `MSTR_DEST_FOLDER_ID`); no hardcoded tenants in the repo.
- [Environment preflight probe](reference_strategy_environment_probe.md) — 9-step tenant health check before build/publish/migrate; avoids halfway failures.
- [Generalize durable artifacts](feedback_generalize_durable_artifacts.md) — every skill, memory, script, and example must be tenant- / DB- / user- / industry-agnostic; concrete values go in env, flags, or `captures/`, never in durable text.
- [Error-code index](reference_strategy_error_codes.md) — flat lookup of every observed `8004cc##` / `iServerCode -2147…` → the memory with the fix. **Grep this FIRST on any 4xx/5xx.**
- [Automation playbook](reference_strategy_automation_playbook.md) — 4-step NLQ loop (classify surface → read memory → probe OpenAPI → confirm before write); safety model + verification expectations.
- [Automation coverage contract](reference_strategy_automation_coverage.md) — self-audit rubric: wrapped helper vs REST hook vs specialized hook vs captured fallback vs known gap.
- [Task catalog](reference_strategy_task_catalog.md) — NL-to-endpoint index: common Strategy requests → REST / MCP / mstrio / helper surface.
- [Drop-in file intake](reference_strategy_intake_patterns.md) — supported ERD formats (DBML, Mermaid, SQL, JSON/YAML), dictionary CSV/JSON shape, user-roster CSV → resolve-users/create-users flow. Read before normalizing any user-supplied file.
- [Surface matrix](reference_strategy_surface_matrix.md) — route ambiguous nouns (attributes, metrics, security filters, ACLs, cubes, datasets, Mosaic models, AI agents) to Mosaic vs classic vs runtime surface.
- [OpenAPI probing](reference_strategy_openapi.md) — `openapi-summary` / `openapi-search` commands, `?visibility=all` trick, path-drift protocol when a call 404s.
- [mstrio-py vs REST](reference_mstrio_py.md) — admin/read workflows (users, schedules, caches, subscriptions, object search, settings) OK; schema/modeling writes must stay on REST. Decision rule inside.
- [Mosaic MCP tools](reference_mcp_tools.md) — `get_projects`, `get_mosaic_models`, `get_semantics`, `query`; REST fallbacks when MCP unavailable; Trino `query` schema-name pattern.
- [Project loading + session cap](reference_strategy_project_loading.md) — `/api/projects` lists unloaded projects; probe before use. Interactive session cap fires on project-scoped calls, not `/api/auth/login` — always `DELETE /api/auth/login` on exit.

## Kimball dimensional modeling (design-time foundations)
- [Kimball foundations for Strategy](reference_data_modeling_foundations.md) — grain, conformed dims, star/snowflake/galaxy/bridge topology, additivity classes, anti-patterns. **Strategy's engine is built for star/snowflake; non-Kimball shapes stop-and-confirm.**
- [Strategy schema object map](reference_strategy_schema_objects.md) — how Kimball concepts (tables, attributes, forms, facts, metrics, relationships, hierarchies, transformations) map to Strategy object classes.
- [Attribute design](reference_strategy_attribute_design.md) — forms, conformance, role-playing dimensions, SCDs, degenerate dimensions, naming rules.
- [Fact and metric design](reference_strategy_fact_metric_design.md) — additive/semi-additive/non-additive behavior, ratio safety (SUM(num)/SUM(denom)), count patterns, governed measures.
- [Relationship design](reference_strategy_relationship_design.md) — cardinality, bridge logic, orphan detection, hierarchy fit, Mosaic relationship write safety.
- [Hierarchy design](reference_strategy_hierarchy_design.md) — drill paths, entry points, subject-area separation, anti-patterns.
- [Time modeling](reference_strategy_time_modeling.md) — calendar / fiscal roles, date transformations, comparative-period validation.
- [Mosaic modeling sequence](reference_strategy_mosaic_modeling.md) — Mosaic-specific build sequence, conformance, relationship sequencing, changesets, validation expectations.
- [Legacy semantic modeling](reference_strategy_legacy_semantic_modeling.md) — classic semantic-layer inventory, migration mapping, legacy object interpretation, report-driven preservation rules.
- [Model design checklist](checklist_strategy_model_design.md) — pre-build checklist for grain, dimensions, metrics, relationships, time, governance.
- [Model build checklist](checklist_strategy_model_build.md) — build-execution checklist for discovery, changesets, sequencing, publish, validation handoff.
- [Model review checklist](checklist_strategy_model_review.md) — post-build checklist for business fit, rollups, hierarchy behavior, validation, documented risks.
- [Automation modeling playbook](checklist_strategy_automation_modeling_playbook.md) — mandatory pre-build design pass (topology + conformed-dim pass + attribute plan + metric plan + relationships + security + publish-readiness + validation). Apply BEFORE `build_mosaic.py build`.

## Mosaic modeling (design-time, payload shapes)
- [build_mosaic.py CLI map](reference_mosaic_build_skill.md) — subcommand index for the build helper; start here when you don't know which subcommand to run.
- [Mosaic preflight check](reference_mosaic_preflight_skill.md) — `skill/scripts/preflight_model_check.py` invoked as step 6 of build-mosaic-model. 6 categories: naming, attr-vs-metric, datatype, joinability, blueprint-fit, governance. ERROR findings stop the build.
- [Mosaic REST API map](reference_mosaic_rest_api.md) — verified endpoint paths (auth, datasources, catalog, data models, changesets, security, translations).
- [Mosaic modeling concepts](reference_mosaic_modeling_concepts.md) — attributes, metrics (compound/conditional/level/transformation), relationships, filters, transformations — payload shapes.
- [Mosaic build config schema](reference_mosaic_config_schema.md) — declarative config fields and post-build derived-metric workflow.
- [Mosaic relationship archetypes](reference_mosaic_relationship_archetypes.md) — 6 canonical patterns (star, snowflake, bridge, composite-FK, descriptive, date-hierarchy) with encoding and failure modes.
- [Business-logic translation](reference_mosaic_business_logic_translation.md) — intent → topology/grain/entities/metrics/aggregation/relationships; Kimball-first; intake ladder, per-column decision matrix, aggregation-function table, inspection-only inference path, red flags.
- [Business-logic pass mandatory](feedback_business_logic_pass_mandatory.md) — never run build without the translation artifact + assumptions log; auto-inference ships semantically wrong models under 2xx status.
- [Mosaic derived metrics](reference_mosaic_derived_metrics.md) — compound/conditional/level metric shapes captured from the UI (ratio, filter-scoped, level).
- [Mosaic AI modeling service](reference_mosaic_ai_service.md) — `/api/aiservice/model/*` — primary keys, linking, lookup table, multi-form attributes, relationships, metrics recommendations.
- [Mosaic batch API](reference_mosaic_batch_api.md) — `POST /api/model/batch` bundles many sub-ops per changeset; `allowPartialSuccess=true` → HTTP 207 with per-op status.
- [Mosaic UI internal endpoints](reference_mosaic_ui_internal_endpoints.md) — workspace/pipeline write surface, changeset rebase, AI service hooks, executive-summary flag. Tenant-internal contracts that shift between versions.
- [Mosaic model linking (data-mesh)](reference_mosaic_model_linking.md) — "Add Models" is a schema import with disambiguation, NOT a stored link; federation is by shared attribute name at query time.
- [Legacy project as Mosaic blueprint](feedback_mosaic_legacy_as_blueprint.md) — mirror the existing semantic model's shape instead of inferring from columns; avoids locale dupes, missing entities, cartesians.

## Mosaic runtime (publish, ACL, security)
- [Mosaic publish routing](reference_mosaic_publish_path.md) — subType 779 → Mosaic 3-step or `/api/cubes/{id}?cubeAction=publish`; ALWAYS poll `publishStatus` or Trino-smoke before declaring success. Do NOT fire both paths concurrently.
- [Mosaic vs Legacy surface delineation](reference_mosaic_vs_legacy_surfaces.md) — subType 779/776 classification; endpoint-pair cheat sheet; asymmetric `/api/model/dataModels` vs `/api/dataModels` paths.
- [Mosaic security filter create + assign](reference_mosaic_security_filter.md) — Modeling-scoped create + top-level `/api/dataModels/.../securityFilters/{sfId}/members` PATCH (the asymmetry is the trap); use `predicate_element_list` (Shape B) for custom-form qualifications.
- [Mosaic ACL read + write](reference_mosaic_acl.md) — Modeling-scoped `PATCH /api/model/dataModels/{mid}/objects/{oid}/acl` + legacy-style `showACL=true` GET.
- [Mosaic build validation](reference_mosaic_build_validation.md) — runnable post-build checklist invoked via `build_mosaic.py validate-model`; F/W checks and diff/regression mode.
- [Rollup-consistency validation](reference_rollup_consistency_validation.md) — Trino query pattern that proves joins + relationships are correct via same-total rollups across every attribute level.
- [Mosaic clone-and-remap pattern](reference_mosaic_clone_pattern.md) — cloning a reference model into a new one: fresh ids with REF dataTypes, text-only `column_reference` tokens, display PATCH post-create, commit order.
- [Strategy object cloning (generalized)](reference_strategy_object_cloning.md) — clone-and-remap across Mosaic, classic, dossier, cube, user object families.

## Mosaic build-quality rules (ship-bar feedback)
- [Consumer-grade naming rules](feedback_consumer_grade_naming.md) — attribute/form/metric naming, descriptions, formatting, no-hardcoded-identities, verify-with-query before ship. Covers `8004cc63` / `8004cd0a` fix-at-create-time rule.
- [Mosaic build quality rules](feedback_mosaic_build_quality.md) — 11 durable rules from a TPC-H side-by-side: form names, auto-hierarchy limits, FK coverage, composites, dates, aggregation, read-back, orphans, descriptions, diff-mode QA.
- [Mosaic forms + metric formats](feedback_mosaic_forms_and_formats.md) — every attribute's report/browse display must be its DESC form; every metric must carry a currency/percent/integer/fixed format. ID-as-display + Generic-number are never shippable.
- [Mosaic gotchas (general)](feedback_mosaic_gotchas.md) — X-MSTR-IdentityToken mandatory for Modeling writes; `type:"pipeline"` requirement; `type:"character"` operator tokens for expressions; base64 catalog IDs; `8004cd15` managed-attribute trap.
- [Mosaic REST payload gotchas](reference_mosaic_rest_gotchas.md) — verified shapes for model/table/attribute/metric POSTs, column-objectId ephemerality, pipeline physical-table shape, EOT token requirement, Trino column naming.
- [Mosaic publishable dataTypes](feedback_mosaic_publishable_datatypes.md) — warehouse-catalog types silently break in-memory publish (iServerCode -2147212544); clone UI-verified types (`utf8_char`, `integer`, `double`, `int64`, `time_stamp`) instead.
- [Multi-DB connect_live forbidden](feedback_mosaic_multi_db_connect_live.md) — Mosaic rejects ≥2 DB instances under connect_live (code 8004d232); use in_memory or split.
- [Mosaic relationship wiring + conformance recipe](feedback_mosaic_relationship_wiring.md) — six-step Kimball conformed-dim recipe: topology classify → attribute plan → dictionary conformance via identical `name` → relationships for non-shared attrs only → post-build expression verify → PATCH-before-PUT → Trino rollup check. Avoids 8004ccdb / 8004ccc7 / 8004e409 / disconnected-star failures on multi-DB builds.
- [iServer session cap + one-process rule](feedback_build_mosaic_session_leak.md) — chaining CLI invocations parks iServer project-interactive sessions that DELETE /api/auth/login does NOT reap; cap is 8004cb0a / iServerCode -2147072486. Preventive rule — one session, one process, one pipeline.
- [Security filter naming](feedback_security_filter_naming.md) — every SF name must describe the qualification (e.g. "Region = EMEA"), not the user/date; keeps the security rule readable when membership rotates.
- [Mosaic description length cap](feedback_mosaic_description_length_cap.md) — data-model description is ~250 char; PATCH fails 8004cc10 above that. Keep short; detail goes in an external README.
- [Mosaic publish endpoint collision](feedback_mosaic_publish_endpoint_collision.md) — never fire `/api/cubes?cubeAction=publish` AND `/api/dataModels/{id}/publish` together; the losing instance's `publishStatus` returns 500 iServerCode -2147072194 for the job's whole lifetime even while the cube finishes in seconds.

## Classic / legacy, AI, runtime, and admin
- [Legacy semantic / admin workflows](reference_strategy_legacy_semantic_admin.md) — classic project semantic layer + admin; distinguishes classic `/api/securityFilters` (+ `/api/securityFilters/{id}/members`) from Mosaic data-model SFs and AI/agent surfaces. Not interchangeable.
- [Legacy-to-Mosaic mining](reference_strategy_legacy_to_mosaic_mining.md) — discover candidate Mosaic tables/objects from legacy reports/documents, or reverse from table dependencies. **Start here for any classic → Mosaic migration**; then decide clone-and-remap vs blueprint-driven build.
- [Classic → Mosaic design transition](reference_strategy_design_transition.md) — conceptual bridge from classic project schema design to modern Mosaic / USL / AI / MCP / governed model automation.
- [Tutorial semantic field study](reference_strategy_tutorial_semantic_field_study.md) — live REST inventory of Tutorial attributes, facts, metrics, filters, prompts, hierarchies, fact extensions, plus Mosaic translation rules.
- [Mosaic field study + legacy bridge](reference_strategy_mosaic_field_study.md) — REST inventory pattern for Mosaic models + object-by-object classic→Mosaic translation matrix. Dated portfolio stats live in `captures/`; rules here are durable.
- [Cube and dataset families](reference_strategy_cubes_and_datasets.md) — Intelligent/OLAP cubes (subType 776), Super Cube/MTDI Push Data datasets, runtime Cube API, Mosaic (subType 779) publish/materialization nuances.
- [Runtime analytics](reference_strategy_runtime_analytics.md) — report/cube/dashboard/document execution via `/instances`; prompt answers, runtime filters, JSON Data API boundary.
- [Report/dossier creation surface](reference_strategy_report_dossier_creation.md) — REST does NOT expose from-scratch creation of reports/dossiers/dashboards on Strategy ONE; only execution against existing templates.
- [Report/dashboard/dossier authoring — from-scratch REST unavailable on Strategy ONE](reference_strategy_report_authoring_patterns.md) — surviving paths: mstrio-py, clone-and-retarget, execute-and-persist.
- [Admin platform workflows](reference_strategy_admin_platform.md) — datasource admin, distribution/subscriptions, migrations/packages, monitors/caches, search/browse, settings, project administration.
- [Subscriptions & schedules (STUB)](reference_strategy_subscriptions_and_schedules.md) — delivery surface (email/file/cache/mobile) + schedules; endpoint families sketched; verified payloads land here as transmitters are exercised.
- [Package & migration lifecycle (STUB)](reference_strategy_package_migration.md) — migrations/packages between projects and tenants; endpoints sketched; no verified write path yet.
- [Monitoring / jobs / caches (STUB)](reference_strategy_monitoring_jobs_alerts.md) — job monitor, cache ops, alerts; Mosaic refresh vs classic cache refresh differ; stub captures families, no wrapped helper yet.
- [AI agents](reference_strategy_ai_agents.md) — Auto Agent (`/api/questions`, `/api/v2/bots`) vs deprecated Bot APIs; chat/question flow, agent config, nuggets/learnings endpoints, AI indexing.

## Validation
- [Strategy model + data validation](reference_strategy_data_validation.md) — 10-check design suite + runnable 5-query paired-query suite; pluggable reference sources (Mosaic, legacy report, flat file, warehouse SQL, REST fixture); tolerance rules; failure triage.
- [Live validation suite](reference_strategy_validation_workflows.md) — non-Mosaic / non-AI validation suite with 10 workflows, runner command, cleanup rules, live-API gotchas.

## Field captures (capture targeting)
- [Chrome MCP capture — arm BEFORE the click](reference_chrome_mcp_capture.md) — `read_network_requests` is opt-in per tab and records only after first invocation; call it to arm the capture, THEN have the user interact.
- [Local skill bundles](reference_local_skill_bundles.md) — `skills/strategy-brand` + `skills/strategy-product-knowledge` — read before brand deliverables or Strategy product content.
