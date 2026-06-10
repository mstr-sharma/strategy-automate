---
name: strategy-object-cloning
description: Clone-and-remap across all Strategy object families — universal walk (strip IDs, mint fresh, remap references, re-apply ACL/displays/translations), per-family table (Mosaic, classic, dossier, cube, user), and the full Mosaic model clone deep dive (table/attribute/metric rewrite, commit failure modes, relationship + SF + publish follow-ups). Load for any clone, template-propagation, or corrupted-object recovery task.
type: reference
---

## Why clone instead of author

- **Unknown payload shape.** Many Mosaic/classic object bodies aren't documented at the granularity you need; a `GET` of a working instance is the canonical sample.
- **Template propagation.** "Make me N tenants worth of this dashboard" is faster as N clones than N from-scratch builds. Same for many near-identical models (one per region, tenant, scenario) from a vetted template.
- **Recovery from corrupted state.** When a model won't publish or a dossier won't render, cloning a sibling and re-applying your deltas usually beats debugging the broken one. Concrete Mosaic trigger: a hand-built model fails in-memory publish (stuck on `status=1`, no tables; or `-2147212544` stall) while a UI-built reference model on the same warehouse tables publishes fine — clone the reference shape into a fresh model instead of patching the broken one in-place. (Used in anger on 2026-04-23 — see `captures/2026-04-23-studio-publish-stall/README.md` for the incident narrative.)
- **Cross-project/tenant reproduction.** A model in another project/tenant has the desired shape and you want it locally.

Do NOT clone when you only need a rename or description tweak — `PATCH /api/model/dataModels/{id}` is simpler.

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

See the **Mosaic deep dive** below for the full working script pattern. Highlights:
- Physical-table dataTypes must match the UI-built reference shape, not the warehouse-catalog shape. See `reference_mosaic_publish_path.md` ("DataType preconditions").
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

## What does NOT clone cleanly (any family)

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

---

## Mosaic deep dive: clone-and-remap a data model (REF-to-new-model)

Step-by-step pattern for cloning a working Mosaic data model into a new one with a chosen name and folder. Handles physical-table duplication with clean dataTypes, attribute/metric rebinding via name-based tokens, relationship recreation, and security-filter reapplication.

### Preconditions

- You already authenticated (`X-MSTR-AuthToken`, `X-MSTR-ProjectID`, `X-MSTR-IdentityToken`).
- You know `REF_MID` (source) and the destination `folderId` for the new model.
- You know the target `dataServeMode` (`connect_live` only valid for single-DB; otherwise `in_memory`).
- Destination folder is writeable by you (ACL `R`+`W`, `C`reate object).

### 1. Dump the reference

```python
# Full model body (serve mode, schemaFolderId, destination)
GET /api/model/dataModels/{REF_MID}?showExpressionAs=tokens

# List of tables, then individual tables with columns + pipeline
GET /api/model/dataModels/{REF_MID}/tables
for tid in tables:
    GET /api/model/dataModels/{REF_MID}/tables/{tid}?showColumns=true&showExpressionAs=tokens

# Attributes — list then detailed
GET /api/model/dataModels/{REF_MID}/attributes
for aid in attrs:
    GET /api/model/dataModels/{REF_MID}/attributes/{aid}?showExpressionAs=tokens

# Fact metrics
GET /api/model/dataModels/{REF_MID}/factMetrics
for mid in mets:
    GET /api/model/dataModels/{REF_MID}/factMetrics/{mid}?showExpressionAs=tokens
```

Persist the bundle (`ref_full.json`) — you'll iterate on the clone locally without re-hitting the server.

### 2. Create the target model

```
POST /api/model/changesets     body={}
POST /api/model/dataModels headers=X-MSTR-MS-Changeset
body={
  "information":{"name": NEW_NAME, "destinationFolderId": FOLDER},
  "dataServeMode":"in_memory"
}
```
Save `MID = response.information.objectId`. Keep the same changeset open.

### 3. Clone tables with fresh ids but REF dataTypes

For each REF table:
- Drop `attributes`, `factMetrics`, `refreshPolicy` from the body (those live elsewhere).
- Replace `information` with just `{"name": <table_name>}`.
- `physicalTable.columns[*].information.objectId` → mint fresh UUID (hex, 32 chars). Keep `name`, `dataType`, `columnName` unchanged.
- `physicalTable.pipeline` is a JSON STRING. Parse it, recursively replace every top-level `id` (root, children, columns) with fresh UUIDs, re-serialize, and re-attach. Critically, after minting new pipeline column ids, ALIGN them with `physicalTable.columns[*].information.objectId` by column NAME (so a given column has the same id on both sides).
- POST `/api/model/dataModels/{MID}/tables` with `X-MSTR-MS-Changeset`.
- Remember old→new table id mapping.

### 4. Clone attributes (text-only `column_reference` tokens)

Token-level column_reference requires the column's `target.objectId`, and those ids are ephemeral until commit — referencing them in the same changeset fails with `Object with ID ... and type 26 (Column) is not found in metadata`. Work around by dropping `target` and using name-only tokens:

```python
for form in body.forms:
    # Preserve the system ID form's platform id so key form stays recognized
    if form.type == "system" and form.category == "ID":
        pass  # keep form.id = "45C11FA478E745FEA08D781CEA190FE5"
    else:
        del form.id  # let server mint
    for e in form.expressions:
        del e.expressionId
        col_name = <col name extracted from REF token or expression.text>
        e.expression.tokens = [{"type":"column_reference", "value": col_name}]
        del e.expression.text                       # server regenerates
        for t in e.tables:
            t.objectId = tbl_map[t.objectId]        # remap to new table
            keep only {objectId, subType, name}
    form.lookupTable.objectId = tbl_map[...]
body.attributeLookupTable.objectId = tbl_map[...]
del body.relationships
del body.childAttributes
del body.displays                                   # PATCH after POST
```

POST, capture the new attribute id, then PATCH displays so the attribute passes commit validation (`8004cf06: attribute ... has no report display`):

```
PATCH /api/model/dataModels/{MID}/attributes/{newAid}?changeset=...
body={"displays":{
   "reportDisplays":[{"id": f.id} for f in response.forms if f.id],
   "browseDisplays": [...]
}}
```

### 5. Clone fact metrics

Similar to attributes:
- Rewrite `fact.expressions[*].expression` to text-only column_reference by name.
- Remap `fact.expressions[*].tables[*].objectId`.
- Drop `fact.entryLevel` and `fact.extensions` unless you know what they pointed at.
- Keep `function`, `functionProperties`, `dimty`, `format` unchanged.
- POST `/api/model/dataModels/{MID}/factMetrics`.

### 6. Commit #1

`POST /api/model/changesets/{cs}/commit` — should return 201 with `status:"Ready"`. Failure modes you may hit:
- `8004e42f` — a table has no attribute/metric. You skipped or failed a metric/attr for that table.
- `8004cf06` — an attribute has no report display. Step 4's PATCH was missed.
- `8004ccfc` — duplicate model name in folder. Delete the old one via `DELETE /api/objects/{oldMID}?type=3` (the `/api/model/dataModels/{id}` DELETE path does NOT work on the observed Strategy ONE Cloud tenant family — uses the generic objects endpoint; verify on other iServer builds before relying on one or the other).

### 7. Relationships (new changeset)

```python
open new changeset
for oaid, naid in attr_map.items():
    for rel in ref_attrs[oaid].relationships or []:
        if any endpoint id missing from attr_map/tbl_map: skip
        PUT /api/model/dataModels/{MID}/attributes/{naid}/relationships
        body={"relationships":[{
            "parent":{"objectId": attr_map[rel.parent.objectId], "subType":"attribute", "name": ...},
            "child": {"objectId": attr_map[rel.child.objectId],  "subType":"attribute", "name": ...},
            "relationshipType": rel.relationshipType,
            "relationshipTable": {"objectId": tbl_map[rel.relationshipTable.objectId], "subType":"logical_table", "name": ...}
        }]}
commit
```

### 8. Security filters (new changeset)

Follow `reference_mosaic_security_filter.md` — create via Modeling-Service path, then assign members via the sibling `/api/dataModels/{MID}/securityFilters/{sfId}/members` PATCH (note the asymmetric URL).

### 9. Publish

Per `reference_mosaic_publish_path.md`: `POST /api/cubes/{MID}?cubeAction=publish` is the reliable trigger on Strategy ONE Cloud tenants (matches the UI). Poll via the Modeling-native 3-step flow if you need per-table confirmation.

### What the Mosaic pattern does NOT carry over

- **ACL grants/denies** on the model root or child objects. Re-apply after clone via `/api/model/dataModels/{newMID}/objects/{objId}/acl?subType=...`.
- **Translations** on names/descriptions — re-PATCH per object.
- **User-defined hierarchies** — clone separately via `/api/model/dataModels/{newMID}/hierarchies`.
- **Custom groups, consolidations, prompts, transformations** — each has its own `POST` endpoint and needs its own remap pass.
- **Legacy-layer artifacts** (classic reports, project-level filters). The clone is Mosaic-scoped only.
- **Serve-mode specifics**: the new model starts unpublished; you must re-publish after clone.

### Helper integration

`build_mosaic.py` should grow a `clone-model --source REF_MID --name NEW_NAME --dest-folder <id>` subcommand that implements steps 2–8. Today the operator has to do this via an ad-hoc script — which is fine for one-off recovery but tedious when building multiple templated models.
