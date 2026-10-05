---
name: Strategy package & migration lifecycle
subtype: stub
description: Stub reference for the package/migration family — project duplication, object packaging, binary upload, migration validation, import, undo, and rollback. Endpoints sketched; verified payloads added as exercised.
type: reference
---

Part of the automation coverage contract. Treat as **generic REST hook** until a typed wrapper ships.

## Endpoint families (corrected 2026-10-05 against the tenant spec + REST docs "Create / Import a migration package")

The earlier sketch (`POST /api/migrations/{id}/validate|import|undo`, `POST /api/packages/{id}/import`) named paths that do not exist. Long-running calls require the header `Prefer: respond-async` and answer 202.

**Migrations**
- `POST /api/migrations` — create a migration (`importInfo` required; `packageInfo` for a new package, or `?packageId=` to reuse one) → 201.
- `GET /api/migrations`, `GET /api/migrations/{id}` — list / status (`packageInfo.status` creating → created; import and undo request statuses).
- Validate: `PUT /api/migrations/{id}/validation` (`Prefer: respond-async`) → 202 — dry run.
- Import: `PUT /api/migrations/{id}` (`Prefer: respond-async`, `?generateUndo=true`) → 201. Approval flow: `PATCH /api/migrations/{id}` with `importInfo.importRequestStatus` `requested` → `approved`.
- Undo: `PATCH /api/migrations/{id}` with `importInfo.undoRequestStatus` (`requested` → `approved`).
- Binaries: `GET /api/migrations/packages/{packageId}/binary`, undo package `GET /api/migrations/imports/{importId}/binary`. Clean up with `DELETE /api/migrations`. Batches: `/api/migrationGroups`.

**Packages**
- Build: `POST /api/packages` (empty holder → `{id, status}`) → `PUT /api/packages/{id}` (`Prefer: respond-async`; body `{type: project|project_security|configuration, settings, content[]}`) → poll `GET /api/packages/{id}` until `ready` → download `GET /api/packages/{id}/binary`. A project or project-security package needs `X-MSTR-ProjectID`; a configuration package must not send it.
- Import: `POST /api/packages` holder → `PUT /api/packages/{id}/binary` (upload) → `POST /api/packages/imports?packageId=<id>&generateUndo=true` (`Prefer: respond-async`) → 202 → poll `GET /api/packages/imports/{importId}` → optional undo package `GET …/imports/{importId}/undoPackage/binary` → close with `DELETE /api/packages/imports/{importId}` (`Prefer` required).
- Delete: `DELETE /api/packages/{id}` **requires `Prefer: respond-async` and answers 202** (status `deleting`), not 204. Always delete the holder: the docs allow one package instance per user session, and an undeleted holder lives as long as the session.
- The upload is `multipart/form-data`.

## Critical gotchas to capture

- Which object types are migration-safe across Mosaic vs classic project boundaries (e.g., can you migrate a Mosaic model — subtype 779 + extType 448 — between projects? What re-binds?).
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
