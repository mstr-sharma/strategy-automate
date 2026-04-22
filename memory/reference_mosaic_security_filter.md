---
name: Mosaic data-model security filter — create + assign members
description: Verified REST payloads for creating a Mosaic (data-model-scoped) security filter and assigning users/groups. Every payload field that tripped the API is documented with the exact rejection and fix.
type: reference
---

## Scope distinction
- **Mosaic data-model security filter** → owned by the Mosaic model; endpoints under `/api/model/dataModels/{modelId}/securityFilters` (create) and `/api/dataModels/{modelId}/securityFilters/{sfId}/members` (assign).
- **Project (classic) security filter** → owned at project level; different endpoints. Do not mix.

This doc covers the Mosaic variant. If a request says "security filter" but does not name a Mosaic data model / dataModelId, route to `reference_strategy_legacy_semantic_admin.md` and use the classic project security-filter endpoints instead.

## Step 1 — create the filter

```
POST /api/model/dataModels/{modelId}/securityFilters
Headers: X-MSTR-MS-Changeset: <cs>
```

Body (verified for a Category ID = 1 filter on Products Hierarchy):

```json
{
  "information": {"name": "Books Only", "subType": "md_security_filter"},
  "qualification": {
    "tree": {
      "type": "predicate_form_qualification",
      "predicateTree": {
        "function": "equals",
        "attribute": {"objectId": "<attribute id>", "subType": "attribute"},
        "form": {"objectId": "<form id>", "subType": "attribute_form_system"},
        "parameters": [{"parameterType": "constant", "constant": {"type": "int32", "value": "1"}}]
      }
    }
  },
  "topLevel": [], "bottomLevel": []
}
```

Gotchas observed:
- **Do not create a placeholder `predicate_false` filter from free text.** That is a deny-all filter, not a parsed qualification. For automation, require a structured qualification JSON or a constrained form-qualification shorthand such as `ATTR_ID[:FORM_ID]=VALUE`.
- **`information.subType` must be `md_security_filter`**, not `security_filter`. Wrong subType → 400.
- **`form.subType` must be `attribute_form_system`** (for the ID system form with objectId `45C11FA478E745FEA08D781CEA190FE5`). Omitting subType or using `attribute_form` → `400: The object of subtype 'null' for object '...' is not supported.`
- Commit the changeset after creation. Member assignment happens in a separate REST call (no changeset header), so commit is required for the SF to be visible to the members endpoint.

## Step 2 — assign members (users / groups)

```
PATCH /api/dataModels/{modelId}/securityFilters/{sfId}/members
Content-Type: application/json
```

Body:

```json
{
  "operationList": [
    { "op": "addElements", "path": "/Members", "value": ["<userId>", "<userId2>"] }
  ]
}
```

Gotchas:
- **Path prefix is `/api/dataModels/...`, NOT `/api/model/dataModels/...`.** The Modeling-scoped path (`/api/model/dataModels/{id}/securityFilters/{sfId}/members`) returns 404. This asymmetry is the trap — creation uses Modeling Service, member assignment uses a sibling top-level path.
- **`op` must be `addElements`** (one word, camelCase). `add` is rejected with `Patch op 'add' cannot be applied to path 'Members'`. Use `removeElements` / `replaceElements` for the mirror operations.
- **`path` must be `/Members`** with a **leading slash and capital M**. Lowercase `members`, `/members`, and `Members` (no slash) all fail `Invalid path, the path should a string matching regex '/([/A-Za-z0-9...`. The regex forces the leading slash and PascalCase segment.
- Success returns **HTTP 204** with an empty body.
- Only accepts user/group IDs — resolving names requires a separate `/api/users?nameBegins=<q>` pass first.

## User discovery that actually works

`/api/users?searchTerm=<q>` returned 0 results on Strategy ONE even for known users. Use the `Begins` variants:

```
GET /api/users?nameBegins=O&limit=100
GET /api/users?abbreviationBegins=t&limit=100
```

- `nameBegins` matches the `fullName` field (e.g., `"Smith, Alex"` matches the leading `S`).
- `abbreviationBegins` matches the `abbreviation` (username-like) field.
- Both default to small `limit`; set explicitly. Response shape is a flat list `[{id, username, fullName, abbreviation, ...}]`.
- `searchTerm` is documented in the OpenAPI but silently returns empty — considered unreliable; avoid.

## Verification

Read back the qualification:

```
GET /api/model/dataModels/{modelId}/securityFilters/{sfId}?showFilterTokens=true
```

Read back the assigned members:

```
GET /api/dataModels/{modelId}/securityFilters/{sfId}/members
```

Classic/project security-filter member assignment is similar but not identical: it uses `/api/securityFilters/{id}/members` and the lowercase `/members` patch path documented in `reference_strategy_legacy_semantic_admin.md`. Keep these two surfaces separate in helper code and audit findings.

## Full example

```python
# user: <resolved user objectId>
# attr: <attribute objectId>  form: ID (45C11FA478E745FEA08D781CEA190FE5 — platform constant)
# element: the literal value you want to filter on (e.g., Category_ID=1)

cs = open_cs(m)
sf = m.s.post(f"{B}/api/model/dataModels/{MODEL}/securityFilters",
              headers={"X-MSTR-MS-Changeset": cs},
              json={
                "information": {"name": "<filter name>", "subType": "md_security_filter"},
                "qualification": {"tree": {
                  "type": "predicate_form_qualification",
                  "predicateTree": {
                    "function": "equals",
                    "attribute": {"objectId": ATTR_ID, "subType": "attribute"},
                    "form": {"objectId": ID_FORM, "subType": "attribute_form_system"},
                    "parameters": [{"parameterType": "constant", "constant": {"type": "int32", "value": "<element-value>"}}]
                  }
                }},
                "topLevel": [], "bottomLevel": []
              }).json()["information"]["objectId"]
commit_cs(m, cs)

m.s.patch(f"{B}/api/dataModels/{MODEL}/securityFilters/{sf}/members",
          json={"operationList": [{"op": "addElements", "path": "/Members",
                                   "value": [USER_ID]}]})
# 204 = success
```
