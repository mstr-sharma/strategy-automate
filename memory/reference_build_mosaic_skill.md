---
name: build-mosaic-model skill location and subcommands
description: Where the skill lives and what every subcommand of its helper script does.
type: reference
originSessionId: initial-session
---
**Skill:** `$REPO/skill/SKILL.md`
**Helper script:** `$REPO/skill/scripts/build_mosaic.py`

Invoke directly; auto-reads tenant defaults and requires `MSTR_PASSWORD` (or `--password`) for authenticated calls. Do not hardcode credentials in memory or skill files.

**Discovery subcommands (read-only):**
- `auth-probe` — confirm login + identity-token flow.
- `list-datasources [--name SUBSTR]` — list DB instances, filter by name.
- `list-namespaces --instance NAME|--instance-id ID` — schemas in a DB instance.
- `list-tables --instance-id ID --namespace SCHEMA [--match SUBSTR]` — tables; uses base64(`{"ns":…}`) for namespaceId under the hood.
- `describe-table --instance-id ID --namespace SCHEMA --table T` — columns + types; uses base64(`{"tbn":…,"ns":…}`) for tableId.
- `discover` — probes every endpoint variant; useful when porting to a new MSTR version.
- `openapi-summary [--out /tmp/strategy-openapi.yaml]` — fetches `{base}/api/openapi.yaml`, prints title/version/path counts, and selected modeling/data-source paths. Does not require login.
- `openapi-search PATTERN [--context N]` — searches local `openapi.yaml` first, then live OpenAPI; use before coding new endpoint workflows.
- `api-call --method GET --path /api/projects` — generic authenticated Strategy REST caller. Use `--no-auth` for public paths such as `/api/openapi.yaml`; `DELETE` requires `--yes`.
- `resolve-users --user NAME_OR_EMAIL` / `--file users.csv` — resolve user IDs before ACL/security/user writes.
- `search-objects --name NAME [--type N] [--subtype N]` — Quick Search wrapper for object IDs.
- `get-model-object --kind attribute|fact_metric|legacy_attribute|... --model-id M --object-id O --show-expression-as tokens` — read Mosaic-contained or classic schema object definitions.

**Build subcommand:**
- `build --name N --source "INSTANCE:SCHEMA:T1,T2,..."` (repeatable, for multi-source) — the main one.
  Flags: `--data-serve-mode {connect_live|in_memory|hybrid}`, `--dictionary`, `--erd`, `--attr-cols`, `--metric-cols`, `--skip-relationships`, `--security-filter 'NAME=qual|USER,USER'`, `--grant 'trusteeId:rights[:user|user_group]'`, `--deny 'trusteeId:rights[:user|user_group]'`, `--translate 'objectId[:SubType]:locale[:field]=text'`, `--certify`, `--publish`.
- `build-from-config --config spec.yaml` — declarative JSON/YAML build; accepts `dictionary`, `data_dictionary`, `erd`, and `erds` paths (see `reference_mosaic_config_schema.md`).

**Quality gate (run after every build, and before publish/certify):**
- `validate-model --model-id M [--fact-tables TBL,TBL] [--strict-orphans] [--diff-against OTHER_ID] [--json]` — enforces the rules in `feedback_mosaic_build_quality.md` via the checks catalogued in `reference_mosaic_build_validation.md`. Emits FAIL/WARN summary + optional JSON report, exits non-zero on failures. `--diff-against` flags count regressions (attributes/metrics/relationships dropping vs a prior model id).

**User/admin ops:**
- `create-users --file users.csv` — dry-run user creation from CSV/JSON/YAML; use `--check-existing` to resolve duplicates during dry-run.
- `create-users --file users.csv --yes` — creates via `POST /api/users`; optional email column creates `/api/users/{id}/addresses`. Default password can come from `MSTR_NEW_USER_PASSWORD`.
- `patch-model-object --kind legacy_attribute|attribute|fact_metric|... --json-file patch.json --before-out before.json --yes` — changeset-backed object update with before/after verification.

**Individual lifecycle ops (operate on existing models):**
- `set-serve-mode --model-id M --mode {connect_live|in_memory|hybrid}`
- `publish --model-id M`  (for in-memory cubes; tries `POST /api/cubes/{modelId}` first)
- `refresh --model-id M --refresh-type {update|add|replace|incremental}`
- `delete-model --model-id M`
- `set-acl --model-id M --object-id O --sub-type fact_metric --grant 'trusteeId:rights' --deny 'trusteeId:rights'`
- `add-security-filter --model-id M --spec 'NAME=qual|USER,USER'`
- `translate --model-id M --entry 'objectId[:subType]:locale[:name|description]=text'`
- `certify --object-id O`

**Metric authoring ops:**
- `create-transformation --model-id M --name N --member 'attributeId=offset'` — e.g. `=-1` for prior period.
- `create-compound-metric --model-id M --name N --formula 'METRIC_ID1 - METRIC_ID2'`
- `create-conditional-metric --model-id M --name N --source-metric M --filter F`
- `attach-transformation --model-id M --name N --source-metric M --transformation T`
