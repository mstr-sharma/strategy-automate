---
name: Strategy automation coverage contract
description: Defines the repo goal of complete Strategy platform automation: generic API reachability for every exposed endpoint, typed helpers for repeatable workflows, and an explicit gap register where APIs are unavailable or tenant-specific.
type: reference
originSessionId: codex-session
---
Use this when auditing whether the repo actually covers the Strategy platform end to end.

## Coverage promise

The goal is complete automation coverage for Strategy where an API, SDK, MCP tool, command-line surface, or reproducible network call exists. Do not imply that every workflow already has a polished helper. Instead, classify each workflow into one of these levels:

**How the repo reaches everything (2026-10-05):** every REST operation in the tenant's spec is callable through `skills/strategy-platform/scripts/strategy_api.py call <operationId>` — validated against the spec (parameters, enums, body), with project / changeset / `Prefer` headers filled in and writes gated behind `--yes`. Each API area has an owning skill (`strategy-admin`, `-distribution`, `-content`, `-migration`, `-ops`, `-ai`, modeling, validation) that records the workflows; `memory/reference_strategy_api_surface.md` is the generated area → skill → coverage table, and `tests/test_rest_contract.py` keeps scripts honest against the spec. The levels below still apply: a validated single call is a *generic REST hook*, not a wrapped workflow.

- **Wrapped helper:** a local command implements a repeatable workflow with validation, dry-run or read-back, and cleanup where needed.
- **Generic REST hook:** the endpoint is reachable and spec-validated through `strategy_api.py describe` / `call` (raw `build_mosaic.py api-call` for multipart), even if no typed subcommand exists yet.
- **Specialized hook:** MCP, Trino, mstrio-py, Workstation CLI, or another official/tenant-supported surface is the safer automation path than raw REST.
- **Captured fallback:** no documented API exists, but a browser/devtools capture can identify a stable request. Record the capture and tenant/version before treating it as reusable.
- **Known gap:** no available automation hook is verified. State the limitation plainly and give the closest reliable workaround.

## Platform families

Track coverage across these families, not just Mosaic:

- Authentication, sessions, projects, folders, search, browse, object metadata, object copy/move/delete, ownership, certification, ACL/object security.
- Classic/project semantic layer: attributes, facts, metrics, filters, prompts, transformations, hierarchies, system hierarchy, cubes, tables, VLDB/applicable properties.
- Mosaic semantic models: data models, tables, attributes, fact metrics, custom metrics, relationships, transformations, security filters, translations, ACLs, publish/materialization.
- Legacy-to-Mosaic migration: classic semantic mining, report/document reverse lineage, blueprint generation, Mosaic build, side-by-side validation.
- Runtime analytics: report/cube/dashboard/dossier/document instances, prompt answers, runtime filters, requested objects, export.
- Cube and dataset families: Intelligent/OLAP cubes, Super Cube / MTDI / Push Data datasets, DDA/MDX runtime cubes, cache/publish/refresh/status.
- Datasource and warehouse administration: datasources, connections, logins, mappings, catalog, OAuth, DSN/driver/DBMS objects.
- Users, groups, security roles, privileges, project membership, addresses, contacts, security-filter assignments.
- Distribution services: subscriptions, schedules/events, transmitters, contacts/contact groups, dynamic recipients, delivery status.
- Monitoring and operations: jobs, caches, project load/unload, cluster/server status, Library status, iServer nodes.
- Migration/package lifecycle: package creation, binary upload/download, validation, import, undo package, migration groups.
- AI/agent surfaces: Auto Agent questions, v2 bot/agent management, chats, training/config, nuggets/learnings, indexing.
- Validation and testing: live workflow probes, paired-query data correctness, rollup consistency, cleanup verification, tenant gotchas.

## Adding coverage

For any new Strategy capability:

1. Search the live spec first: `python3 skills/strategy-platform/scripts/strategy_api.py ops --search "<words>"`, then `describe <operationId>`.
2. If an endpoint exists, prove it with a read-only `api-call` or a dry-run wrapper before adding writes.
3. Add or update the task row in `reference_strategy_task_catalog.md`.
4. Add typed helper code only when the workflow is common, risky, multi-step, or needs payload construction/read-back.
5. Document authentication requirements, changeset requirements, cleanup, and verification in the relevant memory file.
6. If no API exists, add a known-gap note with the tested date, tenant behavior, and best workaround.

## Honesty rules

- Generic REST reachability counts as an API hook, but not as a finished workflow wrapper.
- Do not say a workflow is automated if it cannot be executed, verified, and cleaned up by a repeatable path.
- When OpenAPI, public docs, and tenant behavior disagree, prefer tenant-verified memory, then live OpenAPI, then public docs, then clone-and-remap from a working object.
- Keep legacy/classic, Mosaic, runtime, dataset, and admin surfaces separate even when they share object names.

## Proposed skills — ranked gaps from the 2026-10-05 documentation audit

Compared against the REST spec, the REST docs, product help and mstrio-py master. Each is a candidate `skills/<name>/SKILL.md` (or a section, where noted). Sign-in is no longer a gap: `strategy_auth.py`, `strategy_mcp.py`, `reference_strategy_authentication.md`.

1. **`strategy-mcp-readiness`** — make content appear in the Mosaic MCP server and explain why something is missing: publish + certify (`PUT /api/objects/{id}/certify`), AI-enable classic cubes (`POST /api/cubes/dumpcubes`, status `POST /api/v2/bots/cubes/status`; mstrio `MosaicModel.certify` / `enable_for_ai`), agents active + certified + in the user's Library, privileges ("Use Mosaic MCP Server", or "Use Agent MCP Server" + "Run AI Bots") via `POST /api/privileges/bulkUpdate`, health probes on `{host}/collaboration/mcp/mosaic|agent` (401 = up). Source: product help NextGenAI `agent_MCPServerIntegration.htm`, `agent_MCPServerTroubleshooting.htm`.
2. **`strategy-migration`** — packages (`/api/packages`, `/api/packages/imports` with undo), migrations (`/api/migrations`, `/api/migrationGroups`: validate, import, undo), project duplication (`/api/projectDuplications`), Mosaic `saveAs`, YAML export/restore and Git backup/restore. Source: REST docs `administration/migrations/create-and-import-migration-packages`.
3. **`strategy-distribution`** — subscriptions (CRUD, `/send`, `/status`, bursting, prompts), schedules, events (`/trigger`), transmitters, devices, contacts / contact groups, history list, and scheduled or filtered Mosaic refresh (`contents[].type = data_model`). Source: REST docs `administration/distribution-services/manage-subscriptions`, `mosaic/publish/schedule-refresh-a-data-model`.
4. **`strategy-regression-testing`** — Test Center baseline and comparison tests (`/api/testCenters/integrityTests`, `/integrityComparisons`; mstrio BaselineTest / ComparisonTest) as the official before/after gate for migrations and model changes. Source: product help Workstation `test_center.htm`.
5. **`strategy-identity-admin`** — users, groups, security roles, `privileges/bulkUpdate`, `users/merge`, SCIM 2.0 (`/api/scim/v2/Users|Groups`), multi-tenant administration (irreversible once enabled). Source: product help Workstation `config_lib_server_scim.htm`, `tenant_partitioning.htm`.
6. **`strategy-ops-monitoring`** — v2 job monitor, cube and content caches, project load status, user/DB connections, telemetry usage and query profiles, change journal, fences, license audit.
7. **Mosaic lifecycle section in `build-mosaic-model`** — parameters, smart attributes, custom calendars, model links and external models, OSI (Apache Ossie) import/export, `GET …/hierarchy` snapshots before relationship PUTs, SQL view and Tableau / Power BI data-source exports.
8. **`strategy-content-authoring`** — reports (`POST /api/model/reports` + save/saveAs), dashboards (`POST /api/dossiers/instances` / `draft/instances` → saveAs, dataset rebind), themes, `.mstr` export.
9. **`strategy-server-python`** — `/api/scripts` (run, history, logs, Command Manager → Python), `/api/flows`, `/api/tasks`; mstrio `Script`, `Task`.

Canonical references: REST "what's new" (https://microstrategy.github.io/rest-api-docs/whats-new), Mosaic workflows (https://microstrategy.github.io/rest-api-docs/common-workflows/mosaic/), product What's New (https://www2.strategy.com/producthelp/Current/Readme/en-us/Content/whats_new.htm), mstrio-py NEWS (https://github.com/MicroStrategy/mstrio-py/blob/master/NEWS.md).
