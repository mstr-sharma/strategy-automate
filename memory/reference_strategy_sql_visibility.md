---
name: Seeing the SQL the Strategy engine generates
description: Verified 2026-10-01 — every API surface that exposes engine-generated SQL (Mosaic SQL/Trino query-profile telemetry + EXPLAIN plan, cube/report/dashboard SQL views, dashboard query details, cube-cache job statistics, job monitor), which object type / serve mode each works for, the privileges involved, and the end-to-end trace recipe for "flat-table SQL in, multi-pass cross-store SQL out".
type: reference
---

## The question this answers

A consumer writes plain SQL against a Mosaic model as if it were one flat table (Trino endpoint, MCP `query`, or
REST cube instance). Behind it the Strategy engine resolves attributes, metrics, joins, security filters and serve modes
into one or more passes against one or more data sources. These are the surfaces that let you see that generated SQL.

## Surface matrix

| Surface | Call | Returns | Works for | Status 2026-10-01 |
| --- | --- | --- | --- | --- |
| **Mosaic SQL plan (before running)** | `EXPLAIN <your sql>` on the Trino endpoint (`catalog=sql`, `schema=<project name lowercased>`) | The Strategy *template* built from your SQL (units, metrics, group-by, filter, sort, limit, template JSON) + a **"Strategy Plan Optimization Flow"** block: leaf cube sources with `dataServeMode` and DB roles, JOIN_OFFLOAD / DIRECT_QUERY applicability with reasons, workflow summary (`fully-pushdown (engine)` etc.) | every Mosaic model | verified (in_memory, connect_live, linked multi-source) |
| **Mosaic SQL actual passes (after running)** | `GET /api/telemetry/performance/queryProfile/{trinoQueryId}` then `GET /api/telemetry/performance/queryProfile/{trinoFragmentId}/sourceBreakdown/{instanceId}[/{templateId}]` | profile: `queryStats.sqlQuery` (your SQL), `fragmentStats[]` (`pushdownType` FULL/PARTIAL, `pushdownDisabledReason`, `parentJobId`, `isLinkedModelStat`), `documents[]` (`instanceId`, `templateIds`, `jobIds`, `serveModes` 1=in-memory / 2=live, objects). breakdown: `jobs[].passes[]` with `sqlQuery`, `sqlType`, `executionTimeMs`, `fetchTimeMs`, `outputRows` | every Mosaic model; only successful queries (failed query → 500 "No query stats found") | verified on all three serve shapes |
| **Published cube / in_memory model load SQL** | `GET /api/v2/cubes/{id}/sqlView` → `{sqlStatement}` (mstrio: `OlapCube.export_sql_view()`) | one block per table, each headed `[DB Instance: <name>]`, the SQL the publish job ran | in_memory models, classic cubes | verified; **400 DE93362 "Live Intelligent Cubes cannot be published"** on connect_live models |
| **Cube publish job statistics** | `GET /api/monitors/caches/cubes?clusterNode=<node>&projectIds=<id>` → match `source.id` → `GET /api/monitors/caches/cubes/{cacheId}` | `jobExecutionStatistics`: `sqlPassesCount`, durations, `dbInstanceNames`, `accessedTables[]`, `queryPasseInfos[].sqlStatement` (+ rows, duration per pass) | published cubes only | verified |
| **Classic report / transient report over a model** | `POST /api/v2/reports/{id}/instances` → `GET /api/v2/reports/{id}/instances/{instanceId}/sqlView`; for an ad-hoc request over a Mosaic model, `POST /api/model/reports` (sourceType cube) → `POST /api/model/reports/{id}/instances` (`X-MSTR-MS-Instance`) → the same sqlView with the modeling instance id | `{sqlStatement}` multi-pass plan: tables accessed, per-table passes, join, Analytical Engine steps | classic grid reports; any Mosaic model via the transient report | verified on a classic Tutorial project (multi-pass SQL: `CREATE TEMP TABLE` → `insert … select … group by` → final select with lookups + subquery → `drop table` → Analytical Engine step). **Does not work on a Mosaic cube instance** from `POST /api/v2/cubes/{id}/instances` (500 -2147206852); `/api/v2/cubes/{id}/instances/{iid}/sqlView` is 404 |
| **Dashboard datasets** | `POST /api/dossiers/{id}/instances` → `GET /api/dossiers/{id}/instances/{mid}/datasets/sqlView` | `datasets[].sqlStatement` (load SQL + in-memory view SQL per dataset) | dashboards | verified |
| **Dashboard visualization query details** | `GET /api/dossiers/{id}/instances/{mid}/queryDetails?chapterKey=&visualizationKey=` (document form: `GET /api/documents/{id}/instances/{iid}/queryDetails`) | `chapters[].visualizations[].{queryDetails, sql}` — the Workstation "Query Details" text with per-step timings | grid/graph visualizations | verified |
| **Datamart** | `GET /api/datamarts/{id}/instances/{iid}/sqlView?preview=true|false` | `{sqlStatement}` | datamart reports | spec only |
| **In-flight jobs** | `GET /api/monitors/jobs?nodeName=<node>&projectId=<id>` | `jobs[].{sql, template, filter, status, duration…}` | anything executing right now | needs **Monitor Jobs** privilege (else ERR014 -2147213784); not exercised |
| **Auto / agent questions** | `POST /api/questions/{questionId}/transformsql` | "transformed full SQL for the question" | Auto Answers questions | spec only |

Privilege for the sqlView / queryDetails family: `DssXmlPrivilegesWebReportSQL` (Web "View SQL"). The telemetry profile
endpoints take only `X-MSTR-AuthToken` (no project header). `/api/openSemanticLayer/*` paths are `visibility: internal`
(the Trino connector's own backend) — don't build on them.

## What the trace looks like (generalized from the capture)

Pass `sqlType` codes seen: **1** = SQL sent to a data source (its native dialect), **4** = Analytical Engine step
(`[Populate Report Data]`, cross-tabbing), **30** = in-memory projection / cube query (shown in Strategy's bracket
notation with `Table Join Tree`). Each job also carries `sqlPassType` (28 observed for query jobs).

1. **in_memory model** — one job, one pass of type 30 against the cube (`from <model> with Table Join Tree: TempTable… OuterJoin TempTable…`). No warehouse SQL at query time; the warehouse SQL lives in `cubes/{id}/sqlView` and the cache monitor's `queryPasseInfos`.
2. **connect_live single-source model** — pass 0 type 1 = real warehouse SQL (e.g. `select "a11"."<key>", "a11"."<fact>" AS "WJXBFS1" … from "<schema>"."<table>" "a11"` or `sum(...) group by` when aggregation is needed), pass 1 type 4 = Analytical Engine, pass 2 type 30 = final projection from `<model>_0`.
3. **linked multi-source model (connect_live composed model)** — two fragments:
   - fragment A, `pushdownType: FULL`: the cross-source federation SQL — one sub-select per source model over internal tables named `"<projectId>_<modelId>"."<tableGuid>"`, combined with `full outer join` + `coalesce(...)` on the shared attribute, metric columns aliased `WJXBFS1..n`;
   - fragment B, `pushdownType: PARTIAL`, `isLinkedModelStat: true`, `pushdownDisabledReason: "Pushdown join for mosaic view is disabled by config"`: the per-source jobs — the live source gets its own warehouse SQL (`select <key>, sum(<fact>) … group by <key>`), the in-memory source gets type-30 cube passes (lookup pass + `sum([…])@{[<attr>]}` pass). `serveModes: [2, 1]` lists both.
   The EXPLAIN plan calls this leaf `[Mosaic_Linking_MultiSource] link=true|multiSource=true|dataServeMode=connect_live`.

Pushdown policy visible in EXPLAIN: `direct_query_db_whiltelist: snowflake,starburst` (sic) — DIRECT_QUERY only for those
DB types; other engines fall back to the Strategy engine (`unsupported-db-type`); multi-source linking falls back with
`mosaic-linking-multi-source-no-trino`; JOIN_OFFLOAD applicability depends on the `enable_offload_neo_engine_*` flags.

## In-memory models: what the profile shows vs. Studio's Validation › Query (verified 2026-10-01)

For an in_memory model the `sourceBreakdown` pass is the **final join pass** of the cube query: `select … [TempTableNN.<metric>]
… from <model> with Table Join Tree: TempTable76 OuterJoin TempTable77 with output level Tuple(<grouped attributes>)`.
Studio's model editor → **Validation → Query** tab shows the complete plan for the same request: a `Tables Accessed` list
(lookup, relationship and fact tables with their roles), one `select … sum([[<fact table>].<metric>])@{<level>} … Save As
TempTableNN` pass per fact table, then that same final join — identical row count and values. Treat the profile pass as the
join step and derive the per-table passes from it: each `TempTableNN` carries the metrics of exactly one fact table, so the
model's `/factMetrics?showExpressionAs=tree` (metric → `fact.expressions[].tables[]`) plus `/metrics` (derived → base
metrics, scan the whole definition for `subType: fact_metric|metric` references — conditional and level metrics keep theirs
outside the expression tree) resolves every temp table to its fact table and, via `cubes/{id}/sqlView` block headers, its DB
instance. No attributes in the query ⇒ the temp tables are one-row totals joined with `CrossJoin … Tuple()`; that is correct.
**The complete plan for an ad-hoc request IS reachable (verified 2026-10-01): a transient report through the Modeling
service.** `POST /api/model/reports` (no changeset header — it is refused) with `information.subType: report_grid`,
`sourceType: cube`, `dataSource.cube: {objectId: <data model id>, subType: report_cube}`, `grid.viewTemplate.rows.units`
= `{type: attribute, id}` per attribute, `columns.units` = one `{type: metrics, elements: [{id, subType: metric}]}`; filters
as `grid.viewFilter.tree` with `predicate_form_qualification` nodes (`predicateId`, `predicateText`, `predicateTree:
{function: equals, parameters: [{parameterType: constant, constant: {type: character, value}}], attribute, form}`) — the
auto date hierarchy's month/day attributes are virtual and return 8004c767 "not found in metadata" when qualified. The
201 response's `X-MSTR-MS-Instance` header names a modeling instance; `POST /api/model/reports/{id}/instances` with that
header executes it (204, no body); `GET /api/v2/reports/{id}/instances/{msInstance}/sqlView` then returns the engine's
full plan — `Tables Accessed`, one `Save As TempTableNN` pass per fact table, the final join, `[Analytical engine
calculation steps]` — identical to Studio › Validation › Query for the same objects. Nothing is written to metadata
(`versionId` is all zeros; `DELETE /api/objects/{id}` answers 404); delete the modeling instance when done. Caveat: the
report's final join follows report defaults (inner `Join`) whereas the SQL endpoint's pass for the same query used
`LeftOuterJoin` and Studio's preview `OuterJoin` — same rows only when every key exists in both sources.
The in-memory dashboard route (`POST /api/dossiers/instances` with the model as a type-3 object) still works for
`queryDetails` but needs the undocumented manipulation `actions` string to place objects — prefer the report route.

## Trace recipe

```python
# env: MSTR_BASE, MSTR_USER, MSTR_PASSWORD, MSTR_PROJECT_NAME  (see reference_strategy_env.md)
from trino.dbapi import connect; from trino.auth import BasicAuthentication
cur = connect(host=<Library host>, port=443, http_scheme="https", catalog="sql",
              schema=<project name lowercased>, user=USER, auth=BasicAuthentication(USER, PW)).cursor()
cur.execute("EXPLAIN " + sql)            # plan + Strategy template + optimization flow
cur.execute(sql); rows = cur.fetchall()  # on error: TrinoQueryError.query_id still identifies the query
qid = cur.query_id                        # or cur.stats["queryId"]
prof = GET /api/telemetry/performance/queryProfile/{qid}                       # X-MSTR-AuthToken only
for doc in prof["documents"]:
    for tpl in doc["templateIds"] or [None]:
        for frag in prof["fragmentStats"]:
            GET /api/telemetry/performance/queryProfile/{frag.trinoFragmentId}/sourceBreakdown/{doc.instanceId}[/{tpl}]
            # -> jobs[].passes[].sqlQuery
```
Runnable, env-driven version: `captures/20261001-engine-sql-visibility/trace_mosaic_sql.py` (local, `.py` under captures is gitignored).

## Gotchas

- The Trino query id is the join key for everything; capture it from the client (`cursor.query_id`, or `TrinoQueryError.query_id` on failure). Failed queries have no profile.
- A second REST `requests.Session` reusing the auth token must also carry the login cookies on Strategy ONE Cloud (ingress routing) or you get ERR009 "session has expired".
- `cubes/{id}/sqlView` answers for published (in_memory) models only; for connect_live models use the telemetry profile.
- `reports/{id}/instances/{iid}/sqlView` is for report instances; a Mosaic cube instance has no SQL view.
- `GET /api/monitors/jobs` needs the Monitor Jobs privilege; the `sql` field is only present while the job runs.
- Keep traced queries scoped (attributes + metrics, no bare `COUNT(*)` over a whole model) — see the job-execution-time-limit note in the MCP tools memory.

## Related
- `reference_mcp_tools.md` (Trino/MCP query surface), `reference_mosaic_rest_gotchas.md` (Trino column naming),
  `reference_strategy_monitoring_jobs_alerts.md` (cache/job monitors), `reference_mosaic_vs_legacy_surfaces.md`.
- Capture: `captures/20261001-engine-sql-visibility/README.md`.
