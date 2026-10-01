# 2026-10-01 — Engine-generated SQL visibility (Mosaic SQL → multi-pass, cross-store SQL)

Question: a consumer writes flat-table SQL against a Mosaic model (Trino endpoint / MCP `query`); which APIs show the
SQL the Strategy engine actually ran? Durable answer: `memory/reference_strategy_sql_visibility.md`. This file is the
dated transcript. Stand-ins: **EReaderCo** = an in_memory model (Snowflake synthetic tables + Postgres extension tables),
**PharmaCo** = a Postgres-only connect_live model plus a composed (linked) connect_live model that joins it to a
Snowflake-sourced in_memory model. Tenant: a Strategy ONE Cloud tenant (two iServer nodes); classic report check on a
second tenant's classic Tutorial project. All object IDs, hostnames and warehouse table names redacted.

## Discovery (OpenAPI, `?visibility=all`, 2026 spec, 652+ paths)

SQL-bearing paths: `/api/v2/reports/{id}/instances/{iid}/sqlView`, `/api/v2/cubes/{id}/sqlView`,
`/api/dossiers/{id}/instances/{iid}/datasets/sqlView`, `/api/dossiers/{id}/instances/{iid}/queryDetails`,
`/api/documents/{id}/instances/{iid}/queryDetails`, `/api/datamarts/{id}/instances/{iid}/sqlView`,
`/api/telemetry/performance/queryProfile/{trinoQueryId}`, `…/queryProfile/{trinoFragmentId}/sourceBreakdown/{instanceId}[/{templateId}]`,
`/api/questions/{questionId}/transformsql`, `/api/monitors/jobs` (`JobInfo.sql`), `/api/monitors/caches/cubes/{id}`
(`CubeCacheDetail.jobExecutionStatistics.queryPasseInfos[].sqlStatement`), `/api/openSemanticLayer/*` (internal).

## Runs

### 1. EReaderCo (in_memory, two DB instances) — Trino query
`SELECT "customer (name)", SUM("list price"), SUM("minutes consumed") FROM "<EReaderCo model>" GROUP BY 1 ORDER BY 2 DESC LIMIT 5` → 5 rows, 1.2 s.

- `EXPLAIN`: `TableScan[table = sql:<project>:<model>:(template)<guid>]` + `[Template]` block (units / metrics / group-by / sort / limit, template JSON) + `Strategy Plan Optimization Flow`: leaf `[Mosaic_InMemory] dataServeMode=in_memory`, JOIN_OFFLOAD applicable, DIRECT_QUERY not applicable (all cubes in-memory), `Workflow: fully-pushdown (engine)`.
- `queryProfile`: `sourceType: USL`, one fragment `pushdownType: FULL`, one document `serveModes: [1]`, `jobIds: []`, `templateIds: []`.
- `sourceBreakdown/{instanceId}` (no templateId): 1 job, 1 pass `sqlType 30`, 280 rows, 4 ms:
  ```
  select [Customer]@[CUSTOMER_ID], [Customer]@[NAME],
         [TempTable80.List Price] as [List Price], [TempTable81.Minutes Consumed] as [Minutes Consumed]
  from   <EReaderCo model>
  with Table Join Tree: TempTable80 OuterJoin TempTable81 with output level Tuple([Customer]@[CUSTOMER_ID])
  ```
- `GET /api/v2/cubes/{id}/sqlView` → 200: one `[DB Instance: <synthetic-data instance>]` block per Snowflake table (`select /* {"ms_dataset_id":"<model id>"} */ … from "<SCHEMA>"."<EREADERCO_TABLE>"`), then `[DB Instance: <postgres instance>]` blocks for the extension tables (`from "public"."<EREADERCO_EXT_TABLE>"`).
- `GET /api/monitors/caches/cubes?clusterNode=<node>&projectIds=<id>` → 981 caches on the node; matched on `source.id`; detail → `jobExecutionStatistics`: 18 SQL passes, 0 analytical passes, `sqlDuration 13236`, `accessedTables[]`, `queryPasseInfos[]` = the same per-table load statements with rows/duration.

### 2. PharmaCo (Postgres-only, connect_live) — Trino query
`SELECT "shipment line (id)", SUM("units shipped"), SUM("freight cost") FROM "<PharmaCo live model>" GROUP BY 1 ORDER BY 2 DESC LIMIT 5` → 5 rows, 10.1 s.

- `EXPLAIN` leaf: `[Mosaic_Live] link=false|multiSource=false|dataServeMode=connect_live [sourceDbRoles: <dbrole>@postgre]`; DIRECT_QUERY ❌ `Got unsupported DB types. Cube source DB types: [PostgreSql]. Supported DB types: [Starburst, Snowflake]`; fallback reason `unsupported-db-type`; `Workflow: fully-pushdown (engine)`.
- `queryProfile`: one document `serveModes: [2]`, `templateIds: [<t>]`, `jobIds: [<j>]`.
- `sourceBreakdown/{instanceId}/{templateId}`: 1 job (`sqlPassType 28`, 9406 ms, 3679 rows):
  ```
  pass 0 sqlType=1  (70 ms, 3679 rows)   -- warehouse SQL, Postgres dialect
  select "a11"."SHIPMENT_LINE_ID" AS "SHIPMENT_LINE_ID", "a11"."FREIGHT_COST" AS "WJXBFS1", "a11"."UNITS_SHIPPED" AS "WJXBFS2"
  from   "<pg_schema>"."<PHARMACO_ORDER_SHIPMENTS>" "a11"
  pass 1 sqlType=4   [Populate Report Data] [Analytical engine calculation steps: 1. Perform cross-tabbing]
  pass 2 sqlType=30  select [Shipment Line]@[SHIPMENT_LINE_ID], [Freight Cost] as [Freight Cost], [Units Shipped] as [Units Shipped] from <PharmaCo live model>_0
  ```
- `GET /api/v2/cubes/{id}/sqlView` → **400 ERR010 DE93362 "Live Intelligent Cubes cannot be published"** (connect_live has no publish SQL).
- `POST /api/v2/cubes/{id}/instances` (1 attribute + 1 metric) → 200 instance; `GET /api/v2/reports/{id}/instances/{iid}/sqlView` → **500 -2147206852**; `/api/v2/cubes/{id}/instances/{iid}/sqlView` and `/api/reports/{id}/instances/{iid}/sqlView` → 404.

### 3. PharmaCo composed model (connect_live, links Snowflake in_memory model + Postgres live model) — cross-store metrics
`SELECT "customer segment (id)", SUM("transaction amount"), SUM("net sales") FROM "<PharmaCo composed model>" GROUP BY 1 ORDER BY 2 DESC LIMIT 5` → 4 rows, 2.6 s (Transaction Amount from the Snowflake-sourced cube, Net Sales from Postgres).

- `EXPLAIN` leaf: `[Mosaic_Linking_MultiSource] link=true|multiSource=true|dataServeMode=connect_live`; DIRECT_QUERY ❌ `Cube source is multi-source mosaic linking, but Trino is not in the whitelist`; fallback `mosaic-linking-multi-source-no-trino`.
- `queryProfile`: **two fragments** — `<qid>.0` `pushdownType FULL`; `<qid2>.0` `pushdownType PARTIAL`, `isLinkedModelStat true`, `parentJobId <j>`, `pushdownDisabledReason "[Cannot pushdown: Join][Config]['Pushdown join for mosaic view is disabled by config.' …]"`. **Two documents** — composed-model document `serveModes [2]`, 1 template, 1 job; linked document `serveModes [2, 1]`, 3 templates, 2 jobs, objects `Customer (ID)`, `Net Sales`, `Customer Segment (ID)`, `derived_column_<guid>`, `Transaction Amount`.
- `sourceBreakdown` of the composed document (FULL fragment): pass 0 `sqlType 1`, 1810 ms, 4 rows — the federation SQL:
  ```
  select coalesce("pa11"."SEGMENT", "pa12"."SEGMENT") "SEGMENT", "pa11"."WJXBFS1" "WJXBFS1", "pa12"."WJXBFS1" "WJXBFS2"
  from (select "a12"."<segment-form-col>" "SEGMENT", sum("a11"."<transaction-amount-col>") "WJXBFS1"
        from "<projectId>_<snowflake-model-id>"."<fact-table-guid>" "a11"
        join "<projectId>_<snowflake-model-id>"."<customer-table-guid>" "a12" on ("a11"."<customer-key>" = "a12"."<customer-key>")
        group by "a12"."<segment-form-col>") "pa11"
  full outer join (select "a12"."<segment-form-col>" "SEGMENT", sum("a11"."<net-sales-col>") "WJXBFS1"
        from "<projectId>_<postgres-model-id>"."<gtn-table-guid>" "a11"
        join "<projectId>_<snowflake-model-id>"."<customer-table-guid>" "a12" on ("a11"."<customer-key>" = "a12"."<customer-key>")
        group by "a12"."<segment-form-col>") "pa12"
  on ("pa11"."SEGMENT" = "pa12"."SEGMENT")
  ```
  then pass 1 `sqlType 4` (cross-tabbing) and pass 2 `sqlType 30` projection from `<composed model>_0`.
- `sourceBreakdown` of the linked document (PARTIAL fragment), 3 jobs:
  - Postgres live job: pass 0 `sqlType 1`, 100 ms, 200 rows: `select "a11"."CUSTOMER_ID", sum("a11"."NET_SALES") AS "WJXBFS1" from "<pg_schema>"."<PHARMACO_GROSS_TO_NET>" "a11" group by "a11"."CUSTOMER_ID"` + pass 4 + pass 30 from `<PharmaCo live model>_0`.
  - Snowflake in_memory job A: pass 0 `sqlType 30`, 2 ms, 200 rows: `select [Customer]@[CUSTOMER_ID], [Customer Segment]@[SEGMENT], max([Region]@[REGION])@{[Customer]} as [derived_column_<guid>] from <Snowflake model> with Table Join Tree: [<CUSTOMERS table>]`.
  - Snowflake in_memory job B: pass 0 `sqlType 30`, 1 ms, 200 rows: `select [Customer]@[CUSTOMER_ID], sum([[<TRANSACTIONS table>].Transaction Amount])@{[Customer]} as [Transaction Amount] from <Snowflake model> with Table Join Tree: [<TRANSACTIONS table>]`.

### 4. Dashboard (owned by the operator) on the same tenant
`POST /api/dossiers/{id}/instances` → 201; `datasets/sqlView` → 200 with `datasets[].sqlStatement` (dataset load SQL in the warehouse dialect, followed by the in-memory view SQL in backtick notation); `queryDetails` → 200 with `chapters[].visualizations[].{queryDetails, sql}` — "Visualization Summary" / "Individual Step" blocks with timings. Two agent-type dashboards returned 500 -2147156965 on instance creation (not SQL-related).

### 5. Classic report on a classic Tutorial project (second tenant)
`POST /api/v2/reports/{id}/instances` → 200 → `GET /api/v2/reports/{id}/instances/{iid}/sqlView` → 200 `sqlStatement`: `CREATE TEMP TABLE <T…>(…)` → `insert into <T…> select … sum(…) … from "public"."order_detail" join lu_item/lu_subcateg/lu_day … group by` → final `select … from <T…> join lu_category join lu_quarter where quarter_id in (subquery)` → `drop table <T…>` → `[Analytical engine calculation steps: 1. Perform cross-tabbing]`. Prompted reports return `status 2` and need answers first.

### 6. In-memory model cross-check against Studio › Validation › Query (operator-run, same tenant)
Request: Cloud Provider × Snapshot Date (Month) with six metrics on an in_memory two-source model (Snowflake fact +
Postgres telemetry). Studio's Query tab: `Tables Accessed` (month lookup, cloud→system and date relationship tables, the
two fact tables), pass 1 `sum([[F_<SNOWFLAKE_FACT>].Total Cost])@{[Cloud Provider],[Snapshot Date (Month)]} … Save As
TempTable76`, pass 2 the same shape over `[F_<POSTGRES_TELEMETRY>]` → `TempTable77`, pass 3 the final `OuterJoin` of the
two at `(Cloud Provider, Month)`. The telemetry `sourceBreakdown` for the identical Trino query returned pass 3 only, with
the same 82 rows and values. Resolved the temp tables from `/factMetrics` + `/metrics` definitions instead (see memory).
`POST /api/dossiers/instances` with the model as a type-3 object → 201, in-memory dashboard with one empty visualization;
`queryDetails` → 200 (`select from <model>`); passing attribute/metric objects (type 12/4) → 500 "You have entered an
invalid name"; the manipulations body's `actions` string is undocumented, so the per-section plan was not reproduced.

## Tenant observations (not rules)
- `GET /api/monitors/jobs?nodeName=…` → ERR014 -2147213784 "You do not have Monitor Jobs privilege(s)" for the operator user on the Cloud tenant; the `sql` field on in-flight jobs therefore stays unverified.
- A connect_live model over a public TPC-H Snowflake sample failed at query time with a JDBC "Incorrect username or password" from the datasource — the datasource login behind that model is stale; the Trino error text itself exposes the engine job (`Document execution fails. Error initializing data model from document instance, job <n>`), and a failed query has no `queryProfile` (500 "No query stats found for the provided trinoQueryId").
- Reusing the auth token in a second `requests.Session` without the login cookies → ERR009 "session has expired" (ingress routing); copy cookies.
- Full `EXPLAIN` text ≈ 7 KB per query; `queryProfile` + `sourceBreakdown` ≈ 10–20 KB for the three-job linked case.

Scripts (local, gitignored): `trace_mosaic_sql.py` (env-driven trace), scratch probes for cube-cache / report / dashboard checks.
