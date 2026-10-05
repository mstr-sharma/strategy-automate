---
name: Strategy environment configuration
description: How the helper scripts and skills read tenant/project/credential configuration. All values come from environment variables or CLI flags — no hardcoded tenants in the repo.
type: reference
---
## Configuration model

Every script and skill in this repo reads tenant + credential values from environment variables (or equivalent CLI flags). Nothing is hardcoded. See `.env.example` at the repo root for a copyable template.

## Environment variables

| Variable | Required | Purpose |
| --- | --- | --- |
| `MSTR_BASE` | yes | Library URL, e.g. `https://your-tenant.example.com/MicroStrategyLibrary`. Use the final host: clients refuse a redirect to another origin. |
| `MSTR_AUTH_METHOD` | no | `auto` (default), `password`, `ldap`, `anonymous`, `api-token`, `sso`, `identity-token`, `oidc`. See `reference_strategy_authentication.md`. |
| `MSTR_USER` | password sign-in | Username for `/api/auth/login` (Standard or LDAP). Not needed for SSO. |
| `MSTR_PASSWORD` | password sign-in | Password. Never commit. Set in shell, keychain, or CI secret store. |
| `MSTR_LOGIN_MODE` | no | 1 = Standard (default), 16 = LDAP, 8 = Anonymous, 4096 = API token. SAML (1048576) and OIDC (4194304) are browser modes → `MSTR_AUTH_METHOD=sso`. |
| `MSTR_API_TOKEN` | api-token sign-in | API token (login mode 4096), e.g. for CI. |
| `MSTR_DELEGATE_IDENTITY_TOKEN` | identity-token sign-in | Identity token minted by another app's session (`POST /api/auth/delegate`). |
| `MSTR_SSO_PORT` / `MSTR_SSO_HOST` | no | Loopback port (default 8753) and host (`127.0.0.1` or `localhost`) for the SSO consent page and OAuth redirects. |
| `MSTR_SSO_BROWSER` / `MSTR_SSO_TIMEOUT` | no | Browser to open (a `webbrowser` name, e.g. `chrome`) and seconds to wait (default 300). |
| `MSTR_SESSION_CACHE` | no | `0` disables caching browser sessions in the OS secret store. |
| `MSTR_REUSE_SESSION` | no | `1` keeps password / API-token sessions open and cached between commands (one session for a whole chain) in every script that signs in through `strategy_auth.py` (`build_mosaic.py`, the `_client.py` scripts, `strategy_api.py`); end with `strategy_auth.py logout`. |
| `MSTR_HTTP_TIMEOUT` | no | Read timeout in seconds for every REST call (default 300; the connect timeout is 15 s). Applied by `strategy_auth.SafeSession`, which every client uses; a single call can still pass its own timeout. |
| `MSTR_HTTP_RETRIES` | no | Retries for connection failures (any verb) and HTTP 502/503/504 on GET/HEAD/OPTIONS (default 2). Read timeouts and writes are never repeated. |
| `MSTR_SECRET_STORE` | no | Force `keychain`, `secret-tool`, `file` or `none`. |
| `MSTR_MCP_URL` | no | Mosaic MCP endpoint for `strategy_mcp.py` (found from `MSTR_BASE` when unset). |
| `MSTR_PROJECT_ID` | one-of | Project UUID (32-hex). |
| `MSTR_PROJECT_NAME` | one-of | Project display name — helper will resolve to ID at login. Either `MSTR_PROJECT_ID` or `MSTR_PROJECT_NAME` is required; ID wins when both are set. |
| `MSTR_DEST_FOLDER_ID` | build-only | Destination folder UUID for new Mosaic data models. Look up once via `/api/folders/…` in the target project and export; used by `build_mosaic.py build`. |
| `MSTR_DEST_FOLDER` | no | Legacy alias for `MSTR_DEST_FOLDER_ID`, kept for back-compat. `MSTR_DEST_FOLDER_ID` wins when both are set. |
| `MSTR_NEW_USER_PASSWORD` | no | Default password for `build_mosaic.py create-users` rows that omit one. Read via `--default-password-env`, which defaults to this var name. |

### Borrowed session (last resort — prefer `MSTR_AUTH_METHOD=sso`)

`build_mosaic.py` also accepts a session copied out of a logged-in browser (DevTools → Network header + Application → Cookies). It reuses the session in place and never logs it out, so the human's UI session stays intact. The `sso` method gets the same result without DevTools.

| Variable | Required | Purpose |
| --- | --- | --- |
| `MSTR_AUTH_TOKEN` | borrowed-session | REST session token (`X-MSTR-AuthToken` header). |
| `MSTR_IDENTITY_TOKEN` | no | Modeling Service identity token. Optional — minted from the borrowed session when omitted and a Modeling-Service-bound command runs. |
| `MSTR_SESSION_COOKIE` | borrowed-session | `JSESSIONID` cookie from the logged-in browser session. |
| `MSTR_INGRESS_COOKIE` | borrowed-session | `library-ingress` cookie (Strategy Cloud load-balancer routing cookie). |

### strategy_validate.py subject-matter overrides

Defaults target the MicroStrategy Tutorial project so the live-tenant validator works there out-of-the-box; override to point at any project.

| Variable | Default | Purpose |
| --- | --- | --- |
| `MSTR_VALIDATE_ATTR` | `Category` | Attribute to resolve/inspect in workflows 2–3 and 9. |
| `MSTR_VALIDATE_ELEMENT` | `Books` | Element of that attribute for the security-filter qualification. |
| `MSTR_VALIDATE_METRICS` | `Revenue,Profit,Cost` | Comma-separated metric names for definition inspection. |
| `MSTR_VALIDATE_SEARCH_TERMS` | `Revenue,Sales,Category,Profit,Inventory` | Comma-separated terms for the report/cube search workflow. |
| `MSTR_VALIDATE_DASHBOARD_TERMS` | `Tutorial Home,Dashboard,Sales,Revenue` | Comma-separated terms for the document/dashboard export probe. |
| `MSTR_VALIDATE_SF_NAME` | `<attr> in <element> — secFilter_validation` | Name for the validation security filter. |

CLI equivalents: REST scripts take `--base`, `--auth-method` and a project flag (`--project-id`, `--project-name` or `--project` — see each `--help`); password-capable scripts also take `--user` / `--login-mode` (`strategy_library_publications.py`: `--base-url` / `--username`), and build-mosaic also takes `--dest-folder` plus borrowed-session flags (`--auth-token`, `--identity-token`, `--session-cookie`, `--ingress-cookie`). CLI flags win over env vars. Secrets come from env vars or the OS keychain, never flags: a `--password` on the command line is visible to other local processes.

## MCP connectivity (separate from REST)

The Mosaic MCP tools (`get_projects`, `get_models` — older servers `get_mosaic_models` — `get_semantics`, `query`) connect through **Claude / Codex connector config**, not this repo; scripts can reach the same server with `strategy_mcp.py` (see `reference_strategy_authentication.md`). Each user adds the MCP server to their Claude Code / Codex settings once; the tool names are standard, the server id prefix (`mcp__<uuid>__*`) is per-user. The skills here reference MCP tools by **tool name**, not server id, so any correctly-configured MCP connection works.

## Looking up tenant-specific IDs

Every environment has different internal IDs. Do not paste production IDs into memory. The repo helpers resolve IDs at runtime:

- **Projects:** `GET /api/projects` → choose by name, read `id`.
- **Datasources (DB instances):** `python3 skills/build-mosaic-model/scripts/build_mosaic.py list-datasources` → filter by name, read `id`.
- **Destination folder (for new models):** browse `/api/folders/{id}` from a well-known root (`/api/folders/preDefined/1` = Public Objects; 19 = My Objects; 8 is Public Searches) and pick a target.
- **Reference TPCH (or other seed) model:** `python3 skills/build-mosaic-model/scripts/build_mosaic.py search-objects --name "<seed model name>" --type 3` → read `id`.
- **Universal ID form** `45C11FA478E745FEA08D781CEA190FE5` — this IS a Strategy platform-wide constant, shared across all tenants. Safe to use as-is.

## Local workflow

```bash
cp .env.example .env          # one-time
# edit .env with your tenant values
set -a; source .env; set +a   # export into shell
python3 skills/build-mosaic-model/scripts/build_mosaic.py auth-probe
```

CI / automation should inject the same variables from the platform's secret store; never commit a populated `.env`.

## Validation note

The consumer-grade build + validation reference run documented in `reference_strategy_mosaic_field_study.md` and `reference_strategy_data_validation.md` was executed against a Strategy Cloud tenant. The dated portfolio numbers (156 data models, 1830 one-to-many relationships, etc.) live in `captures/2026-04-21-mosaic-portfolio-field-study/README.md` — they describe that tenant's state at run time and are illustrative of shape, not a fixed expectation for every tenant.
