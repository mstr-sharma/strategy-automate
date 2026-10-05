---
name: strategy-migration
description: Promote Strategy (formerly MicroStrategy) content between projects and environments and keep a way back — metadata packages (holder, content, .mmp download), package import with an undo package, migration records and migration groups (validate, approve, import, undo), project duplication in one environment or across two, and Mosaic model copies (saveAs), YAML export/restore and Git backup/restore. Use for "migrate objects", "promote dev to prod", "move this to production", "package", "export a package", "import package", "undo import", "roll back a migration", "validate a migration", "duplicate project", "copy a Mosaic model", "back up model to Git", "restore a model from YAML".
---

# Strategy migration and promotion

Every import here changes production metadata. Read first, hold a way back before the write (undo package, YAML export or Git commit), read back after. Sign-in and the `ops` / `describe` / `call` mechanics (dry runs, `--yes`, auto-filled headers): `skills/strategy-platform/SKILL.md`. Commands run from the repo root with `API="python3 skills/strategy-platform/scripts/strategy_api.py"`.

## Scope

Owns the spec tags **Packages, Migrations, Migration Groups, Project Duplications, Git Service** (`$API ops --tag strategy-migration`) and borrows three Modeling operations for Mosaic models: `ms-saveAsDataModel`, `ms-exportDataModel`, `ms-restoreDataModel`.

Route elsewhere:
- users, groups, security roles, privileges, settings, license, fences → `strategy-admin`
- reports, dashboards, cubes, folders, object copy/move inside one project, Shared File Store → `strategy-content`
- subscriptions, schedules → `strategy-distribution`
- building or editing a Mosaic model, and publish/certify after a copy → `build-mosaic-model` (plan with `strategy-data-modeling`)
- before/after proof of promoted content (Test Center, paired queries) → `strategy-validation`
- loading the target project, jobs, caches, sessions → `strategy-ops`

## How to work

1. Sign in to each Library you touch. Second environment: `$API --base <Library URL> call …` (`--base` goes before the subcommand). In bodies an environment is `{"id": "<Library URL>", "name": "<label>"}`; mstrio sends the URL with a trailing `/`.
2. `$API describe <operationId>` before every call. Body skeletons list up to 40 values of an enum.
3. Reads first: existing records (workflow 9), the objects and their dependents, both projects loaded (`strategy-ops`), source and target IDs written down.
4. Writes: dry run (no `--yes`), show it, get a yes, then `--yes`. Package, migration and duplication writes answer 201/202 and run asynchronously; poll the status read to a terminal state. A 202 is not success. `call` adds `Prefer: respond-async` (the dry run shows it) where the spec requires it (holder PUT/DELETE, imports, `triggerValidate`, `triggerImport*`); pass `-p Prefer=respond-async` where it is optional but documented (`createDuplication*`, undo PATCHes). Configuration packages must not carry a project: `--project ""` overrides `MSTR_PROJECT_ID`.
5. Read back status and content, hand the promoted objects to `strategy-validation`, then clean up holders, import processes and records you no longer need.

### Session-bound steps: keep one session

`strategy_api.py call` covers these steps directly — `--reuse-session` (or `MSTR_REUSE_SESSION=1`) keeps one session across calls so holders, imports and instances survive; `--file FIELD=PATH` / `--form NAME=VALUE` send multipart bodies; exports get the spec's `Accept` type automatically (override with `--accept`); changesets are opened in `--project`; dry runs show the auto-added `Prefer` / changeset headers. End a reused session with `strategy_auth.py logout`. The one-process frame below is the alternative.

A package holder and its import process live in your server session ("one package instance per user session", freed at logout). With a password or API-token sign-in and no `--reuse-session`, every `$API call` signs in and out, so the holder is gone before the next command. Without a reused session, chain the holder and import steps in one process that keeps the tool's validation:

```python
import json, os, sys, time
sys.path.insert(0, "skills/strategy-platform/scripts")
import strategy_auth as sa, strategy_api as A
base, P = os.environ["MSTR_BASE"].rstrip("/"), os.environ.get("MSTR_PROJECT_ID")  # P unset: configuration package
spec, s = A.load_spec(base), sa.SafeSession()
s.headers.update({"Accept": "application/json", **({"X-MSTR-ProjectID": P} if P else {})})
who = sa.sign_in(s, sa.AuthConfig.from_env(base=base))
def op(ref, *pairs, body=None):   # spec-checked; fills Prefer and Modeling changesets like `call`
    o = A.find_operation(spec, ref)
    r = A.call(o, A.build_request(o, list(pairs), body, P), base=base, session=s)["response"]
    if not r.ok: raise SystemExit(f"{o.key()}: HTTP {r.status_code} {r.text[:300]}")
    return r
def wait(ref, *pairs, done=("ready", "failed")):   # poll a top-level "status"
    for _ in range(240):
        st = op(ref, *pairs).json()
        if str(st.get("status", "")).lower() in done: return st
        time.sleep(5)
    raise SystemExit(f"{ref}: still {st.get('status')} after 20 minutes")
def binary(path, out):            # package, undo and backup downloads
    r = s.get(base + path, headers={"Accept": "application/octet-stream"}); r.raise_for_status()
    open(out, "wb").write(r.content)
try:
    pass                          # workflow steps go here
finally:
    sa.sign_out(s, base, who)     # leaves a shared browser session open: delete holders explicitly
```

## Workflows

### 1. Export a package (source, one process)

```python
pkg = op("createEmptyPackage").json()["id"]
op("updatePackagePerSpec", f"packageId={pkg}", body={             # 202
    "type": "project",           # project | project_security (users, groups) | configuration (P unset)
    "settings": {"defaultAction": "replace", "aclOnReplacingObjects": "use_existing", "aclOnNewObjects": ["keep_acl_as_source_object"]},
    "content": [{"id": "<objectId>", "type": 3, "action": "replace", "includeDependents": True}]})
pk = wait("get_1", f"packageId={pkg}", "showContent=true")       # review pk["content"]: dependents pulled in
binary(f"/api/packages/{pkg}/binary", "change.mmp")
op("deletePackageAsync", f"packageId={pkg}")
```
Conflict actions: `use_existing | replace | keep_both | use_newer | use_older | force_replace | delete`. `updateSchema` (project packages) recalculates table and schema info. `content[].parentId` puts an object in another target folder (Intelligence Server 11.6.0900+, not configuration packages). Privilege: Create Package.

### 2. Import a package with an undo package (target, one process)

```python
pkg = op("createEmptyPackage").json()["id"]
with open("change.mmp", "rb") as f:                                  # multipart (CLI: call … --file file=change.mmp)
    s.put(f"{base}/api/packages/{pkg}/binary", files={"file": f}).raise_for_status()
pk = wait("get_1", f"packageId={pkg}", "showContent=true")
print(json.dumps(pk.get("settings")), [(c.get("name"), c.get("action")) for c in pk.get("content", [])])
if os.environ.get("APPLY") != "1": raise SystemExit("review the actions above; rerun with APPLY=1 to import")
imp = op("create_2", f"packageId={pkg}", "generateUndo=true").json()["id"]
st = wait("retrieve_2", f"importId={imp}", done=("imported", "failed"))
if st.get("undoPackageCreated"): binary(f"/api/packages/imports/{imp}/undoPackage/binary", f"undo-{imp}.mmp")
op("delete_3", f"importId={imp}"); op("deletePackageAsync", f"packageId={pkg}")
```
Roll back by importing `undo-<importId>.mmp` the same way with `generateUndo=false`. Privileges: Create Package, Import Package.

### 3. Promote with a migration record (Storage Service, source → target)

Migration records persist in the Storage Service, so separate `call`s are fine. Both sides need Create package, Apply package and Bypass all objects security check, plus a package storage location configured in Workstation.
```bash
SRC="<source Library URL>" TGT="<target Library URL>"     # e.g. https://<tenant>/MicroStrategyLibrary
$API --base $SRC call createMigration --project <srcProjectId> --body @migration.json   # dry run; then --yes → {id}
$API --base $SRC call getMigration -p migrationId=<mid>                                  # packageInfo.status → created
$API --base $SRC call updateMigration_1 -p migrationId=<mid> --body @request.json --yes   # importRequestStatus "requested"
$API --base $SRC call updateMigration_1 -p migrationId=<mid> --body '{"importInfo":{"importRequestStatus":"approved"}}' --yes
$API --base $SRC call getMigration -p migrationId=<mid> -p showContent=all --out mig.json  # set packageInfo.replicated = true
$API --base $TGT call triggerImport_1 -p migrationId=<mid> -p generateUndo=true --project <tgtProjectId> --body @mig.json   # dry run; then --yes
$API --base $TGT call getMigration -p migrationId=<mid>                                  # importInfo.status → imported | import_failed
```
`migration.json`: `packageInfo` {`type`, `name`, `environment` (source), `tocView` {`settings`, `content`} as in workflow 1, `treeView: {}`} and `importInfo` {`environment` (target), `project` {`id`, `name`}}. `request.json`: `{"importInfo": {"environment": {…target…}, "project": {…}, "importRequestStatus": "requested"}}`. After approval the package is `locked`; the import only runs while it is locked and approved.

Undo, on the target, from `imported`, `import_failed` or `undo_failed`:
```bash
$API --base $TGT call updateMigration_1 -p migrationId=<mid> -p Prefer=respond-async --project <tgtProjectId> --body '{"importInfo":{"undoRequestStatus":"requested"}}' --yes
$API --base $TGT call updateMigration_1 -p migrationId=<mid> -p Prefer=respond-async --project <tgtProjectId> --body '{"importInfo":{"undoRequestStatus":"approved"}}' --yes
$API --base $TGT call getMigration -p migrationId=<mid>                                  # undoing → undo_success | undo_failed
```
Files, with `binary()`: package `/api/migrations/packages/{packageId}/binary` (`downloadPackageBinary`); undo package `/api/migrations/imports/{importId}/binary` (`downloadUndoPackageBinary`, `importInfo.id`).

### 4. Validate before importing (writes no metadata)

Point the record at the target first (`request.json` without `importRequestStatus`); package status must be `created`.
```bash
$API --base $SRC call getMigration -p migrationId=<mid> -p showContent=all --out mig.json
$API --base $TGT call triggerValidate -p migrationId=<mid> --project <tgtProjectId> --body @mig.json --yes   # 202
$API --base $SRC call updateMigration_1 -p migrationId=<mid> --body '{"validation":{"status":"validating"}}' --yes
$API --base $SRC call getMigration -p migrationId=<mid>     # validation.status → validated | validation_failed (+ message)
```
Administrator on both sides; the two clocks within 5 minutes of each other.

### 5. Migration groups (configuration plus several projects)

```bash
$API --base $SRC call createMigrationGroup --body @group.json   # name, sourceEnvironment, targetEnvironment, treeView {}, migrations[]
$API --base $SRC call getMigrationGroup -p migrationGroupId=<gid>   # every migrations[].packageInfo.status → created
$API --base $SRC call updateMigration -p migrationGroupId=<gid> --body '{"importRequestStatus":"requested"}' --yes   # then "approved"
$API --base $SRC call getMigrationGroup -p migrationGroupId=<gid> -p showContent=all --out group.json   # every replicated = true
$API --base $TGT call triggerImport -p migrationGroupId=<gid> -p generateUndo=true --body @group.json   # dry run, --yes; poll migrations[].importInfo.status
```
Configuration package first, at most one package per project, 100 per group; one failure fails the group. Undo on the target: `updateMigration` with `{"undoRequestStatus": "requested"}`, then `"approved"`. The docs send `generateUndo` as a header; the spec has a query parameter, which is what `-p` sends.

### 6. Duplicate a project

```bash
$API call createDuplication --project <srcProjectId> -p Prefer=respond-async --body @dup.json   # dry run; then --yes → {id}
$API call getProjectDuplication -p id=<dupId>       # exporting → exported → importing → completed | export_failed | import_failed
$API call cancelDuplication -p id=<dupId> --body '{"status":"cancelled"}' --yes   # only while exporting, exported or importing
```
```json
{"source": {"environment": {"id": "{base}", "name": "<env>"}, "project": {"id": "<srcProjectId>", "name": "<source>"}},
 "target": {"environment": {"id": "{base}", "name": "<env>"}, "project": {"name": "<new project>"}},
 "settings": {"export": {"projectObjectsPreference": {"schemaObjectsOnly": false}, "subscriptionPreferences": {"includeUserSubscriptions": false}},
              "import": {"locales": [1033], "defaultLocale": 1033}}}
```
Same environment: identical `environment.id` on both sides and the same metadata database type. Across environments: different ids; check compatibility first (`getProjectDuplicationVersions` on the source, its `{apiVersion, dataVersion}` to `validateProjectDuplication` on the target), POST on the source, then `$API --base $TGT call createDuplicationOnTarget -p id=<dupId> -p Prefer=respond-async --body @dup.json --yes`; poll either side (`export_syncing`, `import_syncing`). Offline route: once `exported`, `binary("/api/projectDuplications/<dupId>/backup", "project.projdup")`, then on the target `s.post(f"{base}/api/projectDuplications/restoration", headers={"Prefer": "respond-async"}, files={"file": open("project.projdup", "rb")}, data={"metadata": json.dumps({"target": …, "settings": {"import": …}})})` in one process. Needs the Duplicate Project and Bypass All Access Checks privileges; does not work with user fencing on.

### 7. Copy a Mosaic model (saveAs, one process)

```python
MID = "<dataModelId>"                                       # also used by workflow 8
new_id = op("ms-saveAsDataModel", f"dataModelId={MID}", body={"name": "<new name>", "destinationFolderId": "<folderId>"}).json()["objectId"]
```
Copies tables, attributes, metrics, hierarchy, security filters and folders under new IDs; the changeset is opened and committed for you. Read on the source (Control when it has security filters), Write on a destination folder you own (a shared source folder may not be writable); a same-named model in that folder is an error. Publish and certify the copy with `build-mosaic-model`.

### 8. Back up and restore a Mosaic model (YAML, Git)

```python
cs = op("ms-createChangeset").json()["id"]                 # plain (non-schemaEdit) changeset
y = s.post(f"{base}/api/model/dataModels/{MID}/export", headers={"X-MSTR-MS-Changeset": cs, "Accept": "application/yaml"})
y.raise_for_status(); open(f"{MID}.yaml", "w").write(y.text); op("ms-deleteChangeset", f"changesetId={cs}")
# restore an existing model to that state (Control on every object; 10 MB default limit)
cs = op("ms-createChangeset").json()["id"]
with open(f"{MID}.yaml", "rb") as f:
    r = s.post(f"{base}/api/model/dataModels/{MID}/restore", headers={"X-MSTR-MS-Changeset": cs}, files={"dataModelFile": f})
op("ms-commitChangeset" if r.ok else "ms-deleteChangeset", f"changesetId={cs}")
```
YAML restores an existing model only; it cannot create one. An unchanged fingerprint makes the restore a no-op. Git needs the environment's Git integration (Library → Account Settings → Git Integrations; GitHub only, one per environment) and the Use Git Integration privilege (Read to save, Write to restore). The spec has no operation that lists integrations: take `gitIntegrationId` from that setup or from the request the Library sends on "Save to Git".
```bash
$API call backupObjects -p gitIntegrationId=<gitId> --body '{"objects":[{"projectId":"<pid>","objectId":"<modelId>","objectType":3,"comment":"before promotion"}]}' --yes
$API call getObjectsHistory -p gitIntegrationId=<gitId> --body '{"objects":[{"projectId":"<pid>","objectId":"<modelId>","perPage":20}]}' --yes   # a POST read
$API call restoreObjects -p gitIntegrationId=<gitId> --body '{"objects":[{"projectId":"<pid>","objectId":"<modelId>","objectType":3,"commitId":"<commitId>"}]}' --yes
```
A 207 is a partial success: check every `results[].code`. `restoreObjects` takes an optional changeset header; `call` does not open one for it.

### 9. Housekeeping

```bash
$API call getMigrationList -p limit=100 -p packageInfo.purpose=object_migration
$API call getMigrationGroupList -p limit=100
$API call getProjectDuplications -p limit=50
$API call deletePackage_1 -p packageId=<packageId> --yes        # package, records and undo packages; source, then target
$API call deletePackage -p packageGroupId=<groupId> --yes       # a group (packageInfo.groupId); source, then target
$API call cleanUp -p autoSync=packageInfo.existing --yes         # resync records with the storage file list
$API call deleteDuplication -p id=<dupId> --yes
```

## Safety rules

- Imports, undos, project-duplication imports and model restores change production metadata. Before sending: list the objects with their actions and dependents, name the target environment and project, show the dry run, get an explicit yes for that environment, and hold the way back: the undo package downloaded, or a YAML export or Git backup of every Mosaic model the import replaces.
- Undo is unavailable when any rule is `keep_both`, and a package containing Mosaic schema (`packageInfo.containsExtensionObject: true`) refuses reversal and rollback download. Back those models up with YAML or Git first.
- Name `force_replace` and `delete` actions explicitly before sending; they overwrite or remove target objects whatever their version.
- Validate (workflow 4) before any production import.
- Configuration and project-security packages move server-level objects, users and groups; confirm that scope with the environment administrator.
- `deletePackage` / `deletePackage_1` delete the undo packages too. Only after the user accepts the promoted result.
- Packages only move forward (older platform → newer), up to 2 GB, one create or import per session at a time.
- `transformMigration` and `transformMigrationGroup` are internal (the tool flags them); don't build on them.
- Package files, IDs and hostnames never go into the repo; `captures/` stays local.

## Field notes

- `memory/reference_strategy_package_migration.md` — stub with routing (never skip validate; duplicate Mosaic models across projects with packages, not `/api/objects/{id}/copy`). Corrected against the spec on 2026-10-05: `POST /api/migrations/{id}/validate|import|undo` and `POST /api/packages/{id}/import?projectId=` do not exist. The spec has `PUT …/validation`, `PUT /api/migrations/{id}` (import), `PATCH /api/migrations/{id}` (approve, undo) and `POST /api/packages/imports?packageId=`, and `POST /api/packages` only creates an empty holder.
- `memory/reference_strategy_admin_platform.md` — package types and the project header (configuration packages omit it); `keep_both` blocks undo.
- `memory/reference_mosaic_yaml_osi_dbt_interop.md` — YAML export (changeset plus `Accept: application/yaml`, JSON otherwise), restore-only semantics, Git, OSI (internal).
- `memory/reference_strategy_object_cloning.md` — saveAs is the native Mosaic copy; clone-and-remap only when the copy must change the definition.
- `memory/reference_strategy_project_loading.md`, `memory/reference_strategy_environment_probe.md` — probe the target project and the session cap before importing. Both were corrected on 2026-10-05: their old load calls (`POST /api/projects/{id}?action=load`, `POST /api/admin/projects/{id}`, `POST /api/monitors/projects/{id}/nodes/{node}/activate`) and `DELETE /api/auth/login` are not in the spec. Load and unload live in `strategy-ops`; logout is `POST /api/auth/logout`.
- `memory/feedback_build_mosaic_session_leak.md` — per-project session cap; each `$API call` is one sign-in unless you pass `--reuse-session`.
- `memory/reference_strategy_automation_coverage.md` — "Proposed skills" #2 is this skill.

## Status (2026-10-05)

- **Spec-verified** offline: every operationId and parameter above passed `strategy_api.py`'s own request validation against the tenant spec.
- **Live-exercised:** Mosaic YAML export (`ms-exportDataModel`, recorded 2026-08 in the YAML note). `ms-saveAsDataModel` has also been run once (into a folder the user owned) but has no repo note yet. Nothing else here has a recorded live run, so treat the first run on a tenant as a probe and write the result into `reference_strategy_package_migration.md`.
- **Unverified mechanics:** holder and import session scoping come from the docs (use `--reuse-session`). Migration ids look like `<packageId>:<importId>` and `call` percent-encodes the colon. There is no list operation for Git integrations.
