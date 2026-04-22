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
      "trusteeName": "Smith, Alex",
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

- `subType` string values verified: `metric`, `fact_metric`, `attribute`, `logical_table`. Wrong subType does NOT error — the server silently returns a consistent ACL, so always pass the correct one or you'll end up patching the wrong facet.
- Returns ACL keyed by trusteeId:
  ```json
  {
    "acl": {
      "EXAMPLEUSERIDPLACEHOLDER00000001": {
        "name": "Smith, Alex",
        "subType": "user",
        "granted": 255,
        "denied": 0,
        "inheritable": false
      },
      "EXAMPLEUSERIDPLACEHOLDER00000002": {
        "name": "Jones, Pat",
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

- Wholesale replacement of the ACL (similar semantics to the relationships PUT — any trustee omitted from the body is removed).
- Must be wrapped in a changeset (same as attribute/metric edits).
- `subType` must match the target object's subtype — `metric`, `fact_metric`, `attribute`, `logical_table`, etc.

## Rights mask values observed

| Mask | UI meaning | Notes |
|---|---|---|
| `255` | Full Control | Observed when "Full Control" chip is assigned OR when "Denied All" is assigned (as `denied: 255`). |
| `0` | None | No rights at this level. Use `denied: 255` to deny all, not `granted: 0`. |

The flag decomposition from prior memory `{read:1, write:2, delete:4, control:32, browse:64, execute:128, use:512, inherit:1024}` sums to 1799, not 255. So 255 in Strategy's ACL world is a shorthand for "Full Control" that may not decompose to the named flag set. Treat 255 as a magic "all rights" constant; don't compute it from the flag names.

## UI → trustee → REST mapping

| UI role in the Object-Level Security pane | `granted` mask | `denied` mask |
|---|---|---|
| Full Control | 255 | 0 |
| Can Modify | (pending capture — TBD) | 0 |
| Can View | (pending capture — TBD) | 0 |
| Denied All | 0 | 255 |

`Can Modify` and `Can View` masks need a separate UI capture to pin down. Until then, rely on the legacy Desktop documentation or probe by creating each role and reading back.

## Model-root ACL (the model object itself)

Model-level ACL uses the same pattern with `objectId = modelId` and `subType = logical_table` (Mosaic data models carry subtype `report_emma_cube` in their `information` but the ACL endpoint accepts `logical_table` for the root). Verify per tenant — the spec wording differs by version.

Legacy path `GET /api/objects/{modelId}?type=3&showACL=true` also works for the model root.

## Gotchas

- `GET /api/objects/{id}?showACL=true` (without `type`) returns **400** — type parameter is required.
- `GET /api/model/dataModels/{mid}/objects/{mid}/acl` (without `subType`) returns **500**.
- The Modeling ACL endpoints return 200 with structurally correct but potentially wrong-object ACL if `subType` mismatches the real subtype. Always verify `subType` before write.
