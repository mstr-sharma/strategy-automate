---
name: strategy-content
description: Find, run, export, create and organize Strategy (formerly MicroStrategy) content over REST — reports, dashboards (dossiers) and documents, prompt answers, PDF / Excel / CSV exports, quick and metadata search, lineage, folders, object copy, move, rename and delete, certification, Library publications and content groups, classic and data-import cubes (publish, refresh, status, data) and Push Data datasets. Use it for "report", "dashboard", "dossier", "document", "export to PDF/Excel/CSV", "run a report", "prompt answers", "search objects", "folder", "copy/move object", "certify", "Library publish", "cube", "dataset", "refresh a cube" or "what uses this object". Every call goes through strategy_api.py, validated against the tenant's own OpenAPI spec. Building or publishing Mosaic models belongs to build-mosaic-model.
---

# Strategy content

Reports, dashboards (dossiers), documents, folders, cubes and datasets: find them, run them, export them, create and organize them. Every call goes through `strategy_api.py`; sign-in, `ops` / `describe` / `call`, dry runs and `--yes` are in `skills/strategy-platform/SKILL.md`. Exports carry live data; deletes and overwrites are permanent.

## Scope

Owns the spec tags Reports (with `/api/model/reports`), Dashboards, Dashboards(Dossiers) and Documents, Dashboard(Dossier) Personal View, the ToBeDeprecated `/api/dossier/…` family, Library, Browsing, Object Management, Content Groups, Content Bundles, Themes, Palettes, Maps, Cards, Hyper, Elements, Transaction Reports, Cubes, Datasets, Datamarts, MDX Cube Catalog, Runtimes and Shared File Store: `$API ops --tag strategy-content`. Themes, palettes, maps, datamarts, transaction reports, MDX catalogs, runtimes and the shared file store have no workflow here yet — `ops --tag <tag>`, `describe`, `call`.

Route elsewhere:
- Mosaic data models (type 3, subtype 779 + extType 448): build, publish, refresh, model objects, model ACLs and security filters → `skills/build-mosaic-model/SKILL.md`. Classic schema objects (attributes, facts, metrics, filters, prompt definitions) → `skills/build-mosaic-model/SKILL.md` ("Classic schema objects"; plan with `skills/strategy-data-modeling/SKILL.md`).
- Subscriptions, schedules, scheduled refresh, History List → `skills/strategy-distribution/SKILL.md`.
- Users, groups, ACL trustees, security roles, privileges, project row governors → `strategy-admin`. Caches, jobs, monitors, telemetry → `strategy-ops`. Packages, migrations, project duplication → `strategy-migration`. Numbers that must match a reference → `skills/strategy-validation/SKILL.md`.

## How to work

1. Sign in once (`strategy_auth.py login`), export `MSTR_PROJECT_ID`, and from the repo root `API="python3 skills/strategy-platform/scripts/strategy_api.py"`.
2. `$API describe <operationId>` before every call. `describe` and `call` flag the operations the spec marks deprecated (`"deprecated": true`) — the `/api/dossier/…` family, `/api/dossierPersonalView`, `/api/dashboards…` (`.mstr` import/export, `createDashboard`), `answerPrompts_1` and `/api/objects/cubes/dataImport`. Avoid them.
3. Classify before every write: `$API call getObject -p id=<id> -p type=<type>`. Types: `3` report/cube/model (subtype 768 grid, 769 graph, 774 grid+graph, 776 classic cube, 779 data-import cube — a Mosaic model when `extType` is 448 — 781 Hyper card), `55` dashboard/document (14081), `8` folder, `18` shortcut, `1` filter, `4` metric, `12` attribute, `34` user/group, `58` security filter.
4. Reads first. Instances, exports, searches and queries are POSTs: they change nothing, but `call` still needs `--yes`.
5. Every write: run it without `--yes`, check the printed request, then add `--yes`; read the object back.
6. Delete the instances you create (`deleteDocumentInstance`, `ms-deleteReportInstance`) and any test folders, copies or datasets; report leftovers with their ids.

**One session.** `call` signs in and out per run unless the session is a cached browser one (`strategy_auth.py login --method sso`) or you pass `--reuse-session` (`MSTR_REUSE_SESSION=1`; end it with `strategy_auth.py logout`), so a report / dashboard / cube instance, a metadata `searchId` or a running cube publish dies when that call returns (treat an `X-MSTR-MS-Instance` the same way). Use the cached `sso` session, or chain the steps in one process (needs the 32-hex `MSTR_PROJECT_ID`):

```python
import os, sys
sys.path.insert(0, "skills/strategy-platform/scripts")
import strategy_api as api, strategy_auth as sa
base, pid = os.environ["MSTR_BASE"].rstrip("/"), os.environ["MSTR_PROJECT_ID"]
spec, s = api.load_spec(base), sa.SafeSession()
s.headers.update({"Accept": "application/json", "Content-Type": "application/json"})
signin = sa.sign_in(s, sa.AuthConfig.from_env(base=base))
def run(op, *params, body=None):          # one spec-validated call in this session -> requests.Response
    o = api.find_operation(spec, op)
    return api.call(o, api.build_request(o, list(params), body, pid), base=base, session=s, project=pid)["response"]
try:
    iid = run("createReportInstance_1", "reportId=<id>", "limit=1000", body={}).json()["instanceId"]
    ...                                   # prompts, pages, exports, delete the instance
finally:
    sa.sign_out(s, base, signin)
```

## Workflows

### 1. Find objects

```bash
$API call doQuickSearch -p name=<text> -p pattern=4 -p type=55 -p getAncestors=true -p limit=50   # pattern 4 contains, 2 exactly, 1 begins with
$API call searchForDossiers -p searchTerm=<text> -p searchPattern=CONTAINS   # also searchForReports, searchForRSDs (documents)
$API call createSearch -p name=<text> -p pattern=4 -p type=3 -p domain=2 --yes   # metadata search → {id, totalItems}
$API call searchObjectList -p searchId=<id> -p offset=0 -p limit=200            # page to totalItems, same session
```

- Quick search is index-backed: fast, can lag, skips hidden objects. `-p type=3 -p certifiedStatus=CERTIFIED_ONLY` approximates what the Mosaic MCP server lists (certified models, cubes, reports). `build_mosaic.py search-objects --name <text> --type 55` wraps it.
- Metadata search reads the metadata itself (hidden objects too); its results live in the session, and a session runs one metadata search at a time.

### 2. Lineage and dependents

```bash
$API call doQuickSearch -p usesObjectId=<id> -p limit=200                                   # what uses it, one call
$API call createSearch -p usesObject="<id>;<type>" -p usesRecursive=true -p domain=2 --yes   # dependents, direct + indirect
$API call createSearch -p usedByObject="<id>;<type>" -p domain=2 --yes                     # its components
$API call getDependentCount --body '{"usesOneOf": ["<id>"]}' --yes                         # counts only
$API call getDependentSubscriptions -p objectId=<id> -p type=report                       # deliveries (strategy-distribution)
```

Page `createSearch` results with `searchObjectList` in the same session. Run this before any delete, move or overwrite.

### 3. Folders, copy, move, rename, certify, delete

```bash
$API call getPreDefinedFolder -p folderType=7 -p limit=200    # 1 Public Objects, 7 Public Reports, 19 My Objects, 20 My Reports, 39 root
$API call getFolder -p id=<folderId> -p limit=200
$API call createFolder --body '{"name": "<name>", "parent": "<parentFolderId>"}' --yes
$API call copyObject -p id=<id> -p type=55 --body '{"name": "<new name>", "folderId": "<folderId>"}' --yes   # 201 + new id
$API call updateObject -p id=<id> -p type=55 --body '{"folderId": "<folderId>"}' --yes     # move; {"name": …} renames
$API call certifyObject -p id=<id> -p type=55 -p certify=true --yes                        # certify=false removes it
$API call deleteObject -p id=<id> -p type=55 --yes                                         # explicit confirmation only
```

- `type` is required on every `/api/objects/{id}` call — take it from the search result.
- `copyObject` copies one object, not what it uses: a copied dashboard still reads the same datasets.
- `build_mosaic.py certify --object-id <id>` wraps certification for type 3 (Mosaic models). Certified content is what the Mosaic MCP server lists.
- `deleteFolder` removes the folder and everything in it. Bulk copy / move / delete (`PUT` / `DELETE /api/objects`) are internal. ACL edits through `updateObject` (`acl`) need trustees resolved via strategy-admin.

### 4. Run a report, answer prompts, page results

```bash
$API call getPrompts_1 -p reportId=<id>                                        # what it will ask
$API call createReportInstance_1 -p reportId=<id> -p limit=1000 --body '{}' --yes   # status 1: first page in the body; 2: prompted
$API call getPromptsFromInstance_1 -p reportId=<id> -p instanceId=<iid>        # open prompts, one cascade level at a time
$API call getPromptAvailableAttributeElement_1 -p reportId=<id> -p instanceId=<iid> -p promptIdentifier=<key> -p limit=200
$API call answerPrompts_2 -p reportId=<id> -p instanceId=<iid> --body @answers.json --yes   # 204; repeat until none are open
$API call executeReport_1 -p reportId=<id> -p instanceId=<iid> -p offset=1000 -p limit=1000   # next page
$API call getReportSqlView_1 -p reportId=<id> -p instanceId=<iid>
```

`answers.json`: `{"prompts": [{"key": "<key>", "type": "ELEMENTS", "answers": [{"id": "h<N>;<attributeId>", "name": "<element>"}]}]}`. `VALUE` takes `"answers": <value>`, `OBJECTS` `[{"id", "name", "type"}]`, `EXPRESSION` the runtime `{"expression": {"operator", "operands"}}` grammar (not the Modeling `predicate_*` tree); `"useDefault": true` only when the user chose the default.
- A non-prompted report's first page comes back from the create call, under any sign-in; every later step needs one session.
- `requestedObjects`, `viewFilter`, `metricLimits` and `sorting` in the instance body are runtime-only; nothing is saved.
- Report to a file: write the JSON pages out as CSV locally; `exportReportToExcel` exists but is internal.

### 5. Run and export a dashboard or document

```bash
$API call getVisualizationList_1 -p dossierId=<id>                      # chapters, pages, visualization keys, datasets
$API call createDossierInstance_2 -p dossierId=<id> --body '{}' --yes   # dashboard → mid
$API call createDocumentInstance -p id=<id> --body '{}' --yes           # document → mid
$API call getDocumentInstanceStatus -p id=<id> -p instanceId=<mid>     # 1 ready, 2 waiting for prompt answers
$API call answerPrompts -p id=<id> -p instanceId=<mid> --body @answers.json --yes   # the document endpoints serve dashboards too
$API call setFilters -p dossierId=<id> -p instanceId=<mid> --body '[{"key": "<filterKey>", "selections": [{"id": "<elementId>"}]}]' --yes
$API call getVisualizationResult_2 -p dossierId=<id> -p instanceId=<mid> -p chapterKey=<ck> -p visualizationKey=<vk> -p limit=1000
$API call exportDashboardToPdf -p id=<id> -p instanceId=<mid> --body '{"pageOption": "ALL"}' --yes --out <private-dir>/dash.json
$API call exportDocumentToExcel -p id=<id> -p instanceId=<mid> --body '{"pageOption": "ALL"}' --yes --out <private-dir>/dash.xlsx
$API call exportDocumentToCSV -p id=<id> -p instanceId=<mid> -p nodeKey=<vk> --body '{}' --yes --out <private-dir>/viz.csv
$API call deleteDocumentInstance -p id=<id> -p instanceId=<mid> --yes
```

- The PDF arrives as JSON `{"data": "<base64>"}` (`call` asks for JSON) — decode it into the `.pdf` under `umask 077`. Big exports: add `-p Prefer=respond-async`, then poll `getPdfExportResult -p id=<id> -p instanceId=<mid> -p resultId=<resultId>`. One tenant accepted only `NONE|AUTO` for `orientation`.
- Excel and CSV are `application/octet-stream` in the spec; `call` now sends that `Accept` type and writes the bytes to a private file (`--out` to choose it). Not yet exercised live.
- Whole-dashboard CSV (`exportDashboardToCsv`), the dashboard `answerPrompt` and the document `…/layouts/…/visualizations/…` reads are internal.

### 6. Create a report or a dashboard

Report — Modeling Service, saved through a report instance; clone the body from `ms-getReport` of a similar report:

```bash
$API call "POST /api/model/reports" --body @report.json --yes      # ms-postReport; 201; X-MSTR-MS-Instance is in the printed headers
$API call "POST /api/model/reports/{reportId}/instances/saveAs" -p reportId=<newId> -p X-MSTR-MS-Instance=<inst> --body '{"name": "<name>", "destinationFolderId": "<folderId>"}' --yes
```

`report.json`: `{"information": {"name": "<name>", "subType": "report_grid", "destinationFolderId": "<folderId>"}, "sourceType": "normal", "dataSource": {"dataTemplate": {"units": [{"id": "<attrId>", "type": "attribute"}, {"type": "metrics", "elements": [{"id": "<metricId>", "subType": "metric"}]}]}}, "grid": {"viewTemplate": {"rows": {"units": [{"id": "<attrId>", "type": "attribute"}]}, "columns": {"units": [{"type": "metrics", "elements": [{"id": "<metricId>", "subType": "metric"}]}]}}}}`. Reference a saved filter with `"filter": {"tree": {"type": "predicate_filter_qualification", "predicateTree": {"filter": {"objectId": "<filterId>", "subType": "filter"}, "isIndependent": 0}}}` inside `dataSource` — the documented `standaloneFilter` shape was rejected live. `ms-saveReportInstance` saves in place; `ms-deleteReportInstance` discards.

Dashboard — built in memory around reports or cubes, or over existing datasets, then saved (not yet exercised):

```bash
$API call createDossierInstance_1 --body '{"objects": [{"id": "<reportId>", "type": 3}]}' --yes    # → {id, mid}
$API call createDraftDossierInstance --body '{"datasets": [{"id": "<datasetId>"}]}' --yes
$API call documentSaveAs -p id=<id> -p instanceId=<mid> --body '{"name": "<name>", "folderId": "<folderId>"}' --yes
```

- Save with the `id` the create call returned (the docs' sample shows all zeros). The layout is server-generated: adding, removing or rebinding visualizations is not in REST — use Workstation, or copy a template dashboard (`copyObject` with `type=55`).
- `updateDossierInstanceDatasets` (add or replace datasets) and `applyTheme` work on the instance before `documentSaveAs`.

### 7. Cubes: classify, publish or refresh, status, data

```bash
$API call getObject -p id=<cubeId> -p type=3          # 776 classic; 779 + extType 448 = Mosaic → build-mosaic-model; other 779 = data-import
$API call getDefinition_2 -p cubeId=<cubeId>          # attributes and metrics, no data query
$API call getCubes -p id=<cubeId>                     # size, status, path, modified; repeat -p id=
$API call publishCube_2 -p cubeId=<cubeId> --yes      # 202; a refresh is a republish
$API call getCubeById -p cubeId=<cubeId>              # HEAD → X-MSTR-CubeStatus bit vector in the printed headers
$API call createCubeInstance_1 -p cubeId=<cubeId> -p limit=100 --body '{}' --yes    # execute probe + first page
$API call getReport_1 -p cubeId=<cubeId> -p instanceId=<iid> -p offset=100 -p limit=100
$API call getCubeSqlView -p cubeId=<cubeId>
```

- A logout cancels a running publish: under a password or API-token sign-in, publish and wait in one session (`--reuse-session`, or one process); under a cached `sso` session the plain call is fine.
- Proof is the execute probe, not the 202: iServerCode `-2147072488` means not published, and after a republish `X-MSTR-CubeStatus` still describes the old cache.
- Create with `createCube` (`{"name", "folderId", "definition": {"availableObjects": {"attributes": […], "metrics": […]}}}`) or `ms-createCube` (Modeling body with `options.dataRefresh`), then publish. Large cubes can hit the project row governors (`-2147205488`; strategy-admin raises them).
- `createCubeInstance_1` also reads Mosaic models. `publishCube` (`POST /api/cubes/{id}`) is internal and deprecated — never alongside `publishCube_2`.

### 8. Datasets (Push Data)

```bash
$API call createDICube --body @dataset.json --yes        # one table: definition + data in one call
$API call updateDICube -p datasetId=<id> -p tableId=<table> -p updatePolicy=Upsert --body @table.json --yes   # Add|Update|Upsert|Replace
$API call getDatasetInfo -p datasetId=<id> -p fields=tables -p fields=columns
```

- `dataset.json`: `{"name", "folderId", "tables": [{"name", "columnHeaders": [{"name", "dataType": "STRING|INTEGER|BIGINTEGER|BOOL|DOUBLE|BIGDECIMAL|DATE|TIME|DATETIME"}], "data": "<base64 of a JSON array of row objects>"}], "attributes": [{"name", "attributeForms": [{"category": "ID", "expressions": [{"formula": "<table>.<column>"}]}]}], "metrics": [{"name", "expressions": [{"formula": "<table>.<column>"}]}]}`.
- Several tables or large data: `createTable` (definition only) → `pushApiV2CreateUploadSession` (`{"tables": [{"name", "updatePolicy": "REPLACE", "orientation": "ROW"}]}`) → `pushApiV2AddData` per chunk (`{"tableName", "index": 1, "data": "<base64 of row arrays>"}`, index from 1) → `pushApiV2Publish` → poll `pushApiV2GetPublishStatus`; `pushApiV2Cancel` discards an unpublished session.

### 9. Library publishing and content groups

```bash
$API call getPublishedObject -p id=<objectId>          # recipients: subtype 8704 user, 8705 group; [] if never published
$API call publishObject --body '{"id": "<objectId>", "recipients": [{"id": "<userOrGroupId>"}]}' --yes   # additive; "type": "report_definition" for reports
$API call modifyRecipient -p id=<objectId> -p userId=<recipientId> --yes      # remove one user or group
$API call getContentGroups
$API call getContentGroupContent -p id=<groupId>
```

- Inventory or replay many: `python3 skills/build-mosaic-model/scripts/strategy_library_publications.py export --project "<project>" --out mapping.csv`, then `replicate --mapping mapping.csv --target-project "<copy>"` (dry run unless `--apply`; additive, groups stay groups).
- Never `unpublishObject` (bare `DELETE /api/library/{id}`): it unpublishes for every recipient. `getLibrary` shows only the caller's own Library.

## Safety rules

- Never delete, overwrite or unpublish without explicit confirmation of the listed ids: `deleteObject`, `deleteFolder` (takes its contents), `unpublishObject`, `modifyRecipient`, `saveDocument`, `ms-saveReportInstance`, `"overwrite": true`, `updateCube`, Push Data `Replace` / `REPLACE`. Run workflow 2 first and show what depends on the target.
- Exports and instance results are live business data: write them with `--out` to a private directory outside the repo (`call` writes `0600`; large bodies go to a private temp file), keep rows out of chat, commits and notes, and delete the files when done.
- Prompts and filters must be explicit: answer every prompt with values the user chose, record them, and say whether a filter is runtime-only or saved. Answering a prompt with every element pulls the full data set.
- Certifying, publishing to Library or to a group reaches other people (groups include future members); confirm the audience first.
- Publishing a cube or dataset changes what every dashboard on it shows: count dependents first, and classify every cube-like object (779 + 448 is a Mosaic model → build-mosaic-model).

## Field notes

- `memory/reference_strategy_runtime_analytics.md` — instance flows, prompt grammar, PDF as base64 JSON and the `orientation` enum (verified 2026-08-27). Its internal (dashboard `answerPrompts`, whole-dashboard `/csv`, document `…/layouts/…/visualizations/…`) and deprecated (`…/promptsAnswers`) paths are marked there (2026-10-05).
- `memory/reference_strategy_legacy_semantic_admin.md` — verified recipes: report create + `saveAs` and the filter-reference shape, the progressive prompt loop on v2 instances (2026-08-26); classic cube create, publish, status and governors (2026-08-25).
- `memory/reference_strategy_report_dossier_creation.md`, `memory/reference_strategy_report_authoring_patterns.md` — what REST can author (corrected 2026-10-05: reports and in-memory dashboards yes, visualization CRUD no).
- `memory/reference_strategy_library_publications.md` — per-object recipients, additive replay, project duplication, the helper (verified 2026-09-28).
- `memory/reference_strategy_object_cloning.md` — copy vs clone-and-remap per family; object type numbers.
- `memory/reference_strategy_hyperintelligence.md` — `/api/hyper/*` (all internal in the spec), session-bound card instances.
- `memory/reference_mosaic_vs_legacy_surfaces.md`, `memory/reference_strategy_surface_matrix.md` ("Cubes and datasets") — cube families and classification. The matrix and `memory/reference_strategy_task_catalog.md` mark the internal dataset publish / refresh / status paths (`POST /api/datasets/{datasetId}`, `GET /api/datasets/cubes/{id}/status`, `…/instances/{instanceId}/refresh`) and the internal, deprecated `POST /api/cubes/{cubeId}` (2026-10-05).
- `memory/reference_strategy_admin_platform.md` ("Search, browse, lineage") — its bulk copy / move / delete under `/api/objects` is marked internal (2026-10-05).
- `memory/reference_strategy_validation_workflows.md` — live probes 2, 5, 6 and 7 (search, report / cube data, prompts, document PDF) run by `strategy_validate.py`.
- `memory/reference_strategy_automation_coverage.md` ("Proposed skills" #8, folded in here) and `memory/reference_strategy_task_catalog.md` — routing.
- Official: REST docs `common-workflows/analytics/` (object-discovery incl. data-lineage-analysis-via-rest-apis, use-prompts-objects, manage-reports, manage-dossiers, export-to-pdf, manage-datasets); mstrio-py `project_objects` (`Report`, `Dashboard`, `OlapCube`, `SuperCube`).

## Status

- **Spec-verified (2026-10-05):** every operationId, parameter, enum and body field above, against the tenant's 2026 spec; every `call` line passes the tool's request validation offline.
- **Live-exercised (recorded in notes):** quick search and object reads (2026-04-21); report and cube instance data and prompt discovery (2026-04-21) and the progressive prompt loop (2026-08-26); document instance → PDF (2026-04-21, 2026-08-27); `ms-postReport` + `saveAs` (2026-08-26); classic cube create, publish, `HEAD` status and execute probe (2026-08-25); Library export / replicate (2026-09-28); Hyper cards (2026-08-28); object copy (authoring-patterns note).
- **Not yet live:** metadata-search paging and lineage searches, folder create / delete, move / rename, certify on type 55, Excel / CSV exports, dashboard create + `documentSaveAs`, Push Data, content groups.
