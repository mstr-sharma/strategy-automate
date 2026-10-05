---
name: strategy-platform
description: The shared core every Strategy (formerly MicroStrategy) automation in this repo runs on — sign-in (password, LDAP, API token, browser single sign-on, identity token, OIDC), a spec-validated way to call ANY of the ~1,700 Strategy REST operations, and the client for the tenant's Mosaic and Agent MCP servers. Use it for "call the Strategy API", "is there an endpoint for …", "what can the REST API do for X", "describe this endpoint", "log in with SSO", "no password", "API token", "call the MCP server from a script", or whenever no domain skill wraps the operation you need.
---

# Strategy platform core

Everything else in this repo builds on four modules in `skills/strategy-platform/scripts/`:

| Script | What it does |
|---|---|
| `strategy_auth.py` | Signs any script in: `password`, `ldap`, `anonymous`, `api-token`, `sso` (browser single sign-on, no password), `identity-token`, `oidc`. Caches browser sessions in the OS keychain; logs out with `POST /api/auth/logout`. CLI: `methods`, `login`, `status`, `logout`. |
| `strategy_api.py` | Lists, describes and calls **every** REST operation in the tenant's own OpenAPI spec, validating each request before it is sent. |
| `strategy_mcp.py` | Calls the Mosaic MCP server (`--server mosaic`, default) or the Agent MCP server (`--server agent`) with the same OAuth single sign-on the MCP connector uses. |
| `_client.py` | `BaseMSTR` and helpers shared by the inventory, mining and validation scripts. |

Sign-in details and the REST contracts behind them: `memory/reference_strategy_authentication.md`. MCP details: `memory/reference_mcp_tools.md`.

## Sign in

```bash
export MSTR_BASE=https://<tenant>.strategy.com/MicroStrategyLibrary
python3 skills/strategy-platform/scripts/strategy_auth.py methods   # what the tenant enables, what this machine would use
python3 skills/strategy-platform/scripts/strategy_auth.py login     # SSO accounts: the human clicks Allow once in the browser
```

Scripts pick the method with `--auth-method` / `MSTR_AUTH_METHOD` (default `auto`: API token, else user + password, else a cached browser session or saved API token, else browser SSO). Never type a user's password, never print tokens, never pass secrets as command-line flags.

## Call any REST operation

```bash
API="python3 skills/strategy-platform/scripts/strategy_api.py"
$API sync                                   # cache the tenant's spec (public + internal operations)
$API tags                                   # every API area, its operation count and owning skill
$API ops --tag Subscriptions                # operations in an area (or an owning skill: --tag strategy-distribution)
$API ops --search "security role"           # words that must all match id, path or summary
$API describe getUserGroups                 # parameters, auto-filled headers, body skeleton, responses
$API call getUserGroups -p limit=50         # reads run directly
$API call createUserGroup --body @group.json            # writes print the request (dry run) …
$API call createUserGroup --body @group.json --yes      # … and run only with --yes
$API call "DELETE /api/usergroups/{id}" -p id=<ID> --yes
```

What `call` does for you:
- **Validates** against the spec: unknown parameter names (with the valid list), missing required path/query/header parameters, enum values, a missing or unexpected body, missing required top-level body fields.
- **Fills required headers:** `X-MSTR-ProjectID` from `--project` (id or name) / `MSTR_PROJECT_ID` / `MSTR_PROJECT_NAME`; a Modeling **changeset** when the operation requires one (opened, committed on success, discarded on failure; reads always discard; `--schema-edit` for schema-lock changesets, `--changeset <id>` to join one you hold); `Prefer: respond-async` when required.
- **Gates writes:** anything but GET/HEAD needs `--yes`; without it the exact request is printed and nothing is sent.
- **Flags** internal (non-public) and deprecated operations, redacts tokens and cookies, asks exports for their real type (PDF, Excel, CSV, YAML, binary), and writes large or binary responses to a private file with a preview instead of flooding the console (`--out FILE` to choose the file).
- **Multi-step chains** (run a report, then page it; start a search, then read it; start a job, then poll it) need one session across calls. Browser SSO sessions are reused automatically; for a password or API token add `--reuse-session` (or `MSTR_REUSE_SESSION=1`) so the session is cached and left open, and end it with `strategy_auth.py logout`. Without it each call signs in and out, which ends the instances and jobs the previous call created.

An operation is an `operationId` or `"VERB /api/path"` (a few operationIds are duplicated in the spec — the tool asks for the verb and path then). Multipart uploads are not covered by `call`; use `build_mosaic.py api-call --file/--form`.

## Who owns what

`strategy_api.py tags` prints this from `SKILL_TAGS` in `strategy_api.py`; the generated per-area table with coverage numbers is `memory/reference_strategy_api_surface.md`.

| Skill | Owns (spec tags) |
|---|---|
| `strategy-platform` | Authentication, Misc, Documentation |
| `strategy-admin` | System Administration, User Management, Security Roles, privileges, SCIM, IAM, Multi Tenant, License, vault, preferences, languages, projects, server/client configuration |
| `strategy-distribution` | Subscriptions, Schedules, Events, Transmitters, Devices, Contacts, Contact Groups, History List |
| `strategy-content` | Reports, Dashboards / Documents, Library, Browsing, Object Management, content groups/bundles, themes, maps, Cubes, Datasets, Datamarts |
| `strategy-migration` | Migrations, Migration Groups, Packages, Project Duplications, Git |
| `strategy-ops` | Monitors, Telemetry, Change Journal, performance, server scripts, tasks, flows |
| `strategy-ai` | Agents, Auto Bots, Explorer, Ontology, recommendations |
| `build-mosaic-model` / `strategy-data-modeling` | Data Models, schema objects, security filters, datasources, catalog |
| `strategy-validation` | Test Center (baseline and comparison tests) plus paired-query validation |

## When to write a typed helper instead

`strategy_api.py call` covers single operations. Write a typed helper (in the owning skill's `scripts/` folder) only when a workflow is multi-step, constructs non-trivial payloads, needs read-back verification or cleanup, or is risky enough to want guard rails — e.g. `build_mosaic.py build`, `patch-fact-metrics`, `strategy_library_publications.py replicate`. Helpers in other skills import this folder with:

```python
sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                 os.pardir, os.pardir, "strategy-platform", "scripts")))
import strategy_auth            # sign_in / sign_out
from _client import BaseMSTR    # or strategy_api for spec lookups
```

Every new helper gets hermetic tests; `tests/test_rest_contract.py` fails if a script calls a path/verb the spec does not have.

## Keeping current

When the platform moves (new release, new tenant):

```bash
$API sync
$API export-index --out tests/fixtures/strategy_rest_operations.tsv      # CI's copy of the operation list
$API coverage --write memory/reference_strategy_api_surface.md          # regenerate the surface map
python3 -m pytest -q tests                                              # contract test + every new area has an owner
```

A new spec tag fails `tests/test_strategy_api.py` until it is assigned to a skill in `SKILL_TAGS`.

## Safety rules

- Reads first; show the dry run of a write before sending it with `--yes`; read back after every write.
- Internal operations are not part of the public contract — fine for probing, say so before relying on one.
- Do not log out a borrowed or browser-shared session; `strategy_auth.sign_out()` already leaves those alone.
- Secrets come from env vars or the OS keychain only.
