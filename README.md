# strategy-automate

A **Strategy** (formerly MicroStrategy) automation brain for AI coding assistants — every part of the platform that exposes an API, SDK, MCP, CLI, or reproducible hook. Covers Mosaic data-model creation and modification, classic semantic-layer inspection and migration, runtime analytics, cubes and datasets, security and governance, platform admin, AI agents, and data validation.

**Kimball-first by default.** Strategy's SQL engine is built for star / snowflake / galaxy schemas with conformed dimensions. Every modeling workflow in this repo declares topology (`star | snowflake | galaxy | bridge-heavy | non-Kimball`) and classifies each input table (`fact | dim | bridge | snowflake_parent_dim | degenerate_dim | noise`) before writing any payload. Non-Kimball shapes stop-and-confirm with the user.

Tested with **Claude Code** and **Codex CLI**. Every other harness (Gemini CLI, Grok, Ollama, Cursor / Cline / Continue / Aider, MCP-aware chat apps) is supported by design — skills + memory are plain Markdown + Python, and every per-LLM shim at the repo root points at [`AGENTS.md`](AGENTS.md).

## How agents route work

The cold-start routing tree, the strict skill-precedence chain, and all operating rules live in [`AGENTS.md`](AGENTS.md) — maintained there only. In one line: `strategy-automation` classifies the surface, `strategy-data-modeling` plans the model, `skills/build-mosaic-model/SKILL.md` executes via REST, `strategy-validation` verifies the numbers, and on any Strategy error code the first stop is [`memory/reference_strategy_error_codes.md`](memory/reference_strategy_error_codes.md).

## Repo layout

```
strategy-automate/
├── AGENTS.md                      # canonical LLM-agnostic entry point
├── CLAUDE.md CODEX.md GEMINI.md   # thin per-LLM shims (all point to AGENTS.md)
├── GROK.md OLLAMA.md CURSOR.md    # additional harness shims
├── README.md .env.example         # human setup + env-var template
├── memory/                        # durable knowledge, indexed by MEMORY.md
│   ├── MEMORY.md                  # flat index — grep or scan to find the right file
│   ├── reference_strategy_error_codes.md    # error code → memory with the fix
│   ├── reference_data_modeling_foundations.md  # Kimball foundations (all design sections)
│   ├── reference_mosaic_*.md                # Mosaic payload shapes, publish, ACL, SF
│   ├── reference_strategy_*.md              # surface matrix, env, OpenAPI, legacy, etc.
│   ├── feedback_*.md                        # durable fixes learned from failures
│   └── checklist_*.md                       # modeling playbook + review gate
├── skills/
│   ├── build-mosaic-model/        # the execution skill
│   │   ├── SKILL.md
│   │   ├── examples/              # model_plan / attribute_plan / relationship_plan / validation_suite templates
│   │   └── scripts/
│   │       ├── _client.py               # shared BaseMSTR, auth args, search, inventory helpers
│   │       ├── build_mosaic.py          # subcommands for auth, catalog, build, publish, wire-relationships, SF, ACL, translate, validate-model, … (see --help)
│   │       ├── mosaic_safety.py         # stateless defensive helpers (error parsing, expression builders, merge-aware relationship PUT)
│   │       ├── preflight_model_check.py
│   │       ├── schema_object_translator.py    # classic schema objects → Mosaic payload translation
│   │       ├── strategy_mosaic_inventory.py   # walk every Mosaic data model (subType 779)
│   │       ├── strategy_semantic_inventory.py # walk classic attrs / facts / metrics / filters / hierarchies
│   │       ├── strategy_semantic_mine.py      # top-down / reverse lineage for legacy → Mosaic
│   │       ├── strategy_validate_models.py    # file-adapter + live Mosaic-to-Mosaic Trino diff
│   │       └── strategy_validate.py           # live-tenant runtime-workflow validator
│   ├── strategy-data-modeling/SKILL.md   # Kimball-first planning layer
│   ├── strategy-automation/SKILL.md      # NLQ router + surface classifier
│   └── strategy-validation/SKILL.md      # paired-query numeric-correctness validator
├── tests/                         # hermetic unit tests (run in CI)
├── captures/                      # dated tenant transcripts; raw payloads stay local
├── pyproject.toml LICENSE         # deps + lint config; MIT
└── .github/workflows/tests.yml   # CI: unittest + ruff
```

## Setup

### 1. Clone + configure env

```bash
git clone <this-repo> strategy-automate
cd strategy-automate
cp .env.example .env
# edit .env with your Library URL, username, password, project name/ID, dest folder
set -a; source .env; set +a
```

Required: `MSTR_BASE`, `MSTR_USER`, `MSTR_PASSWORD`, and either `MSTR_PROJECT_ID` or `MSTR_PROJECT_NAME`. For building new Mosaic models, also set `MSTR_DEST_FOLDER_ID`. Full env-var list in [`memory/reference_strategy_env.md`](memory/reference_strategy_env.md).

### 2. Install Python deps

```bash
python3 -m pip install --user requests
```

`requests` is the only non-stdlib dependency, declared in [`pyproject.toml`](pyproject.toml) (dependency declaration only — scripts stay directly runnable, no install required). Optionally add `PyYAML` for YAML configs (used by `build-from-config` and other `--file *.yaml` inputs); without it the scripts fall back to a `ruby -ryaml` one-liner for YAML parsing. If your default Python is Anaconda and you see SSL-handshake timeouts against your tenant, switch to `/usr/bin/python3` — some Anaconda builds ship an old OpenSSL that hangs on Strategy Cloud TLS.

### 3. Verify tenant connectivity

```bash
python3 skills/build-mosaic-model/scripts/build_mosaic.py auth-probe
python3 skills/build-mosaic-model/scripts/build_mosaic.py list-datasources
```

### 4. Wire the repo into your AI tool

The repo is **LLM-agnostic**. [`AGENTS.md`](AGENTS.md) is the canonical entry point; every shim at the repo root points there.

| Harness | Entry file | Notes |
|---|---|---|
| Claude Code | [`CLAUDE.md`](CLAUDE.md) | `CLAUDE.md` is auto-loaded and routes to `AGENTS.md`; skills + memory are read on demand. |
| OpenAI Codex CLI | [`CODEX.md`](CODEX.md) | Reads `AGENTS.md` on `cd`; skills loaded on demand. |
| Google Gemini CLI | [`GEMINI.md`](GEMINI.md) | Same contract as Codex. |
| xAI Grok / Grok Code | [`GROK.md`](GROK.md) | Each `SKILL.md` treated as long-form instruction. |
| Ollama local models | [`OLLAMA.md`](OLLAMA.md) | Bootstrap system-prompt template for harnesses that don't auto-load Markdown. |
| Cursor / Cline / Continue / Aider / Windsurf | [`CURSOR.md`](CURSOR.md) | Point IDE agent at `AGENTS.md` as the rules file. |
| Any other LLM | [`AGENTS.md`](AGENTS.md) | No configuration needed — read the file + memory index and proceed. |

**MCP-aware chat apps** — connect the Strategy Mosaic MCP server (per your vendor's connector). The memory and skills reference MCP tools by standard name: `get_projects`, `get_mosaic_models`, `get_semantics`, `query`. Without MCP, every tool has a REST fallback documented in [`AGENTS.md`](AGENTS.md).

## Typical tasks

### Build a new Mosaic model from warehouse tables

```
Build a mosaic model. Instance: <your datasource name>
Schema: <schema>
Tables: <T1>, <T2>, <T3>
```

For multi-DB builds (e.g., Postgres + Snowflake), route through [`skills/strategy-data-modeling/SKILL.md`](skills/strategy-data-modeling/SKILL.md) first — declare conformed dims, classify tables, pick the topology before hitting REST. Case-mismatch FKs (`<entity>_id` vs `<ENTITY>_ID`) and semantically-same-but-differently-named FKs (`primary_<entity>_id` vs `<entity>_id`) silently break auto-conformance unless you pass `--conformance-map` or `--fk-map` to `build`. See [`memory/feedback_mosaic_relationship_wiring.md`](memory/feedback_mosaic_relationship_wiring.md) for the six-step recipe.

End-to-end chain in a single Python process (avoids session-cap trips — see [`memory/feedback_build_mosaic_session_leak.md`](memory/feedback_build_mosaic_session_leak.md)):

```bash
python3 skills/build-mosaic-model/scripts/build_mosaic.py build-from-config --config model-spec.yaml
# or
python3 skills/build-mosaic-model/scripts/build_mosaic.py build \
  --name "Sales Mosaic" \
  --source "Snowflake Prod:SALES:CUSTOMER,ORDER,LINEITEM" \
  --dictionary /tmp/sales.dict.json \
  --conformance-map /tmp/sales.conformance.json
```

### Post-build relationship wiring with pre-flight validation

For multi-DB or mixed-case builds where auto-conformance leaves orphan FKs:

```bash
python3 skills/build-mosaic-model/scripts/build_mosaic.py wire-relationships \
  --model-id <model_id> \
  --hints /tmp/fk-hints.json \
  --dry-run
```

Validates step-3 (self-reference → `8004ccdb`) and step-5 (relationship_table prerequisite → `8004ccc7`) before issuing any PUT; skips PUTs that would fail and reports which ones need attribute merges first.

### Publish an in-memory Mosaic model (same process as build)

```bash
python3 skills/build-mosaic-model/scripts/build_mosaic.py publish --model-id <model_id> --skip-classify
```

`--skip-classify` bypasses the `GET /api/objects/{id}?type=3` surface check when you already know the target is a Mosaic model — saves one project-scoped call against the session cap when chaining build → publish.

### Validate a model's numbers

File adapter (dump rows from any comparator, then diff):

```bash
python3 skills/build-mosaic-model/scripts/strategy_validate_models.py \
  --model-file /tmp/model_rows.csv \
  --reference-file /tmp/reference_rows.csv \
  --key region,nation --measures revenue,orders \
  --out /tmp/validation.json
```

Live Mosaic-to-Mosaic (via Trino, no external files):

```bash
python3 skills/build-mosaic-model/scripts/strategy_validate_models.py \
  --model "<new_model>" --reference-mosaic "<reference_model>" \
  --query 'SELECT "region (region name)", SUM("revenue") FROM %s GROUP BY 1' \
  --key 'region (region name)' --measures revenue \
  --out /tmp/validation.json
```

See [`skills/strategy-validation/SKILL.md`](skills/strategy-validation/SKILL.md) and [`memory/reference_strategy_data_validation.md`](memory/reference_strategy_data_validation.md) for the 5-query minimum suite, the 10-check design suite, comparator-source decision matrix, and failure-triage mapped to Kimball root causes.

### Inspect every Mosaic model in a project

```bash
python3 skills/build-mosaic-model/scripts/strategy_mosaic_inventory.py --workers 12
```

Writes structured JSON to `/tmp`. Portfolio rollups + per-model attributes, metrics, relationships, security filters, external-data-model links.

### Mine a classic project for Mosaic candidates

```bash
python3 skills/build-mosaic-model/scripts/strategy_semantic_mine.py --mode top-down --report "Revenue Report"
python3 skills/build-mosaic-model/scripts/strategy_semantic_mine.py --mode reverse --table LU_PRODUCT
```

See [`memory/reference_strategy_legacy_to_mosaic_mining.md`](memory/reference_strategy_legacy_to_mosaic_mining.md) — it's the start-here hub for classic → Mosaic migrations (4-step sequence: mining → field-study → blueprint/clone decision → build).

### Automate an API surface that has no typed helper yet

```bash
python3 skills/build-mosaic-model/scripts/build_mosaic.py openapi-search "<domain word>" --context 3
python3 skills/build-mosaic-model/scripts/build_mosaic.py api-call --method GET --path /api/projects
```

Generic REST reachability is part of platform-hook coverage. Promote to a typed helper when the workflow becomes common, risky, multi-step, or needs strict verification or cleanup.

## Memory, conventions, and security

Durable knowledge lives in `memory/` — [`memory/MEMORY.md`](memory/MEMORY.md) is the one-line-per-file index, and each file carries `type:` frontmatter (`user` / `project` / `reference` / `feedback`). The operating rules agents follow — Kimball-first planning, changesets as the unit of write, one-session-one-process, error-code-grep-first, the consumer-grade-naming ship bar, and the generalization/scrub rules — are maintained in [`AGENTS.md`](AGENTS.md) → "Operating rules", not here.

Security posture for humans: no hardcoded credentials, tenant IDs, or industry-specific content anywhere in durable text (`.env` is gitignored, `.env.example` is the template); raw tenant payloads go to `/tmp` or `captures/<date>-<topic>/`, never into memory files. See [`memory/feedback_generalize_durable_artifacts.md`](memory/feedback_generalize_durable_artifacts.md) for the scrub checklist.

## Contributing

1. **New endpoint or workflow** → prove the hook with `openapi-search` + read-only `api-call`; add a subcommand to [`skills/build-mosaic-model/scripts/build_mosaic.py`](skills/build-mosaic-model/scripts/build_mosaic.py) when it deserves a typed helper; update [`memory/reference_mosaic_build_skill.md`](memory/reference_mosaic_build_skill.md) and the relevant `SKILL.md`.
2. **New durable knowledge** → add a memory file with `name` / `description` / `type` frontmatter, then point to it from [`memory/MEMORY.md`](memory/MEMORY.md). Cite code by function/subcommand name, never line numbers. New error codes MUST add a row to [`memory/reference_strategy_error_codes.md`](memory/reference_strategy_error_codes.md).
3. **New platform surface or known gap** → update [`memory/reference_strategy_automation_coverage.md`](memory/reference_strategy_automation_coverage.md) and [`memory/reference_strategy_task_catalog.md`](memory/reference_strategy_task_catalog.md).
4. **New skill surface** → new directory under `skills/` with a `SKILL.md`; add routing in [`skills/strategy-automation/SKILL.md`](skills/strategy-automation/SKILL.md) so other sessions find it. Skills must stay one-way (classify → plan → build → verify).
5. **Dated tenant-specific content** goes under `captures/<YYYY-MM-DD>-<topic>/`, not in memory.
6. **Do not commit** tenant IDs, usernames, passwords, personal names, or industry-specific terminology (see generalization rule above).

## License

MIT — see [LICENSE](LICENSE).
