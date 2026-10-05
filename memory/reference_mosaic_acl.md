---
name: Mosaic data-model ACL (object security) — read + write
description: The Modeling Service DOES expose object-level ACLs on Mosaic data models and every contained object (attributes, metrics, fact metrics, tables, filters). This was an open question in prior memory. Both read paths and write path are verified against the UI's Object-Level Security pane.
type: reference
---

Yes, Mosaic ACL APIs are exposed. Verified by capturing the "Security and Translation → Object-Level Security" UI pane's effect on a real model.

## Read — two equivalent paths

Both return the same underlying ACL but shaped differently:

### Legacy-style (objects API)

```
GET /api/objects/{objectId}?type={objectType}&showACL=true
```

- `type` is the numeric object type (4 for metric, 12 for attribute, 776 for logical_table, 779 for data model, etc.)
- Returns `acl[]` as a list of entries with numeric rights mask:
  ```json
  [
    {
      "deny": false,
      "type": 1,
      "rights": 255,
      "trusteeId": "EXAMPLEUSERIDPLACEHOLDER00000001",
      "trusteeName": "<user-a-fullname>",
      "trusteeType": 34,
      "trusteeSubtype": 8704,
      "inheritable": false
    },
    ...
  ]
  ```
- Entries carry `deny:true|false` (two entries per trustee if both granted and denied rights exist).
- `trusteeSubtype 8704` = user, `8705` = user_group.

### Modeling-scoped (the one our helpers should use)

```
GET /api/model/dataModels/{modelId}/objects/{objectId}/acl?subType={objectSubType}
```

- `subType` string values verified: `metric`, `fact_metric`, `attribute`, `logical_table` (contained tables), `report_emma_cube` (model root — see below). Wrong subType on GET does NOT error — the server silently returns a consistent ACL, so always pass the correct one or you'll end up patching the wrong facet.
- Returns ACL keyed by trusteeId:
  ```json
  {
    "acl": {
      "EXAMPLEUSERIDPLACEHOLDER00000001": {
        "name": "<user-a-fullname>",
        "subType": "user",
        "granted": 255,
        "denied": 0,
        "inheritable": false
      },
      "EXAMPLEUSERIDPLACEHOLDER00000002": {
        "name": "<user-b-fullname>",
        "subType": "user",
        "granted": 0,
        "denied": 255,
        "inheritable": false
      }
    }
  }
  ```
- This shape is what `PATCH ...objects/{objectId}/acl` accepts (see Write below). Each trustee has independent `granted` and `denied` masks that can both be nonzero.

Alternative path `/api/dataModels/{id}/objects/{oid}/acl` (no `/model/` prefix) returns **404** — asymmetry with security-filter members endpoint, which uses the non-`model/` prefix. Do not guess based on the security-filter pattern; ACL uses the `/model/` prefix.

## Write — Modeling-scoped PATCH

```
PATCH /api/model/dataModels/{modelId}/objects/{objectId}/acl?subType={objectSubType}
Headers: X-MSTR-MS-Changeset: {cs}
```

Body (verified shape, mirrors the read response):

```json
{
  "acl": {
    "<trusteeId>": {
      "granted": 255,
      "denied": 0,
      "subType": "user",
      "inheritable": false
    },
    "<trusteeId2>": {
      "granted": 0,
      "denied": 255,
      "subType": "user",
      "inheritable": false
    }
  }
}
```

- Wholesale replacement of the ACL (similar semantics to the relationships PUT — any trustee omitted from the body is removed). `build_mosaic.py` merges with the current ACL first.
- Must be wrapped in a changeset (same as attribute/metric edits).
- `subType` must match the target object's subtype — `metric`, `fact_metric`, `attribute`, `logical_table` for a contained table, `report_emma_cube` for the model root.

## Rights mask values (EnumDSSXMLAccessRightFlags)

The `granted` / `denied` masks are bit vectors of EnumDSSXMLAccessRightFlags — the same order as the spec's `ms-EnumAccessRight` string enum:

| Bit | Right |
|---|---|
| 1 | browse |
| 2 | use_execute |
| 4 | read |
| 8 | write |
| 16 | delete |
| 32 | control |
| 64 | use |
| 128 | execute |

They sum to **255 = Full Control**. (An earlier version of this note and of `build_mosaic.py`'s `_RIGHT_FLAGS` used read 1, write 2, delete 4, browse 64, use 512, inherit 1024 — wrong: `--grant x:read` set only Browse and `--deny g:write` denied Use&Execute while leaving Write allowed. Fixed 2026-10-05.) Inheritance is the separate `inheritable` boolean on each entry, not a bit.

| UI role in the Object-Level Security pane | `granted` | `denied` |
|---|---|---|
| Full Control | 255 | 0 |
| Can Modify (browse, read, write, delete, use, execute) | 221 | 0 |
| Can View (browse, read, use, execute) | 197 | 0 |
| Denied All | 0 | 255 |

`build_mosaic.py --grant/--deny` and `set-acl` accept these names (`view`, `modify`, `full`, or individual rights) or a number, and refuse unknown names. The modify/view masks follow the standard Strategy bundles; capture one from the UI if a tenant's roles differ.

**Write semantics:** the PATCH body is the whole ACL — trustees left out are removed. The helper therefore reads the current ACL (`GET` on the same path) and changes only the trustees named on the command line before it PATCHes.

## Model-root ACL (the model object itself)

Model-level ACL uses the same pattern with `objectId = modelId` and **`subType = report_emma_cube`** — the subtype the model carries in its `information` (same value `POST /api/model/dataModels` requires). Corrected 2026-10-05 from a teammate's live write test:

- `PATCH .../objects/{modelId}/acl?subType=report_emma_cube` — works.
- `PATCH .../objects/{modelId}/acl?subType=logical_table` — fails with **`8004e403`**. (An earlier version of this note said the root accepts `logical_table`; it doesn't.)
- Classic write `POST /api/objects/{modelId}/acl` — **404** for a Mosaic model. There is no legacy write fallback for the root; use the Modeling PATCH.

Legacy path `GET /api/objects/{modelId}?type=3&showACL=true` still works for **reading** the model-root ACL.

`build_mosaic.py` (`build --grant/--deny` and `set-acl`) defaults to `subType=report_emma_cube` for the root (was the unverified `data_model` before 2026-10-05). For a contained object, pass `set-acl --sub-type attribute|metric|fact_metric|logical_table`.

## Gotchas

- `GET /api/objects/{id}?showACL=true` (without `type`) returns **400** — type parameter is required.
- `GET /api/model/dataModels/{mid}/objects/{mid}/acl` (without `subType`) returns **500**.
- The Modeling ACL endpoints return 200 with structurally correct but potentially wrong-object ACL if `subType` mismatches the real subtype. Always verify `subType` before write.
