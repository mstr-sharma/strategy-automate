---
name: Strategy package & migration lifecycle
subtype: stub
description: Stub reference for the package/migration family — project duplication, object packaging, binary upload, migration validation, import, undo, and rollback. Endpoints sketched; verified payloads added as exercised.
type: reference
---

Part of the automation coverage contract. Treat as **generic REST hook** until a typed wrapper ships.

## Endpoint families

- `POST /api/migrations` — create a migration (source project, target project, object list).
- `GET /api/migrations/{id}` — status, per-object success/failure.
- `POST /api/migrations/{id}/validate` — dry-run validation.
- `POST /api/migrations/{id}/import` — apply (after validate).
- `POST /api/migrations/{id}/undo` — rollback to pre-import state (where supported).
- `POST /api/packages` — build a package (binary) for download/archive.
- `GET /api/packages/{id}/binary` — fetch package file.
- `POST /api/packages/{id}/import?projectId=...` — import into a target.

## Critical gotchas to capture

- Which object types are migration-safe across Mosaic vs classic project boundaries (e.g., can you migrate a 779 Mosaic model between projects? What re-binds?).
- Security filters and user/group targeting — how membership is resolved across environments.
- Dependency expansion — migrations can silently pull in parent objects (schemas, tables). Capture the "preview dependencies" shape before committing.

## Routing rules

- **Duplicate a project's Mosaic models to another project on same tenant** → packages or migrations, not `/api/objects/{id}/copy` (which is folder-scoped, not project-scoped).
- **Promote dev → staging → prod** → migrations with validate step; never skip validate.
- **Backup before schema risky changes** → package export.

## Pending: verified payloads

Exercise and document when first used:
- Mosaic data model migration between Shared Studio projects.
- Classic project semantic-layer migration with security-filter preservation.
- Package export of a single dossier + dependencies.
