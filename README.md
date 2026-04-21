# strategy-automation

A one-stop **Strategy** (formerly MicroStrategy) automation brain for AI coding assistants. Everything needed to stand up Mosaic models, inspect and migrate legacy semantic-layer content, validate data correctness, and run admin tasks — end-to-end against any Strategy Cloud tenant, driven from natural-language requests.

Tested with **Claude Code**, **Codex CLI**, and MCP-aware chat apps. The skills and memory are plain Markdown + Python — transportable across any tool that understands skill-style instructions and can run CLI scripts.

## What's in here

```
strategy-automate/
├── skill/                         # build-mosaic-model skill + helper scripts
│   ├── SKILL.md
│   └── scripts/
│       ├── build_mosaic.py             # REST CLI: auth, catalog, build, patch, publish
│       ├── strategy_mosaic_inventory.py  # walk every Mosaic data model (subType 779)
│       ├── strategy_semantic_inventory.py  # walk classic attributes/facts/metrics/…
│       ├── strategy_semantic_mine.py   # top-down / reverse lineage for legacy → Mosaic
│       └── strategy_validate.py        # live-tenant workflow validator
├── strategy-automation/SKILL.md   # NLQ router — pick the right surface + memory
├── strategy-validation/SKILL.md   # paired-query data-correctness validator
├── memory/                        # MEMORY.md index + 27 typed memory files
├── AGENTS.md                      # entry point for Codex-style agents
├── GEMINI.md                      # entry point for Gemini CLI
├── .env.example                   # env-var template
└── README.md
```

## Setup

### 1. Clone and configure

```bash
git clone <this-repo> strategy-automation
cd strategy-automation
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

**Claude Code** — drop or symlink the repo under a project that Claude Code sees. The skills in `skill/`, `strategy-automation/`, `strategy-validation/` are auto-discovered by their `SKILL.md` frontmatter. The `memory/` directory is the durable knowledge base (structured per Claude Code's auto-memory conventions in `memory/MEMORY.md`).

**Codex CLI** — `AGENTS.md` at repo root is the entry point. Codex reads it when you `cd` into the repo. Everything under `memory/` and the `SKILL.md` files are referenced from `AGENTS.md`.

**Gemini CLI** — `GEMINI.md` at repo root points to the same content.

**Cursor / Cline / Continue** — open the repo as your workspace. Point your agent at `AGENTS.md` as the primary instruction file, or source the memory files explicitly in the system prompt.

**MCP-aware chat apps** — connect the Strategy Mosaic MCP server (whatever connector your vendor provides) to get `get_projects`, `get_mosaic_models`, `get_semantics`, `query`. The memory and skills reference those tools by name; any correctly-configured MCP session works.

## Typical tasks

**Build a new Mosaic model from warehouse tables:**
```
Build a mosaic model. Instance: <your datasource name>
Schema: <schema>
Tables: <comma-separated>
```
The `build-mosaic-model` skill discovers columns, generates attribute/metric/relationship payloads, commits through a changeset, and applies consumer-grade naming. See `skill/SKILL.md`.

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

## What lives in memory

`memory/MEMORY.md` is the index. Each pointed-to file captures durable knowledge — tenant-agnostic patterns, REST endpoint maps, gotchas, consumer-grade naming rules, the classic ↔ Mosaic translation matrix, etc. Read the index once to orient; load specific files on demand.

## Security

- **No hardcoded credentials or tenant IDs** in the repo. `grep -r MSTR_PASSWORD` only finds the env-var name.
- `.env` is gitignored; `.env.example` is the template.
- Security filters in build scripts are **opt-in and parameterized** — no example usernames.
- Read-only discovery helpers write raw tenant payloads only to `/tmp`, never to the repo.

## Conventions

- **Every script reads env vars or CLI flags.** No tenant defaults baked in.
- **Every Mosaic build closes with a consumer-grade-naming pass + data validation.** See `memory/feedback_consumer_grade_naming.md` and `strategy-validation/SKILL.md`.
- **Changesets are the unit of metadata write.** Open, write, commit — or discard on failure. Relationships, ACLs, translations typically need a separate changeset from object creation.
- **Tenant-specific discoveries get written into memory.** When a script's endpoint 404s, probe `/api/openapi.yaml` via `openapi-search`, fix the script, and update the memory file.

## Contributing

1. New endpoint or workflow → add a subcommand to `skill/scripts/build_mosaic.py`, then update `skill/SKILL.md`.
2. New durable knowledge → add a memory file with `name/description/type` frontmatter, then point to it from `memory/MEMORY.md`.
3. New skill surface → sibling directory with a `SKILL.md`; add routing in `strategy-automation/SKILL.md` so other sessions find it.
4. Don't commit tenant IDs, usernames, passwords, or personal names.

## License

MIT (or internal use, per your org's policy).
