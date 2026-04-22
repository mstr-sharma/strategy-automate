---
name: Strategy legacy semantic layer and admin workflows
description: Distinguish classic project semantic-layer/admin workflows from Mosaic data-model and AI/agent workflows.
type: reference
originSessionId: codex-session
---
Use this when a user asks for "legacy", "classic", "project-level", or existing MicroStrategy semantic-layer automation: attributes, facts, metrics, filters, security filters, users, groups, roles, subscriptions, ACLs, VLDB, object moves/copies, or legacy object edits.

## Surface selection

Strategy now exposes similarly named objects across different surfaces. Route by object ownership, not by keyword alone:

- **Classic/project semantic layer:** project metadata objects that exist outside a Mosaic data model. Use top-level Modeling Service endpoints such as `/api/model/attributes`, `/api/model/metrics`, `/api/model/facts`, `/api/model/filters`, `/api/model/securityFilters`, plus object/admin APIs such as `/api/securityFilters`, `/api/users`, `/api/usergroups`, `/api/objects`. These are the old MicroStrategy project semantic-layer workflows.
- **Mosaic data models:** objects contained inside a modern data model. Use `/api/model/dataModels/{dataModelId}/...` and `/api/dataModels/{dataModelId}/...`. A request must mention a Mosaic model/data model/model ID, or be clearly about a scratch Mosaic build, before using these paths.
- **AI/agents/newer workflows:** Agent, AI service, Auto, bot, MCP, and NLQ/data-question surfaces. Discover in live OpenAPI (`/api/openapi.yaml?visibility=all`) and prefer MCP tools for semantic query/inspection when the connector is available.

If the user says "security filter" without a model ID and references users/groups or a project, assume **classic project security filter**, not Mosaic data-model row-level security.

For a broader matrix covering attributes, metrics, ACLs, roles, cubes, datasets, and AI/agent surfaces, read `reference_strategy_surface_matrix.md` first.

For deep read-only inspection of object internals before cloning, updating, or modernizing a legacy semantic layer, read `reference_strategy_tutorial_semantic_field_study.md` and use:

```bash
python3 skill/scripts/strategy_semantic_inventory.py --workers 8 --out /tmp/strategy-semantic-inventory.json
```

Add `--include-definition-bodies` only when you need raw bodies for analysis, and keep that output in `/tmp`.

## Classic semantic object internals

Use exact object resolution before editing. Search results can include same-named Agent object templates, system objects, custom groups, and transformation attributes that do not behave like normal project schema objects.

Core read paths:

- Attributes: `GET /api/model/attributes/{attributeId}?showExpressionAs=tree`
- Facts: `GET /api/model/facts/{factId}?showExpressionAs=tree`
- Metrics: `GET /api/model/metrics/{metricId}?showExpressionAs=tree`
- Filters: `GET /api/model/filters/{filterId}?showExpressionAs=tree&showFilterTokens=true`
- Prompts: `GET /api/model/prompts/{promptId}?showExpressionAs=tree`
- System hierarchy: `GET /api/model/systemHierarchy`
- Attribute relationships: `GET /api/model/systemHierarchy/attributes/{attributeId}/relationships`
- User hierarchies: `GET /api/model/hierarchies`, then `GET /api/model/hierarchies/{hierarchyId}`

Object anatomy worth preserving:

- **Attributes:** forms, key form, lookup table, display forms, expression trees, table mappings, relationship tuples, element-caching/security-filter flags.
- **Facts:** data type, all expression/table mappings, entry level, fact extensions/allocation expressions, alias.
- **Metrics:** expression tree, nested metric/fact references, dimensionality (`dimty`), conditionality, transformation roles, subtotals, smart total, thresholds, format tokens.
- **Filters:** qualification text/tree/tokens; distinguish element lists, form qualifications, metric qualifications, prompt-backed filters, relationship/report qualifications, and custom groups.
- **Prompts:** question, default answer, restriction, expression type, predefined objects/elements, and whether the prompt is a non-editable system prompt.
- **Hierarchies:** system hierarchy gives relationship tables and cardinality; user hierarchies give curated drill/browse paths.

When translating to Mosaic, use classic relationships/fact tables as source evidence, but do not blindly copy every prompt, report filter, custom group, or agent/template object into the new model.

## Classic project security filters

Classic security filters are project metadata objects. They narrow data for users/groups across the project.

Create/read/update the filter definition through top-level Modeling Service:

- Create changeset: `POST /api/model/changesets?schemaEdit=false`
- Create filter object: `POST /api/model/securityFilters` with `X-MSTR-MS-Changeset`
- Read definition: `GET /api/model/securityFilters/{securityFilterId}` with `X-MSTR-ProjectID` and optional `showExpressionAs=tree|tokens`, `showFilterTokens=true`
- Commit: `POST /api/model/changesets/{changesetId}/commit` with body `{}`. Tenant `a verified Strategy Cloud tenant` rejected `{"userComments":...}` as an unrecognized field.

List and assign members through the non-model security filter API:

- List project filters: `GET /api/securityFilters?nameContains=<name>`
- Assign users/groups: `PATCH /api/securityFilters/{id}/members`
- Verify members: `GET /api/securityFilters/{id}/members`
- Verify a user's project filters: `GET /api/users/{id}/securityFilters`

Member patch body:

```json
{"operationList":[{"op":"addElements","path":"/members","value":["<user-or-group-id>"]}]}
```

Use `removeElements` for revocation. Values are user or user-group IDs, not names.

Do **not** use these Mosaic-only paths for a classic project security filter:

- `/api/model/dataModels/{dataModelId}/securityFilters`
- `/api/dataModels/{dataModelId}/securityFilters/{securityFilterId}/members`

Those are for security filters owned by a Mosaic data model.

## Element-list security filter shape

For a qualification such as `Category = Books`:

1. Resolve the project ID from `GET /api/projects`.
2. Resolve the attribute with `/api/searches/results?name=Category&type=12&pattern=4`, then prefer exact-name objects under `Schema Objects > Attributes`. Do not blindly take the first fuzzy result; `Category` also appeared under `Object Templates > Agents` and failed Modeling/element reads.
3. Resolve the attribute element with `/api/attributes/{attributeId}/elements?searchTerm=Books` when the generic route is tenant-supported. If not, use a report/cube context such as `/api/reports/{reportId}/attributes/{attributeId}/elements`.
4. Create a `ms-SecurityFilter` qualification using a `predicate_element_list` tree.

Minimal body shape:

```json
{
  "information": {
    "name": "Books_secFilter-codex",
    "destinationFolderId": "<folder-id>"
  },
  "qualification": {
    "tree": {
      "type": "predicate_element_list",
      "predicateId": "p1",
      "predicateText": "Category in Books",
      "predicateTree": {
        "attribute": {"objectId": "<category-attribute-id>", "subType": "attribute", "name": "Category"},
        "elements": [{"display": "Books", "elementId": "<books-element-id>"}],
        "function": "in"
      }
    }
  }
}
```

On `a verified Strategy Cloud tenant`, the schema `Category` attribute was `8D679D3711D3E4981000E787EC6DE8A4`; generic element lookup returned `{"name":"Books","id":"h1;;Books"}`, and using that ID as `elementId` in the security-filter body committed successfully.

If a tenant rejects hand-authored predicate trees, use mstrio-py or clone/remap a working security filter returned by `GET /api/model/securityFilters/{id}?showExpressionAs=tree`. mstrio-py accepts a string qualification and builds the expression body for `/api/model/securityFilters`.

For classic/project workflows, do not automatically add `X-MSTR-IdentityToken`. On `a verified Strategy Cloud tenant`, adding identity token after login caused classic Modeling Service metric reads to fail with a false "Wrong projectId" error. Use `X-MSTR-AuthToken` plus `X-MSTR-ProjectID` unless a specific tenant endpoint proves it needs identity token.

## User duplication and assignment

Duplicate a user with the REST User Management API:

- Resolve source user: `GET /api/users?nameBegins=<username>`
- Create duplicate: `POST /api/users?sourceUserId=<sourceUserId>`
- Required body fields: `username`, `fullName`; include `enabled` and description/comment as needed.
- If the target username already exists, verify it is the intended user and continue with assignment instead of creating another near-duplicate.

Then assign the project security filter with `PATCH /api/securityFilters/{id}/members` as above.

## Object security, roles, and privileges

Do not conflate these with security filters:

- **Object ACL / object security:** who can browse, read, write, delete, control, execute, or use an object.
- **Security roles / privileges:** what capabilities a user or group has.
- **Security filters:** row-level restrictions applied to users/groups.

Classic object ACL workflow:

- Read object and ACL: `GET /api/objects/{id}?type=<type>`.
- Update object and ACL: `PUT /api/objects/{id}?type=<type>`.
- Body uses `acl` entries with `op` (`ADD`, `REPLACE`, etc.), `trustee`, `rights`, `denied`, `inheritable`, and `type`.
- Folder ACLs can propagate to children with `propagateACLToChildren` and propagation behavior.

Mosaic data-model object ACL workflow is different:

- `GET/PATCH /api/model/dataModels/{dataModelId}/objects/{objectId}/acl?subType=<subType>`.
- Patch requires a changeset and commit.

## mstrio-py package notes

Official package/repo: `mstrio-py`, GitHub `MicroStrategy/mstrio-py`.

Useful modules for this lane:

- `mstrio.modeling.security_filter.SecurityFilter`
- `mstrio.modeling.security_filter.list_security_filters`
- `mstrio.api.security_filters`
- `mstrio.users_and_groups.user.User`
- `mstrio.users_and_groups.user_group.UserGroup`
- `mstrio.access_and_security.security_role`
- `mstrio.access_and_security.privilege`
- `mstrio.utils.acl`

mstrio-py's `SecurityFilter.create(...)` wraps `POST /api/model/securityFilters` and its `apply(...)` wraps `PATCH /api/securityFilters/{id}/members`. Use mstrio-py when expression construction is the fragile part, but capture the resolved REST endpoint and IDs in the final notes so future agents can reproduce the workflow without relying on hidden wrapper state.

## Verification checklist

- Read before write: exact project, object name, source user, destination username, and folder ID.
- For security filters: verify the committed object can be read by `/api/model/securityFilters/{id}` and listed by `/api/securityFilters`.
- For member assignment: verify `/api/securityFilters/{id}/members` contains the new user ID.
- For user-centric verification: verify `/api/users/{id}/securityFilters` includes the filter under the intended project.
- Logout with `DELETE /api/auth/login` when the task finishes.
