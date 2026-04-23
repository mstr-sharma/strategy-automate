---
name: Mosaic model clone-and-remap pattern (REF-to-new-model)
description: Step-by-step pattern for cloning a working Mosaic data model into a new one with a chosen name and folder. Handles physical-table duplication with clean dataTypes, attribute/metric rebinding via name-based tokens, relationship recreation, and security-filter reapplication. Used on 2026-04-23 to recover from a dirty-typed model that refused to publish.
type: reference
---

## When to use this

- A hand-built Mosaic model fails in-memory publish (stuck on `status=1`, no tables; or `-2147212544` stall) and a UI-built reference model on the same warehouse tables publishes fine. Clone the reference shape into a fresh model instead of patching the broken one in-place.
- A model in another project/tenant has the desired shape and you want to reproduce it locally.
- You're building many near-identical models (one per region, tenant, scenario) from a vetted template.

Do NOT use this when you only need a rename or description tweak — `PATCH /api/model/dataModels/{id}` is simpler.

## Preconditions

- You already authenticated (`X-MSTR-AuthToken`, `X-MSTR-ProjectID`, `X-MSTR-IdentityToken`).
- You know `REF_MID` (source) and the destination `folderId` for the new model.
- You know the target `dataServeMode` (`connect_live` only valid for single-DB; otherwise `in_memory`).
- Destination folder is writeable by you (ACL `R`+`W`, `C`reate object).

## The walk

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
- `8004ccfc` — duplicate model name in folder. Delete the old one via `DELETE /api/objects/{oldMID}?type=3` (the `/api/model/dataModels/{id}` DELETE path does NOT work on studio.strategy.com — uses the generic objects endpoint).

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

Per `reference_mosaic_publish_path.md`: `POST /api/cubes/{MID}?cubeAction=publish` is the reliable trigger on studio.strategy.com (matches the UI). Poll via the Modeling-native 3-step flow if you need per-table confirmation.

## What this pattern does NOT carry over

- **ACL grants/denies** on the model root or child objects. Re-apply after clone via `/api/model/dataModels/{newMID}/objects/{objId}/acl?subType=...`.
- **Translations** on names/descriptions — re-PATCH per object.
- **User-defined hierarchies** — clone separately via `/api/model/dataModels/{newMID}/hierarchies`.
- **Custom groups, consolidations, prompts, transformations** — each has its own `POST` endpoint and needs its own remap pass.
- **Legacy-layer artifacts** (classic reports, project-level filters). The clone is Mosaic-scoped only.
- **Serve-mode specifics**: the new model starts unpublished; you must re-publish after clone.

## Helper integration

`build_mosaic.py` should grow a `clone-model --source REF_MID --name NEW_NAME --dest-folder <id>` subcommand that implements steps 2–8. Today the operator has to do this via an ad-hoc script — which is fine for one-off recovery but tedious when building multiple templated models.
