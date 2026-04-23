---
name: Cloning Strategy objects — Mosaic, classic, runtime
description: The clone-and-remap pattern generalized across Strategy object families. Pairs with `reference_mosaic_clone_pattern.md` (Mosaic-specific) and documents the same approach for classic objects, dossiers, reports, cubes, and security filters. Key rule: strip identifying metadata, mint fresh IDs, remap inter-object references, re-apply owner/ACL/translations in follow-up calls.
type: reference
---

## Why clone instead of author

- **Unknown payload shape.** Many Mosaic/classic object bodies aren't documented at the granularity you need; a `GET` of a working instance is the canonical sample.
- **Template propagation.** "Make me N tenants worth of this dashboard" is faster as N clones than N from-scratch builds.
- **Recovery from corrupted state.** When a model won't publish or a dossier won't render, cloning a sibling model/dossier and re-applying your deltas usually beats debugging the broken one.

## The universal walk

1. **Identify source + destination.** Source is a working, committed object. Destination can be a new folder in the same project, a different project (via migration), or a different tenant (via package export + import).
2. **GET the full definition** including any tokenized expressions (`?showExpressionAs=tokens`) and child objects (`?showColumns=true`, `?showACL=true`, `?showFilterTokens=true` — per object family).
3. **Persist locally** as `ref_full.json` or similar. Iterate on the clone spec without re-hitting the server.
4. **Rewrite**:
   - Strip identifiers: `information.objectId`, `information.dateCreated`, `information.dateModified`, `information.versionId`, any `expressionId`, `pipeline.id`, `rootTable.id`, `children[*].id`, `columns[*].id`.
   - Mint fresh UUIDs (32-char hex, uppercase on Strategy).
   - Change `information.name` (required if destination folder already contains the source).
   - Remap **internal references**: every `objectId` that pointed at a cloned sibling must point at the clone's new id. Maintain a `{old_id → new_id}` dict built as you POST dependencies.
   - Drop display/ACL/translation blocks and re-apply post-create — some object types require these as separate PATCH calls after initial POST.
5. **POST in dependency order**: tables before attributes, attributes before metrics, metrics before compound metrics, base objects before security filters/relationships/ACLs.
6. **Post-create follow-ups**: displays PATCH (Mosaic attributes must have `displays.reportDisplays` or commit fails); relationship PUTs in a second changeset; security-filter members in a third; ACL + translations if needed.
7. **Smoke test**: `GET` one of the cloned objects and confirm its internal references resolve.

## Per-family notes

### Mosaic data model (subType 779)

See `reference_mosaic_clone_pattern.md` for the full working script pattern. Highlights:
- Physical-table dataTypes must match the UI-built reference shape, not the warehouse-catalog shape. See `feedback_mosaic_publishable_datatypes.md`.
- Attribute/metric expressions: use text-only `column_reference` tokens (`{"type":"column_reference","value":"COL_NAME"}` — no `target.objectId`) to let the server re-bind by name on commit.
- Tables need at least one attribute or metric per table BEFORE commit, else `8004e42f`.
- Attributes need `displays.reportDisplays` PATCHed before commit, else `8004cf06`.
- Deletes via `DELETE /api/objects/{id}?type=3` (NOT `/api/model/dataModels/{id}`, which 404s on the Strategy ONE Cloud tenant family observed; recheck on other iServer builds).

### Classic schema objects (attributes, facts, metrics, filters in a project)

- `POST /api/objects/{id}/copy?destinationFolderId=...` works for most classic schema objects with dependencies auto-copied.
- Cross-project: use migrations (see `reference_strategy_package_migration.md`).
- Security filter clone must handle Mosaic-vs-classic endpoint asymmetry — classic uses `/api/model/securityFilters`, Mosaic uses `/api/model/dataModels/{id}/securityFilters` — **not a drop-in copy**. See `reference_mosaic_security_filter.md`.

### Dossier / dashboard / document (type 58 / 55)

- `POST /api/objects/{sourceId}/copy` is the primary path.
- Visualization definitions rebind to the same data-model IDs by default. To retarget, PATCH the dossier's dataset references after copy.
- Prompt definitions clone intact; prompt *answers* (saved defaults) may or may not — verify on first use.

### Intelligent cube (type 74, subType 776)

- `POST /api/cubes` with a full definition body, OR clone via `/api/objects/{id}/copy?type=74`.
- Post-clone, refresh via `/api/cubes/{id}/refresh?refreshType=replace`.
- Do NOT confuse with Mosaic cube materialization — see `reference_mosaic_vs_legacy_surfaces.md`.

### User / user group (type 34 / 42)

- `POST /api/users` or mstrio-py. Privileges and security role memberships are separate follow-up PATCH calls.
- ACL on objects owned by a source user doesn't transfer to the new user automatically.

## What does NOT clone cleanly

- Usage statistics (dashboards showing "viewed by X users in last 30 days" — resets to 0).
- Audit history / certifications — re-apply if needed.
- Subscriptions owned by a specific user — re-create with new user ids.
- Tenant-specific IDs: any `databaseInstance.objectId`, `project.objectId`, user/group ids — remap to the destination tenant's equivalents.

## When to prefer migrate vs clone vs copy

| Intent | Use |
|---|---|
| Same project, different folder | `/api/objects/{id}/copy?destinationFolderId=...` |
| Same tenant, different project | Migration (`reference_strategy_package_migration.md`) |
| Different tenant | Package export + import |
| Need to change the definition as part of the copy | Custom clone-and-remap (this memory's walk) |
| Rebuilding a corrupted Mosaic model | Custom clone-and-remap (scrub dataTypes, mint new IDs; do NOT use `/copy` — it would carry the corruption) |
