---
name: Strategy automation coverage contract
description: Defines the repo goal of complete Strategy platform automation: generic API reachability for every exposed endpoint, typed helpers for repeatable workflows, and an explicit gap register where APIs are unavailable or tenant-specific.
type: reference
originSessionId: codex-session
---
Use this when auditing whether the repo actually covers the Strategy platform end to end.

## Coverage promise

The goal is complete automation coverage for Strategy where an API, SDK, MCP tool, command-line surface, or reproducible network call exists. Do not imply that every workflow already has a polished helper. Instead, classify each workflow into one of these levels:

- **Wrapped helper:** a local command implements a repeatable workflow with validation, dry-run or read-back, and cleanup where needed.
- **Generic REST hook:** the endpoint is reachable through `build_mosaic.py openapi-search` plus `build_mosaic.py api-call`, even if no typed subcommand exists yet.
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

1. Search the live spec first: `python3 skills/build-mosaic-model/scripts/build_mosaic.py openapi-search "<domain word>" --context 3`.
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
