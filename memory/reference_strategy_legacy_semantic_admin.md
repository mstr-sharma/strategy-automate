---
name: Strategy legacy semantic layer and admin workflows
description: Distinguish classic project semantic-layer/admin workflows from Mosaic data-model and AI/agent workflows.
type: reference
originSessionId: codex-session
---
Use this when a user asks for "legacy", "classic", "project-level", or existing MicroStrategy semantic-layer automation: attributes, facts, metrics, filters, security filters, users, groups, roles, subscriptions, ACLs, VLDB, object moves/copies, or legacy object edits.

## Surface selection

Strategy now exposes similarly named objects across different surfaces. Route by object ownership, not by keyword alone — `reference_strategy_surface_matrix.md` is the routing file (classic/project semantic layer vs Mosaic data models vs runtime vs Push Data vs admin vs AI/agents); read it first. This file owns the classic/project workflows themselves.

Two classic-lane heuristics worth keeping here:

- A request must mention a Mosaic model/data model/model ID, or be clearly about a scratch Mosaic build, before using `/api/model/dataModels/...` or `/api/dataModels/...` paths.
- If the user says "security filter" without a model ID and references users/groups or a project, assume **classic project security filter**, not Mosaic data-model row-level security.

For deep read-only inspection of object internals before cloning, updating, or modernizing a legacy semantic layer, read `reference_strategy_tutorial_semantic_field_study.md` and use:

```bash
python3 skills/build-mosaic-model/scripts/strategy_semantic_inventory.py --workers 8 --out /tmp/strategy-semantic-inventory.json
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

Do **not** use the Mosaic data-model security-filter paths for a classic project security filter — the classic-vs-Mosaic SF routing rows live in `reference_strategy_surface_matrix.md` ("Security and access").

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

## Classic attribute + fact creation (verified write path)

Verified 2026-08-25 on a Strategy Cloud tenant (17 objects, one bulk changeset):

- Changeset: `POST /api/model/changesets?schemaEdit=true` → create objects with `X-MSTR-MS-Changeset` + `X-MSTR-ProjectID` (no identity token) → `POST /api/model/changesets/{id}/commit` with body `{}` (201).
- Attribute: `POST /api/model/attributes` with `information` (`subType:"attribute"`, `destinationFolderId`), `forms[]`, `attributeLookupTable`, `keyForm:{"name":"ID"}` (name refs OK at create), `displays:{reportDisplays:[{name}],browseDisplays:[{name}]}`.
- Form shape: `{name, category ("ID"/"DESC", omit for extra forms), type, displayFormat, dataType, expressions[], lookupTable}`. **Form `type` enum: `"system"` works, `"normal"` is rejected (`8004c908`)** — use `"system"` for every form incl. extra ones.
- Fact: `POST /api/model/facts` with `information` (`subType:"fact"`), `dataType`, `expressions[]`.
- Expression grammar (attribute forms + facts): `{"expression":{"tokens":[{level:"resolved",state:"initial",value:"<COL>",type:"column_reference",target:{objectId:<columnId>,subType:"column",name:"<COL>"}},{...type:"end_of_text",value:""}]},"tables":[{objectId,subType:"logical_table",name}]}` — clone-shape from any `GET ...?showExpressionAs=tokens`.
- Column objectIds come from `GET /api/model/tables/{logicalTableId}`; same-named columns share ONE column object across tables (that shared id is what makes a multi-table form expression legal).
- **Post-commit schema lock lingers:** after committing a `schemaEdit=true` changeset and logging out, the schema stays locked (`GET /api/model/schema/lock` shows LOCKID = your committed changeset; delete of that changeset from a new session 500s with `8004cb15` "does not belong to the user"). Fix: `DELETE /api/model/schema/lock` (200 when the lock owner is your account), then `POST /api/model/schema/reload` with body `{"updateTypes": []}` (the field is mandatory — `8004c901` without it; `table_logical_size` is not a valid value).

## Classic metric creation + dynamic aggregation + cube publish (verified write path)

Verified 2026-08-25 on a Strategy Cloud tenant (19-metric library + intelligent cube over a 64.8K-row Postgres star, validated to 4 decimals against warehouse SQL).

**Metric creation — always go through the formula parser:**
- `POST /api/model/metrics` with `expression: {"tokens": [{"value": "Avg([Float Value])"}]}` — ONE raw-text token; the parser builds the embedded `agg_metric` + `dimty` layer the SQL engine requires. Tree-built `{"operator","function":"avg",children:[fact ref]}` bodies are ACCEPTED by Modeling but the engine cannot load them (`-2147212797`); repair in place by PUTting a raw-token expression (object id survives).
- Parser-verified grammar: `Avg/StDev/Min/Max/Count(fact)`, arithmetic compounds by `[name]` reference, `IF(a<b,x,y)`, `IsNull([m])` (tree function name is `is_null`; token text is `IsNull`), `Sqrt`, `[m]*[m]`.
- Compounds cannot reference same-changeset metrics (`8004cb04`) — commit bases, then compounds.
- Ratio/formula compounds need `smartTotal: "decomposable_true"` to recompute from components at view level.
- When PUTting a compound expression over an echoed GET body, pop `dimty` AND `conditionality` (`8004d711`).

**Dynamic aggregation (what makes cube datasets roll up in dossiers):** encoded as a `metricSubtotals` entry — `{"definition": {Aggregation system subtotal F225147A4CA0BB97368A5689D9675E73}, "implementation": {<function's system subtotal>}}`; set `Total`'s implementation to the same function for grand totals. Prereq: `aggregateFromBase` and `subtotalFromBase` must both be `false` (`8004d713`/`8004d714`). System subtotal ids (product-wide): Total `96C487AF4D12472A910C1ACACFB56EFB`, Count `078C50834B484EE29948FA9DD5300ADF`, Average `B328C60462634223B2387D4ADABEEB53`, Minimum `00B7BFFF967F42C4B71A4B53D90FB095`, Maximum `B1F4AA7DE683441BA559AA6453C5113E`, Standard Deviation `7FBA414995194BBAB2CF1BB599209824`, Aggregation `F225147A4CA0BB97368A5689D9675E73`. Without this, Avg/StDev metrics show `--` above cube grain (default dynamic aggregation is none).
- **Sigma on a unit-grain cube can never dynamically aggregate** (stddev cells are NULL at n=1): use the sum-of-squares pattern — base metric `Avg([x]*[x])` (Aggregation=Average) + smart compound `Sqrt((n/(n-1))*(E[X2]-Mean*Mean))`. Exact at every level.

**Intelligent cube build/publish:**
- Create: `POST /api/v2/cubes` `{name, folderId, definition:{availableObjects:{attributes:[{id,name,type}], metrics:[...]}}}` (what mstrio `OlapCube.create` wraps). Update definition: `PUT /api/v2/cubes/{id}` (204).
- Publish: `POST /api/v2/cubes/{id}` → `{jobId, instanceId}`. **Jobs are session-bound — logging out cancels a running publish.** Keep the triggering session alive until done.
- Status: `HEAD /api/cubes/{id}` → `X-MSTR-CubeStatus` (0 = no cache). Meaningful only for a FIRST publish; on republish it reports the old cache — the only truth is an execute probe. Real publish errors: `GET /api/v2/cubes/{id}/instances/{instanceId}` (blocks while running — use a short read timeout; timeout = still running).
- Project governors default 32000 and kill larger cube publishes silently (`-2147205488`): raise `maxCubeResultRowCount`/`maxReportResultRowCount`/`maxInternalResultRowCount` via `PATCH /api/v2/projects/{id}/settings` `{name:{value:N}}`.
- Multi-pass temp-table SQL on pooled/small Postgres = un-analyzed temp tables + nested-loop plans (minutes for tiny data). Fix: VLDB **Intermediate Table Type = Derived table** via `PUT /api/objects/{cubeId}/vldb/propertySets/{setName}?type=3` body `[{"name":"Intermediate Table Type","value":1}]` — value must be an int, not a string; the collection endpoint is GET-only (405); db_role objects (type 29) are not supported by this endpoint.
- Sparse cross-table objects (an overrides/write-back table with rows for only some keys) inner-join into cube SQL and silently trim the key list — model a LEFT-JOIN view (one row per key, NULLs where absent) and bind the facts there instead.

## Classic prompts, N-level nested (cascading) prompts, and report creation (verified write path)

Verified 2026-08-26 on a Strategy Cloud tenant (3-level Category→Subcategory→Item chain in the Tutorial project, executed end-to-end over REST). This is the KB10434 pattern (prompt → filter-wrapping-prompt → next prompt element-restricted by that filter), fully authorable without Developer.

**Prompt objects (`POST /api/model/prompts`, changeset-scoped like other Modeling writes):**
- Element prompt body: `information` (`subType:"prompt_elements"`, `destinationFolderId`), `title`, `instruction`, `question: {attribute: {objectId, subType:"attribute"}, listAllElements: true}`, `restriction: {required: bool, allowPersonalAnswers: "none"}`.
- **The cascade hook is `question.filter`** — set `{objectId: <filterId>, subType: "filter"}` (+ `listAllElements: false`) to restrict the element list by a filter. The restricting filter MAY itself contain a prompt; Modeling accepts it and the engine resolves it at run time.
- Prompted filter shape: `qualification.tree = {type: "predicate_element_list", predicateTree: {elementsPrompt: {objectId, subType: "prompt_elements"}}}` (Workstation-authored ones may show `isEmbedded: true`; standalone references work the same).
- Commit each object before the next references it (same rule as compound metrics / `8004cb04`): P1 → F1(wraps P1) → P2(restricted by F1) → F2 → … Only the DEEPEST filter goes on the report; the engine discovers the chain and asks prompts in dependency order. Make every level `required`, or AND all level filters onto the report — optional lower prompts left unanswered mean no filtering at all (KB37738).

**Workstation editor limitation (not an engine one):** the prompt editor's "Filtered elements" pick immediately element-browses with the chosen filter for a preview; a prompted filter can't be browsed at design time, so the editor refuses with *"The filter … contains prompts. Filtered element browsing is not supported with a filter that contains prompts."* Workaround verified server-side: point the prompt at a static placeholder filter (preview works, saves), then PUT the placeholder filter's qualification to the prompted element list afterwards — the prompt's `question.filter` reference survives the swap. `PUT /api/model/filters/{id}` is full-replace: echo the GET `information` block alongside the new `qualification` or it 400s (`8004c901` missing-field).

**Classic report creation (`POST /api/model/reports`) — instance-based, NOT changeset-based:**
- POST body: `information` (`subType:"report_grid"`), `sourceType:"normal"`, `dataSource: {dataTemplate: {units: [attribute refs + {type:"metrics", elements:[metric refs]}]}, filter: …}`, `grid: {viewTemplate: {rows/columns/pageBy}}` (clone shape from any `GET /api/model/reports/{id}`).
- The POST returns the new objectId in the body and an **`X-MSTR-MS-Instance` response header**; persist with `POST /api/model/reports/{id}/instances/saveAs` (that header + `{name, destinationFolderId}`). Default promptOptions keep filter/template prompted.
- **Report-filter-by-reference: the OpenAPI-documented `{"standaloneFilter": {…}}` shape is REJECTED** (`8004c90a` "Unrecognized field") on the observed build — use the shape real reports carry: `filter: {tree: {type: "predicate_filter_qualification", predicateTree: {filter: {objectId, subType:"filter"}, isIndependent: 0}}}`.

**Runtime prompt answering (how to verify a cascade without a browser):**
- `POST /api/v2/reports/{id}/instances` `{}` → `status: 2` (prompted); v1 prompt endpoints work with the v2 instance id.
- `GET /api/reports/{id}/instances/{iid}/prompts` is **progressive**: round 1 lists only the level-1 prompt; each answered level makes the next appear (this is why Web/Library render nested prompts as sequential steps). Prompt `key` looks like `<promptId>@0@10`.
- Element browse: `GET …/prompts/{key}/elements?limit=200` — returns exactly the restricted list (verified counts: 4 categories → 6 subcategories of the chosen category → 15 items of the chosen subcategory). Element ids come back as `h<N>;<attributeId>` — feed them back verbatim.
- Answer: `PUT …/prompts/answers` `{"prompts": [{"key", "type": "ELEMENTS", "answers": [{"id", "name"}]}]}` (204), loop until the prompt list is empty, then `GET /api/v2/reports/{id}/instances/{iid}` for data.

**When the ask is cascading choices on a DASHBOARD, don't build prompt chains** — dashboard filter-panel attribute filters natively target other filters (filter's More menu → Select Targets, optional "Update targets automatically"); element lists come from the dataset, so an in-memory cube makes every cascade update memory-speed, while live-connect fires SQL per interaction. Prompt chains are for prompted reports/subscriptions and SQL-level slicing of big dimensions; a dashboard on a prompted report asks prompts at dataset add/re-prompt time, not per viewer.

## User duplication and assignment

Duplicate a user with the REST User Management API:

- Resolve source user: `GET /api/users?nameBegins=<username>`
- Create duplicate: `POST /api/users?sourceUserId=<sourceUserId>`
- Required body fields: `username`, `fullName`; include `enabled` and description/comment as needed.
- If the target username already exists, verify it is the intended user and continue with assignment instead of creating another near-duplicate.

Then assign the project security filter with `PATCH /api/securityFilters/{id}/members` as above.

## Object security, roles, and privileges

Do not conflate object ACLs, security roles/privileges, and security filters. The concept distinctions, the classic object ACL workflow (`GET/PUT /api/objects/{id}?type=<type>` with `acl` entries, rights bitmasks, `propagateACLToChildren`), and the different Mosaic data-model object ACL workflow (changeset-scoped `GET/PATCH /api/model/dataModels/{dataModelId}/objects/{objectId}/acl?subType=<subType>`) are routed in `reference_strategy_surface_matrix.md` ("Security and access"); Mosaic ACL payload depth is in `reference_mosaic_acl.md`.

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
