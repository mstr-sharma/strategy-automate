---
name: Mosaic MCP tools and how they relate to the REST helpers
description: The tenant's two MCP servers (Mosaic, Agents), the Mosaic tools over certified content (Mosaic models plus classic cubes/reports/datasets), calling them from scripts with the same single sign-on, and where REST takes over.
type: reference
---
**Two MCP servers per tenant** (verified 2026-10-05): the **Mosaic** MCP server at `{host}/collaboration/mcp/mosaic` (the tools below) and the **Agent** MCP server at `{host}/collaboration/mcp/agent` (Strategy AI agents). Both sign in through OAuth at `{host}/collaboration`; each token is scoped to one server. The host-root `/.well-known/oauth-protected-resource` names only the Agent server — discover the Mosaic one from its own 401 challenge or `{host}/collaboration/.well-known/oauth-protected-resource/mcp/mosaic`.

**Mosaic MCP server:** tools appear under a per-user prefix (`mcp__<server>__`); read-only over **certified** content — published is not enough (corrected 2026-10-05).
- `get_projects` — list Strategy projects the user can access.
- `get_models` (older servers: `get_mosaic_models`) — lists **certified** content only, typed `Mosaic Model` or `Other Model`. `Other Model` = governed classic content — Intelligent Cubes, reports and datasets from classic projects (verified 2026-10-05: a classic tutorial project lists only `Other Model` rows, and `get_semantics` + `query` work on them). `only_mosaic_models=true` filters to Mosaic. A published but uncertified model is missing from the list; classic cubes also need AI enablement (`POST /api/cubes/dumpcubes`, status `POST /api/v2/bots/cubes/status`).
- `get_semantics {project, model}` — attribute + metric list for one model (the shape the benchmark scripts embed in system prompts). Lookup is by model name and fails until the model is certified. To make a fresh build visible to MCP, run `build_mosaic.py certify --object-id <modelId>` (or `--certify` at build) after publish; until then use REST (`/api/model/dataModels/{id}/attributes` + `/factMetrics`) and direct Trino.
- `query {project, query}` — read-only Trino-compatible SQL; write/DDL is rejected with `MOSAIC_SQL_WRITE_REJECTED`. Include a `LIMIT` when exploring, never `SELECT *`, and wrap metrics in an aggregate when grouping. Avoid whole-model `COUNT(*)` probes on big models: the query can hit the job time limit (see `reference_strategy_sql_visibility.md`).

**From scripts:** `skills/strategy-platform/scripts/strategy_mcp.py` signs in exactly like the MCP connector (OAuth 2.1 + PKCE through the tenant's single sign-on, dynamic client registration, refresh tokens in the OS secret store) and exposes `login`, `tools`, `call <tool> --args JSON` and `query --project P --sql S` (`--server mosaic` by default, `--server agent` for the Agent server). The token is scoped to the MCP server — REST ignores it — so REST scripts sign in with `strategy_auth.py` (`--auth-method sso` for the same SSO). See `reference_strategy_authentication.md`.

**Strategy REST:** no first-class MCP; every write and admin task goes through `$REPO/skills/build-mosaic-model/scripts/build_mosaic.py` and its siblings, signing in through `strategy_auth.py` with configuration from env vars (never stored credentials).

**Browser-automation MCPs** (Claude Preview, Claude in Chrome): useful to confirm something in the Library UI, never a substitute for REST — and never used to type a user's credentials.
