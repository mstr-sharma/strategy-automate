# strategy-automate

A one-stop **Strategy** (formerly MicroStrategy) automation brain for AI coding assistants. The repo is built toward complete platform automation wherever Strategy exposes an API, SDK, MCP, CLI, or reproducible hook: Mosaic models, legacy semantic-layer migration, runtime analytics, cubes/datasets, security/governance, platform admin, AI agents, and data validation — driven from natural-language requests.

Tested with **Claude Code** and **Codex CLI**. Other harnesses (MCP-aware chat apps, Gemini CLI, Grok, Ollama, Cursor/Cline/Continue/Aider) are supported by design — the skills and memory are plain Markdown + Python and every per-LLM shim points at `AGENTS.md` — but have not been exercised end-to-end yet.

## What's in here

```
strategy-automate/
├── skill/                         # build-mosaic-model skill + helper scripts
│   ├── SKILL.md
│   ├── examples/
│   │   ├── model_plan_template.yaml
│   │   ├── attribute_plan_template.yaml
│   │   ├── relationship_plan_template.yaml
│   │   └── validation_suite_template.yaml
│   └── scripts/
│       ├── build_mosaic.py             # REST CLI: auth, catalog, build, patch, publish
│       ├── strategy_mosaic_inventory.py  # walk every Mosaic data model (subType 779)
│       ├── strategy_semantic_inventory.py  # walk classic attributes/facts/metrics/…
│       ├── strategy_semantic_mine.py   # top-down / reverse lineage for legacy → Mosaic
│       ├── strategy_validate_models.py  # compare model result sets to trusted references
│       └── strategy_validate.py        # live-tenant workflow validator
├── strategy-data-modeling/SKILL.md # modeling-planning layer before build / migration / review
├── strategy-automation/SKILL.md   # NLQ router — pick the right surface + memory
├── strategy-validation/SKILL.md   # paired-query data-correctness validator
├── memory/                        # MEMORY.md index + typed memory files
├── AGENTS.md                      # canonical, LLM-agnostic entry point
├── CLAUDE.md CODEX.md GEMINI.md   # thin per-LLM shims (all point to AGENTS.md)
├── GROK.md OLLAMA.md CURSOR.md    # additional LLM shims
├── .env.example                   # env-var template
└── README.md
```

## Setup

### 1. Clone and configure

```bash
git clone <this-repo> strategy-automate
cd strategy-automate
cp .env.example .env
# edit .env with your Library URL, username, password, project name/ID, dest folder
set -a; source .env; set +a
```

Required: `MSTR_BASE`, `MSTR_USER`, `MSTR_PASSWORD`, and either `MSTR_PROJECT_ID` or `MSTR_PROJECT_NAME`. For building new Mosaic models also set `MSTR_DEST_FOLDER_ID`. See `memory/reference_strategy_env.md` for the full list.

### 2. Install Python deps

```bash
python3 -m pip install --user requests
```

That's it. All other scripts work with the standard library. If your default Python is Anaconda and you see SSL handshake timeouts against your tenant, switch to `/usr/bin/python3`.

### 3. Verify tenant connectivity

```bash
python3 skill/scripts/build_mosaic.py auth-probe
python3 skill/scripts/build_mosaic.py list-datasources
```

### 4. Wire the repo into your AI tool

The repo is **LLM-agnostic**. `AGENTS.md` is the canonical entry point and every tool-specific shim at the repo root (`CLAUDE.md`, `CODEX.md`, `GEMINI.md`, `GROK.md`, `OLLAMA.md`, `CURSOR.md`) points there.

| Harness | Entry file | Notes |
|---|---|---|
| Claude Code | [`CLAUDE.md`](CLAUDE.md) | Skills auto-discovered via `SKILL.md` frontmatter; memory auto-loaded from `memory/MEMORY.md`. |
| OpenAI Codex CLI | [`CODEX.md`](CODEX.md) | Reads `AGENTS.md` on `cd`; skills loaded on demand. |
| Google Gemini CLI | [`GEMINI.md`](GEMINI.md) | Same contract as Codex. |
| xAI Grok / Grok Code | [`GROK.md`](GROK.md) | Each `SKILL.md` treated as long-form instruction. |
| Ollama local models | [`OLLAMA.md`](OLLAMA.md) | Includes a bootstrap system-prompt template for harnesses that don't auto-load Markdown. |
| Cursor / Cline / Continue / Aider / Windsurf | [`CURSOR.md`](CURSOR.md) | Point IDE agent at `AGENTS.md` as rules file. |
| Any other LLM | [`AGENTS.md`](AGENTS.md) | No configuration needed — read the file + memory index and proceed. |

**MCP-aware chat apps** — connect the Strategy Mosaic MCP server (whatever connector your vendor provides) to get `get_projects`, `get_mosaic_models`, `get_semantics`, `query`. The memory and skills reference those tools by name; any correctly-configured MCP session works. Without MCP, every tool has a REST fallback documented in `AGENTS.md`.

## Typical tasks

**Build a new Mosaic model from warehouse tables:**
```
Build a mosaic model. Instance: <your datasource name>
Schema: <schema>
Tables: <comma-separated>
```
Route through `strategy-data-modeling/SKILL.md` first when the business process, grain, dimensions, facts, relationships, hierarchies, or validation scope still need to be decided. The `build-mosaic-model` skill then discovers columns, generates attribute / metric / relationship payloads, commits through a changeset, and applies consumer-grade naming. See `skill/SKILL.md`.

For **multi-DB or mixed-case** builds (e.g., Postgres lowercase + Snowflake uppercase), auto-conformance silently orphans case-mismatched or differently-named FKs, and relationship PUTs then fail with `8004ccdb` / `8004ccc7`. Follow the six-step recipe in [`memory/feedback_mosaic_relationship_wiring.md`](memory/feedback_mosaic_relationship_wiring.md): write the attribute plan first, express conformance via identical `name` in the dictionary, declare relationships only between attributes that do NOT already share a table, verify `forms[*].expressions[*].tables` after build, PATCH missing expressions before issuing relationship PUTs, and close with a Trino rollup check.

**Inspect every Mosaic model in a project:**
```bash
python3 skill/scripts/strategy_mosaic_inventory.py --workers 12
```
Writes structured JSON to `/tmp`. Portfolio rollups + per-model attributes, metrics, relationships, security filters. See `memory/reference_strategy_mosaic_field_study.md`.

**Mine a classic project for Mosaic candidates:**
```bash
python3 skill/scripts/strategy_semantic_mine.py --mode top-down --report "Revenue Report"
python3 skill/scripts/strategy_semantic_mine.py --mode reverse --table LU_PRODUCT
```
See `memory/reference_strategy_legacy_to_mosaic_mining.md`.

**Validate a model's numbers:**
Route through the `strategy-validation` skill (`strategy-validation/SKILL.md`). Reference source can be another Mosaic model, a classic project report, a flat file, direct warehouse SQL, or a saved REST fixture. See `memory/reference_strategy_data_validation.md` for the 5-query minimum suite.

**Review or design a semantic model before building it:**
Route through `strategy-data-modeling/SKILL.md`. It turns free-form modeling requests into a reusable plan covering business process, grain, attributes, facts, metrics, relationships, hierarchies, time roles, security notes, and validation checks, with templates in `skill/examples/`.

**Automate an API surface that has no typed helper yet:**
```bash
python3 skill/scripts/build_mosaic.py openapi-search "<domain word>" --context 3
python3 skill/scripts/build_mosaic.py api-call --method GET --path /api/projects
```
Generic REST reachability is part of the platform hook coverage. Add typed helpers when a workflow becomes common, risky, multi-step, or needs strict verification/cleanup.

## What lives in memory

`memory/MEMORY.md` is the index. Each pointed-to file captures durable knowledge — tenant-agnostic patterns, modeling foundations, REST endpoint maps, gotchas, consumer-grade naming rules, the classic ↔ Mosaic translation matrix, and validation guidance. Read the index once to orient; load specific files on demand.

## Security

- **No hardcoded credentials or tenant IDs** in the repo. `grep -r MSTR_PASSWORD` only finds the env-var name.
- `.env` is gitignored; `.env.example` is the template.
- Security filters in build scripts are **opt-in and parameterized** — no example usernames.
- Read-only discovery helpers write raw tenant payloads only to `/tmp`, never to the repo.

## Conventions

- **Every script reads env vars or CLI flags.** No tenant defaults baked in.
- **Modeling plans come before metadata writes.** For model design, review, or migration work, declare business process, grain, facts, dimensions, relationships, hierarchies, and validation before calling build helpers.
- **Automation coverage is explicit.** Classify each platform capability as wrapped helper, generic REST hook, specialized hook, captured fallback, or known gap. See `memory/reference_strategy_automation_coverage.md`.
- **Every Mosaic build closes with a consumer-grade-naming pass + data validation, or an explicit validation-pending comparator note.** Validation is reference-dependent: another Mosaic model, a classic report/model, warehouse SQL, a flat file, or an external system can be the comparator. See `memory/feedback_consumer_grade_naming.md` and `strategy-validation/SKILL.md`.
- **Changesets are the unit of metadata write.** Open, write, commit — or discard on failure. Relationships, ACLs, translations typically need a separate changeset from object creation.
- **Tenant-specific discoveries get written into memory.** When a script's endpoint 404s, probe `/api/openapi.yaml` via `openapi-search`, fix the script, and update the memory file.
- **Do not chain `build → publish → add-security-filter → set-acl` as separate shell invocations on Strategy ONE Cloud tenants.** The project-interactive iServer sessions accumulate across invocations and won't reap on `DELETE /api/auth/login` — they only release on a ~30-min idle timer. Fold post-build ops into a single process (use `build-from-config` or an inline Python block). See [`memory/feedback_build_mosaic_session_leak.md`](memory/feedback_build_mosaic_session_leak.md) for the budget rules and the `-2147072486` / `8004cb0a` failure signature.

## Contributing

1. New endpoint or workflow → first prove the hook with `openapi-search` + read-only `api-call`; add a subcommand to `skill/scripts/build_mosaic.py` when it deserves a typed helper, then update `skill/SKILL.md`.
2. New durable knowledge → add a memory file with `name/description/type` frontmatter, then point to it from `memory/MEMORY.md`.
3. New platform surface or known gap → update `memory/reference_strategy_automation_coverage.md` and `memory/reference_strategy_task_catalog.md`.
4. New skill surface → sibling directory with a `SKILL.md`; add routing in `strategy-automation/SKILL.md` so other sessions find it.
5. Don't commit tenant IDs, usernames, passwords, or personal names.

## License

MIT (or internal use, per your org's policy).
