---
name: strategy-automation
description: Automate Strategy (formerly MicroStrategy) environments from natural-language requests. Use for any Strategy REST, Mosaic semantic model, datasource/catalog, project/folder/object, report/dashboard/document, cube/cache, security/governance, user/group, subscription, migration, monitoring, or mstrio-py task. Routes NLQ work to the local Strategy memory, OpenAPI spec, authenticated REST helper, Mosaic builder skill, MCP query tools, or mstrio-py as appropriate.
---

# Strategy Automation

Use this skill when the user asks to automate, inspect, build, modify, secure, publish, query, migrate, monitor, or administer anything in Strategy / MicroStrategy.

## First Move

1. Read `/Users/<operator-user>/Desktop/Mosaic Build/memory/MEMORY.md`.
2. Identify the task family in `/Users/<operator-user>/Desktop/Mosaic Build/memory/reference_strategy_automation_playbook.md`.
3. Use live `{Library}/api/openapi.yaml` through the helper when endpoint details matter. A local `openapi.yaml` may be generated for temporary caching, but it is not part of the lean repo.
4. Use credentials from environment (`MSTR_PASSWORD`) or user-provided secure runtime values. Never write secrets to memory, skills, config, or logs.

## Tool Router

- **Build or modify a Mosaic model from warehouse tables:** use `$build-mosaic-model` and its helper script.
- **Drop-in ERDs, dictionaries, rosters, or legacy update briefs:** read `reference_strategy_intake_patterns.md`, normalize files to supported JSON/YAML/CSV/DBML/Mermaid/SQL formats, then resolve IDs before writing.
- **Any REST endpoint not wrapped yet:** use:
  ```bash
  cd "/Users/<operator-user>/Desktop/Mosaic Build"
  python3 skill/scripts/build_mosaic.py openapi-search "<term>" --context 2
  python3 skill/scripts/build_mosaic.py api-call --method GET --path /api/projects
  ```
- **Users and access targets:** use `resolve-users` before ACL/security/user writes; use `create-users` for roster dry-runs and `--yes` only when the user clearly wants creation.
- **Existing or legacy schema objects:** use `search-objects`, then `get-model-object --show-expression-as tokens|tree`, then `patch-model-object --before-out ... --yes` after reviewing the payload.
- **Published-model semantic inspection/query:** use the Mosaic MCP tools when available (`get_projects`, `get_mosaic_models`, `get_semantics`, `query`), or Trino notes in memory.
- **Admin/read workflows with stable wrappers:** mstrio-py is acceptable for users/groups, security roles, schedules/subscriptions, caches, object search, and settings. Capture the equivalent REST path if it becomes a reusable workflow.
- **Unknown modeling payload:** `GET` a working object, clone/remap IDs, then `POST`/`PATCH` through Modeling Service.

## Operating Rules

- Prefer tenant-verified gotchas over public docs when they conflict.
- For destructive operations, enumerate the target object IDs and ask once if the user did not explicitly request deletion/removal.
- Use changesets for Modeling Service writes, commit only after all referenced objects exist, and discard failed changesets.
- For schema/model writes, print or return the object URL, object IDs, and any skipped/failed operations.
- Keep durable lessons in `/Users/<operator-user>/Desktop/Mosaic Build/memory/feedback_mosaic_gotchas.md` or a specific reference file.

## Memory Map

- Environment and credentials: `reference_strategy_env.md`
- Raw REST spec usage: `reference_strategy_openapi.md`
- Broad task routing: `reference_strategy_automation_playbook.md`
- Task-to-endpoint catalog: `reference_strategy_task_catalog.md`
- Drop-in ERD/dictionary/user-list/legacy-update intake: `reference_strategy_intake_patterns.md`
- Mosaic modeling payloads: `reference_mosaic_modeling_concepts.md`
- Mosaic build CLI: `reference_build_mosaic_skill.md`
- mstrio-py role: `reference_mstrio_py.md`
