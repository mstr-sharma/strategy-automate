---
name: Strategy validation workflow suite
description: Tenant-verified non-Mosaic, non-AI validation workflows for proving Strategy automation coverage against a live demo environment.
type: reference
originSessionId: validation-session
status: tenant-verified-2026-04-21
---
Use this to validate the Strategy automation memory/skills against a live environment. These workflows intentionally exclude Mosaic data-model and AI/Agent/Bot work.

Credentials must come from runtime input or environment variables. Never write passwords, auth tokens, cookies, exports, or returned business data into memory or the repo.

## Verified runner

Script: `$REPO/skill/scripts/strategy_validate.py`

Command pattern:
```bash
python3 skill/scripts/strategy_validate.py --yes --keep-security-artifacts --package-holder
```

Example passing run:
- run ID: `validation-<YYYYMMDD-HHMM>`
- project: any tutorial-style project (resolve via `/api/projects`)
- result: `pass=10 warn=0 skip=0 fail=0`
- kept requested artifacts: one security filter + one user membership record as sample.
- optional package holder is created and deleted in the same run.

Live gotchas captured from the run:
- For these classic/project workflows, use `X-MSTR-AuthToken` plus `X-MSTR-ProjectID`; do not automatically add `X-MSTR-IdentityToken`. On this tenant, adding identity token caused `/api/model/metrics/{id}` to fail with a false "Wrong projectId" error.
- Search by exact name and prefer ancestors under `Schema Objects`; exact-name collisions exist under `Object Templates > Agents`. The schema `Category` attribute is `8D679D3711D3E4981000E787EC6DE8A4`, while an Agent template object with the same name failed element/model reads.
- `/api/attributes/{attributeId}/elements?searchTerm=Books` worked for the schema `Category` and returned `{"name":"Books","id":"h1;;Books"}`. Report-scoped element endpoints returned `8D679D3711D3E4981000E787EC6DE8A4:1`. Use the tenant-accepted generic endpoint when available, otherwise fall back to report/cube-scoped element endpoints.
- `POST /api/model/changesets/{changesetId}/commit` accepted `{}`. A body with `userComments` was rejected as an unrecognized field.
- `POST /api/documents/{id}/instances` returned HTTP 201 and instance key `mid`; export used that `mid` and returned HTTP 200 JSON with `data`.
- Monitor cache endpoints may be unavailable to the demo user; treat privilege/availability limits as evidence, not as workflow failure, when the admin probe is intentionally non-destructive.

## Execution rules

- Use one run ID suffix, e.g. `validation-YYYYMMDD-HHMM`, for any created object.
- First run every workflow in read-only/probe mode where possible.
- For write workflows, resolve and print target IDs before writing.
- Clean up all test-created objects unless the user explicitly asks to keep them.
- If cleanup fails, record the object ID/name and exact endpoint needed for cleanup in the final response.
- Skip a workflow, rather than forcing it, if required privileges or safe target content are unavailable.
- Do not execute subscription sends, project unloads, datasource mutations, cache deletions, package imports, or object deletes unless the specific workflow explicitly says they are in scope and the user signs off.

## 10 validated workflows

### 1. Auth, Project, And Session Baseline

Purpose: verify login/session/project discovery and capture tenant version/spec behavior.

Scope: read-only.

Core steps:
- `POST /api/auth/login`
- `GET /api/projects`
- Resolve `MicroStrategy Tutorial`
- Fetch live `/api/openapi.yaml?visibility=all`
- Optional `GET /api/sessions` or identity/session endpoints if exposed
- `POST /api/auth/logout`

Verification:
- Auth token received, project ID resolved, OpenAPI reachable, logout succeeds.

### 2. Search, Browse, Object Metadata, And ACL Read

Purpose: prove object discovery and classic object-security read routing.

Scope: read-only.

Core steps:
- Quick search with `/api/searches/results` for known objects (`Category`, a report/dashboard/document).
- Metadata search with `/api/metadataSearches/results` for the same term when available.
- Browse predefined/public folders with `/api/folders/preDefined/...` or `/api/folders/{id}`.
- `GET /api/objects/{id}?type=<type>` for one resolved object.
- Inspect ACL fields without changing them.

Verification:
- Same target object can be resolved by search/browse and read by object ID/type.

### 3. Classic Attribute And Element Inspection

Purpose: validate legacy/project attribute handling and element browsing.

Scope: read-only.

Core steps:
- Resolve `Category` attribute by exact name/type.
- `GET /api/model/attributes/{attributeId}?showExpressionAs=tree`
- `GET /api/attributes/{attributeId}/elements?searchTerm=Books` when available; otherwise use report/cube-scoped element endpoints.
- Confirm the `Books` element ID/display value.

Verification:
- Attribute details and element list are retrieved; no Mosaic/data-model attribute endpoints are used.

### 4. Classic Metric Definition Inspection

Purpose: validate legacy/project metric routing and expression retrieval.

Scope: read-only.

Core steps:
- Search for a simple metric such as `Revenue`, `Profit`, or `Cost`.
- `GET /api/model/metrics/{metricId}?showExpressionAs=tree`
- Fetch applicable advanced properties if exposed.
- Read object metadata with `/api/objects/{id}?type=4`.

Verification:
- Metric definition, expression, object metadata, and applicable properties are readable.

### 5. Runtime Report Or Cube Data Extraction

Purpose: validate JSON Data API runtime execution without changing metadata.

Scope: runtime instance only.

Core steps:
- Search for a small report or cube that the demo user can execute.
- `POST /api/reports/{reportId}/instances` or `POST /api/cubes/{cubeId}/instances`.
- Fetch first page/result with a small limit.
- Apply a runtime view filter or requested objects only if the target supports it.
- Delete/cleanup the instance if endpoint supports it.

Verification:
- A compact data sample is returned here in the chat, with object IDs and row/column counts.

### 6. Runtime Prompt Discovery And Answer Probe

Purpose: prove prompt-answer automation without editing prompt definitions.

Scope: runtime instance only; skip if no safe prompted content exists.

Core steps:
- Search for prompted report/document/dashboard content.
- Create instance or read prompt definitions.
- `GET .../prompts` and available prompt elements/objects as applicable.
- If safe, answer with default/no-answer or a small explicit answer.
- Re-fetch status/result.

Verification:
- Prompt definitions and answer path are proven; final notes distinguish runtime prompt answer from `/api/model/prompts`.

### 7. Document/Dashboard Export Probe

Purpose: validate export workflows and asynchronous result polling.

Scope: runtime export only.

Core steps:
- Resolve a small document/dashboard/dossier.
- Create instance.
- Export PDF or CSV using document/dashboard export endpoint.
- Poll result/status endpoint when asynchronous.
- Delete temporary result/instance if supported.

Verification:
- Export job/result metadata is returned; do not store binary export in repo unless user asks.

### 8. User, Group, Role, And Privilege Readback

Purpose: validate governance reads before any user/security writes.

Scope: read-only.

Core steps:
- Resolve source user `$MSTR_USER`.
- List user details, memberships, addresses, security roles, privileges.
- List user groups and security roles visible to the session.
- Verify project-level context for role/privilege endpoints.

Verification:
- User/group/role/privilege surfaces are reachable and differentiated from ACL/security filters.

### 9. Classic Security Filter Assignment Write Test

Purpose: validate the classic project security-filter workflow requested by the user.

Scope: write with `-validation` names; cleanup decision required.

Core steps:
- Resolve project, source user `$MSTR_USER`, target username `validation_duplicate_user`.
- Resolve `Category` attribute and `Books` element.
- Create or reuse `Books_secFilter_validation` via `/api/model/securityFilters`.
- Duplicate user with `POST /api/users?sourceUserId=<$MSTR_USER id>` if `validation_duplicate_user` does not already exist.
- Assign filter with `PATCH /api/securityFilters/{id}/members`.
- Verify via `/api/securityFilters/{id}/members` and `/api/users/{id}/securityFilters`.

Cleanup options:
- Keep objects if the user wants the requested artifacts to remain.
- Otherwise revoke membership, delete duplicate user, and delete/move the test security filter only after explicit signoff.

Verification:
- Security filter is classic/project-level, not Mosaic data-model security filter.

### 10. Distribution, Package, And Monitor Admin Probe

Purpose: validate high-impact admin lanes without risky operations.

Scope: mostly read-only; optional create/delete of harmless package holder only if approved.

Core steps:
- Distribution: `GET /api/subscriptions`, `GET /api/schedules`, list addresses/recipients visible to `$MSTR_USER`.
- Monitor/cache: list cube/content caches and project status where privileges allow; do not alter/delete caches.
- Packages: optionally `POST /api/packages` to create an empty package holder, `GET /api/packages/{id}`, then `DELETE /api/packages/{id}`. Do not upload/import packages.

Verification:
- Read access and privilege limitations are captured. Any package holder created is deleted in the same run.

## Additional hardening after first live run

- Executable validation harness added at `skill/scripts/strategy_validate.py` with `--workflow`, `--yes`, `--keep-security-artifacts`, `--package-holder`, and `--run-id` flags.
- Cleanup ledger is written to `/tmp/strategy-validation-<run-id>.json`, never into the repo.
- Runner includes idempotent find-or-create behavior for the security filter and duplicate user.
- Runner resolves exact object names with ancestor scoring to avoid object-template/agent collisions.
- Runner uses privilege-aware unavailable statuses for admin monitor/cache probes.
