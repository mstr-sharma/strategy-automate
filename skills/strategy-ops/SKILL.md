---
name: strategy-ops
description: Run and watch a Strategy (formerly MicroStrategy) environment through the REST API — v2 job monitor (what is running, its SQL, cancel), user and database connections (who is connected, disconnect sessions, clear the per-project session cap), cube and content caches per cluster node (unload, invalidate, delete, purge object/element caches), project status and load/unload/idle per node, telemetry (service status, usage insights, performance, Mosaic SQL query profiles), change journal search and purge, and server-side Python scripts, tasks and flows. Use for "monitor jobs", "cancel a job", "what is running", "cache", "purge cache", "who is connected", "disconnect sessions", "session cap", "project status / load project", "unload project", "telemetry", "usage", "query profile", "change journal", "who changed this", "run a server script", "task", "trigger a task".
---

# Strategy operations and monitoring

Reads here are cheap; most writes hit everyone on a node. Act on the requesting user's own jobs and sessions unless told otherwise, and ask before purging, unloading or disconnecting on a shared environment. Sign-in and the `ops` / `describe` / `call` mechanics (dry runs, `--yes`): `skills/strategy-platform/SKILL.md`. Commands run from the repo root with `API="python3 skills/strategy-platform/scripts/strategy_api.py"`.

## Scope

Owns the spec tags **Monitors, Telemetry, Change Journal, Scripts, Tasks, Flows**, plus the internal-only **Performance Statistics, HangDetector, Workflows, Insight Engine** (`$API ops --tag strategy-ops [--internal]`).

Route elsewhere:
- users, groups, security roles, privileges, settings, license audit and compliance, fences → `strategy-admin`
- report, dashboard and cube definitions, cube refresh, object search → `strategy-content`; Mosaic publish → `build-mosaic-model` (`memory/reference_mosaic_publish_path.md`)
- subscriptions and schedules (a task runs on a schedule object) → `strategy-distribution`
- packages, migrations, project duplication → `strategy-migration`
- Test Center comparisons and numeric validation → `strategy-validation`

## How to work

1. Sign in, then check what you may see: `$API call getClusterNodes`. With Use Cluster Monitor it returns full node detail; with only a user-connection, cache, cube or job monitor privilege, node names; with none, 403.
2. Job, cache and DB-connection monitors work per node: take `nodes[].name` from `getClusterNodes` and loop.
3. Who am I: `$API call sessionSessionIdUserInfoGet` gives `id` and `fullName`. The job monitor filters on full name (`user`); the connection monitor on login (`username`) or full name (`name`).
4. `$API describe <operationId>` before each call; reads first; writes as a dry run, then `--yes` after the user agrees; read back (the job is gone, the cache state changed, the project reached `loaded`).
5. Many writes answer 202 (cube cache changes, project status, change journal purge): poll until done.
6. Every `$API call` is its own sign-in unless you pass `--reuse-session` (`MSTR_REUSE_SESSION=1`) or use a cached `sso` session, and project operations open a project session (`memory/feedback_build_mosaic_session_leak.md`). Use a reused session for polling loops and end it with `strategy_auth.py logout`.

## Workflows

### 1. Jobs: what is running, cancel one

```bash
$API call getJobs_1 -p nodeName=<node> -p user="<full name>" -p sortBy=-elapsedTime   # also status, type, objectType, projectName, elapsedTime=gt:<ms>
$API call getJob -p id=<jobId>              # sql, templateName, filterName, stepStatistics, errorMessage
$API call getJobQueries -p id=<jobId>       # queries consuming a realtime job
$API call deleteJob_1 -p id=<jobId>         # dry run; then --yes → 204; list again to confirm
$API call bulkDeleteJobs_1 --body '{"jobIds":["<id1>","<id2>"]}'   # dry run; then --yes; 207 = partial
```
Repeat a filter for several values (`-p status=executing -p status=waiting`). `sql` is present only while the job runs. The v1 `getJobs`, `deleteJob` and `bulkDeleteJobs` are deprecated. Privilege: Use Job Monitor.

### 2. Connections: who is connected, disconnect sessions

```bash
$API call getUserConnections -p clusterNode=<node> -p username=<login> -p limit=1000   # or name=<full name>, projectId=, idleTime=gt:1800 (seconds)
$API call deleteUserConnection -p id=<connectionId>                  # dry run; then --yes → 204
$API call getUserConnectionsAggregatedUsages -p clusterNode=<node>
$API call getMultipleDataBaseConnection -p clusterNodes=<node1>,<node2>   # warehouse connection monitor
$API call getDisConnectDataBaseConnection -p instanceId=<id>              # dry run; then --yes
```
Your own stale sessions (cap error `8004cb0a` / -2147072486): `python3 skills/build-mosaic-model/scripts/build_mosaic.py kill-sessions [--project <name|id>] [--idle-minutes 5]` lists them, and `--yes` disconnects them. A connection takes its open jobs with it, publishes included, so check `openJobsCount` first. The internal `bulkDeleteUserConnectionOnSpecificClusterNode` (`deleteAll=true`) is off limits.

### 3. Cube caches

```bash
$API call getAllCubeCaches -p clusterNode=<node> -p projectIds=<pid> -p limit=1000   # match a cube or Mosaic model on source.id
$API call getSingleCubeProperties -p id=<cacheId>    # state, size, rowCount, jobExecutionStatistics (passes, sqlStatement)
$API call alterCubeAction -p id=<cacheId> --body '{"state":{"loadedState":"unloaded"}}'   # or {"state":{"active":false}}; dry run, --yes → 202 {manipulationId}
$API call getManipulationStatus -p id=<manipulationId>   # executing → ready | error
$API call deleteCubeCache -p id=<cacheId>                # dry run; then --yes → 204
$API call getCubeCacheAggregatedUsages -p clusterNode=<node> -p aggregateBy=project
```
A cache id is base64 of `<cacheId>:<projectId>:<node>` (pad to a multiple of 4 to decode). Deleting a cube cache drops the published data until the next publish, and an in-memory Mosaic model stops answering. Republishing is not done here (see Scope).

### 4. Content caches, object and element caches

```bash
$API call getAllCaches -p clusterNode=<node> -p projectId=<pid> -p type=report -p limit=1000   # also status, owner, contentName, lastHitTime=lt:<ISO Z>
$API call alterContentCache_1 -p clusterNode=<node> --body '{"operationList":[{"op":"replace","path":"/contentCaches/<combinedId>/status/invalid","value":true}]}'   # dry run; then --yes → 202
$API call getReportCaches -p id=<reportId> -p projectId=<pid>   # one object; deleteReportCaches, getDocumentCaches, deleteDocumentCaches take the same
$API call deleteCache -p projectId=<pid> -p cacheType=object   # purge element | object | report | all for a project
```
`alterContentCache_1` paths: `/status/invalid` true = invalidate, `/status/loaded` true or false = load or unload, `{"op": "remove", "path": "/contentCaches/<combinedId>", "value": null}` = delete. `combinedId` is base64 of `<cacheId>:<contentType>:<projectId>`; mstrio reads it from the list as `combinedId`, which the spec schema does not show, so look at a live list first. The v1 `alterContentCache` is deprecated. `deleteCache` needs Cache Administration.

### 5. Projects: status, load, unload, idle

```bash
$API call getProjects -p limit=-1                                  # every project in metadata
$API call getProjectStatusOnAllNodes -p projectId=<pid>            # nodes[].projectStatus
$API call getProjectStatusFromNode -p nodeName=<node> -p projectId=<pid>
$API call updateProjectStatus -p nodeName=<node> -p projectId=<pid> --body '{"operationList":[{"op":"replace","path":"/status","value":"loaded"}]}'   # one node; dry run, --yes → 202
$API call updateProjectStatusOnAllNodes -p projectId=<pid> --body '{"status":"loaded"}'   # every node; dry run, --yes → 202
```
Statuses: `loaded`, `unloaded`, `exec_idle`, `request_idle`, `full_idle`, `wh_exec_idle`, `partial_idle`, plus `*_pending`. Unloading waits for sessions to close; `-p deleteSessions=true` ends them at once, so only with the user's explicit yes. Privileges: Load and Unload Project, Idle and Resume Project. A 404 with iServerCode -2147209151 on any project call means the project is not loaded on any node.

### 6. Telemetry: health, usage, performance, query profiles

```bash
$API call "GET /api/telemetry/status"     # operationId getStatus is duplicated in the spec: use verb + path
$API call getProcessingStatus             # 400 = the Platform Analytics consumer is not running
$API call getModelUsage -p startTime=<epoch ms> -p endTime=<epoch ms> -p limit=100   # also getObjectUsage, getSourceUsage
$API call getDataModelExecutionDrilldown -p modelId=<modelId> -p startTime=<epoch ms> -p limit=100   # …/users: getDataModelUserDrilldown
$API call getUserStatistics -p id=<userId>
$API call getUnusedObjects -p inactiveDays=90 -p limit=100
$API call getPerformance -p startTime=<epoch ms> -p limit=100 -p sortBy=-requestTime
$API call getAudit -p limit=100
$API call getAlerts -p limit=100
$API call getQueryProfile -p trinoQueryId=<queryId>     # SQL client's query id: fragmentStats, documents[].instanceId, templateIds
$API call getQueryProfileSourceBreakdown_1 -p trinoFragmentId=<fragmentId> -p instanceId=<instanceId>   # jobs[].passes[].sqlQuery
```
Times are epoch milliseconds. Filter with repeatable `columnsFilter=<columnId>:<value>` or `globalSearchTerm`; distinct column values come from the `…/elementList` operations (`$API ops --tag Telemetry --search elementList`). With a template id use `getQueryProfileSourceBreakdown`. Only successful SQL queries have a profile. Usage insights answered 404 on one tenant, so check the service status first. Telemetry admin writes (`startRestore`, `updateRuntimeConfig`, `enableMultitenantMetadata`, `deleteSentinelPerfData`, `putAlertActions`, sentinel replays) change the platform: only on an explicit request.

### 7. Change journal: who changed what, purge

```bash
$API call createChangeJournalSearch_1 --body '{"affectedProjects":["<pid>"],"changeTypes":["change_object","delete_object"],"objectNames":["<name>"]}' --yes   # → {searchId}
$API call getChangeJournalRowSearchResult -p searchId=<searchId> -p limit=100 -p offset=0   # user, transaction, changedObject, timestampISO
$API call deleteChangeJournalSearchResult -p projects.id=<pid> -p timestamp="01/01/2026 12:00:00 AM" -p comment="<reason>"   # purge older entries: dry run first
```
The search is a POST, so even this read needs `--yes`. Other filters: `users`, `affectedObjects` (`[{id, type}]`), `objectTypes`, `transactionSources`, `beginTime`, `endTime`. Needs Monitor Change Journal. A purge deletes audit history for good; `purgeAllProjects=true` only on an explicit request.

### 8. Server-side Python scripts, tasks and flows

```bash
$API call doQuickSearch -p type=76 -p name=<name> --project <pid>   # find scripts (type 76); search belongs to strategy-content
$API call getCommandManagerScript -p id=<scriptId> --project <pid>  # read the code and its variables first
$API call getScriptVariablesAnswer -p id=<scriptId> --project <pid>
$API call evaluateCommandManagerScriptWithId -p id=<scriptId> --project <pid> --body @vars.json   # dry run; then --yes → 202 {id}
$API call getCommandManagerScriptEvaluationStatus -p evaluationId=<evalId> --project <pid>        # status, results.stdout / stderr
$API call cancelCommandManagerScriptEvaluation -p evaluationId=<evalId> --project <pid>           # dry run; then --yes
$API call getScriptHistory -p scriptids=<id1>,<id2> --project <pid>       # last run per script
$API call getScriptEvaluationHistory -p scriptId=<scriptId> -p limit=20   # your saved-script runs
$API call getScriptEvaluationLog -p id=<scriptId> -p evaluationId=<evalId> --project <pid>   # ids: getScriptEvaluationIds -p id=<scriptId>
$API call queryTasks -p type=script -p allProjects=true -p limit=-1      # a task = script or workflow on a schedule
$API call triggerTask -p id=<taskId> -p scheduleId=<scheduleId>         # dry run; then --yes → 202; activateTask / deactivateTask take the same
$API call listFlows -p flowCreationId=<evaluationId>                    # status of a Flow started by createFlow
```
`vars.json` is `{"variables": [{"id": "<varId>", "value": "<value>"}]}`; mark secret values with `"secretValueInput": true` and keep them in the file, never on the command line. Needs Use Python Script. The freehand `evaluateCommandManagerScript` (base64 code, no saved object) runs anything: avoid unless asked. Reading a finished Flow marks it delivered, and it drops out of later lists.

### 9. Internal monitors and admin pointers

Internal, so the tool flags them and they are not public contract: `getHangDetectorStatus` / `postHangDetectorStatus`, `changeStatsMode` (`PUT /api/stats`), `getServerBusyIndicator`, `restartServer` (`PUT /api/monitors/libraryServer/status` restarts the Library cluster), Insight Engine (`/api/insight/{path}`), workflow files and flow conversion. Read-only probes such as `$API call getHangDetectorStatus` are fine; writes only on an explicit request. Cluster membership (`addServerClusterMember`, `removeServerClusterMember`) is public but an administrator change. License audit (`checkLicenseAudit` → `checkLicenseAuditResult`), compliance (`checkLicenseCompliance` → `checkComplianceResult`), license history and fences (`getFences_1`) belong to `strategy-admin`.

## Safety rules

- Cancelling jobs, disconnecting sessions and unloading projects affect other people. Default to the requesting user's own jobs (`user=<full name>`) and connections (`username=<login>`). For anyone else's, list them and get an explicit yes that names the jobs or users.
- Never purge or delete caches (`deleteCache`, `deleteCubeCache`, `alterContentCache_1` remove or invalidate, `deleteReportCaches`, `deleteDocumentCaches`), unload or idle a project, or pass `deleteSessions=true` on a shared environment without asking. Each one costs every user a cold start or a dropped session. Use the narrowest scope: one report, one cube, one node.
- Disconnecting a connection cancels its running jobs, publishes included (publish jobs are session-bound).
- A change journal purge or a telemetry delete loses audit history for good: only on an explicit request, with a comment.
- Scripts and tasks run code and deliveries with their owner's rights. Read them first, run them only on request, and keep secrets off the command line.
- Internal and deprecated operations are flagged by the tool; prefer the v2 job and content-cache operations.
- Node names, hosts and IDs stay out of the repo.

## Field notes

- `memory/reference_strategy_monitoring_jobs_alerts.md` — job records carry SQL while running (Monitor Jobs privilege, else ERR014 -2147213784); cube cache `jobExecutionStatistics`. Rewritten against the spec on 2026-10-05: its old `GET /api/monitors/caches`, `POST /api/monitors/caches/{id}?action=…`, `GET /api/monitors/sessions`, `POST /api/alerts`, `GET /api/alerts/{id}/history` and `POST /api/cubes/{id}/refresh` are not in the spec, and `GET` / `DELETE /api/monitors/jobs` are deprecated in favour of `getJobs_1` / `deleteJob_1`.
- `memory/reference_strategy_sql_visibility.md` — query profile to per-pass engine SQL (verified 2026-10-01), cube cache monitor SQL, `sqlView` surfaces.
- `memory/reference_strategy_project_loading.md` — unloaded projects (-2147209151) and the session cap. Corrected 2026-10-05: its old `POST /api/admin/projects/{id}`, `POST /api/monitors/projects/{id}/nodes/{node}/activate`, `DELETE /api/sessions/{sessionId}` and `DELETE /api/auth/login` are not in the spec — use workflow 5, `deleteUserConnection` and `POST /api/auth/logout`.
- `memory/reference_strategy_environment_probe.md` — preflight order before heavy automation. Corrected 2026-10-05: the old `POST /api/projects/{id}?action=load` (not in the spec) is gone, and the publish-job check uses `getJobs_1 -p objectType=cube` (the deprecated v1 has no publish job type).
- `memory/reference_strategy_admin_platform.md` — overview of the monitor families. Its purge path was corrected to the spec's `/caches/` (2026-10-05), which is what `deleteCache` sends.
- `memory/feedback_build_mosaic_session_leak.md` — the `8004cb0a` session cap, `kill-sessions`, logout is `POST /api/auth/logout`.
- `memory/reference_mosaic_publish_path.md` — the cube cache monitor as publish-completion evidence; decoding cache ids.
- `memory/reference_mosaic_ai_service.md` — usage insights answered 404 on one tenant.
- `memory/reference_strategy_automation_coverage.md` — "Proposed skills" #6 (operations monitoring) and #9 (server-side Python) both land here.

## Status (2026-10-05)

- **Spec-verified** offline: every operationId and parameter above passed `strategy_api.py`'s own request validation against the tenant spec.
- **Live-exercised** (recorded in notes): cube cache list and detail (`getAllCubeCaches`, `getSingleCubeProperties`) and query profiles (`getQueryProfile`, `getQueryProfileSourceBreakdown[_1]`), 2026-10-01. The deprecated v1 job list answered ERR014 without Monitor Jobs. The `kill-sessions` connection calls need a monitoring privilege most operator accounts lack. Everything else (v2 jobs, cancels, connections, content caches, project load/unload, change journal, scripts, tasks) is spec-only: treat the first run as a probe and record it in `reference_strategy_monitoring_jobs_alerts.md`.
- **Open:** the spec's `GET /api/sessions/userInfo` has no `username` (`kill-sessions` reads one, so check its match on a live run); the content-cache `combinedId` is not in the spec's list schema; the change journal `beginTime` / `endTime` format is undocumented.
