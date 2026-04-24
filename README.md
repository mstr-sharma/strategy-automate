# strategy-automate

A **Strategy** (formerly MicroStrategy) automation brain for AI coding assistants — every part of the platform that exposes an API, SDK, MCP, CLI, or reproducible hook. Covers Mosaic data-model creation and modification, classic semantic-layer inspection and migration, runtime analytics, cubes and datasets, security and governance, platform admin, AI agents, and data validation.

**Kimball-first by default.** Strategy's SQL engine is built for star / snowflake / galaxy schemas with conformed dimensions. Every modeling workflow in this repo declares topology (`star | snowflake | galaxy | bridge-heavy | non-Kimball`) and classifies each input table (`fact | dim | bridge | snowflake_parent_dim | degenerate_dim | noise`) before writing any payload. Non-Kimball shapes stop-and-confirm with the user.

Tested with **Claude Code** and **Codex CLI**. Every other harness (Gemini CLI, Grok, Ollama, Cursor / Cline / Continue / Aider, MCP-aware chat apps) is supported by design — skills + memory are plain Markdown + Python, and every per-LLM shim at the repo root points at [`AGENTS.md`](AGENTS.md).

## Skill precedence (one-way, no loops)

```
User task → which branch?
0. Error code in the transcript (8004…, iServerCode -2147…)?
     → memory/reference_strategy_error_codes.md   (symptom → fix)
1. Building a NEW semantic model?
     → strategy-data-modeling/SKILL.md   (plan grain, dims, conformance, topology)
     → skill/SKILL.md                    (execute via build_mosaic.py)
     → strategy-validation/SKILL.md      (verify numbers)
2. Modifying an existing model / admin / runtime task?
     → strategy-automation/SKILL.md      (NLQ router)
3. Legacy (classic) → Mosaic migration?
     → memory/reference_strategy_legacy_to_mosaic_mining.md (start-here hub)
     → strategy-data-modeling → skill/SKILL.md
4. Unknown endpoint / unfamiliar payload shape?
     → build_mosaic.py openapi-summary / openapi-search
     → memory/reference_mosaic_clone_pattern.md
```

`strategy-automation` classifies the surface and hands off downward. `strategy-data-modeling` owns all planning. `skill/SKILL.md` executes. `strategy-validation` verifies. No skill calls back up the chain.

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
│   ├── reference_data_modeling_foundations.md  # Kimball foundations
│   ├── reference_mosaic_*.md                # Mosaic payload shapes, publish, ACL, SF, clone
│   ├── reference_strategy_*.md              # surface matrix, env, OpenAPI, legacy, etc.
│   ├── feedback_*.md                        # durable fixes learned from failures
│   └── checklist_*.md                       # pre-build / build / review gates
├── skill/                         # build-mosaic-model skill
│   ├── SKILL.md
│   ├── examples/                  # model_plan / attribute_plan / relationship_plan / validation_suite templates
│   └── scripts/
│       ├── _client.py               # shared BaseMSTR + payload helpers
│       ├── build_mosaic.py          # 32 subcommands: auth, catalog, build, publish, wire-relationships, SF, ACL, translate, validate-model, …
│       ├── preflight_model_check.py
│       ├── strategy_mosaic_inventory.py   # walk every Mosaic data model (subType 779)
│       ├── strategy_semantic_inventory.py # walk classic attrs / facts / metrics / filters / hierarchies
│       ├── strategy_semantic_mine.py      # top-down / reverse lineage for legacy → Mosaic
│       ├── strategy_validate_models.py    # file-adapter + live Mosaic-to-Mosaic Trino diff
│       └── strategy_validate.py           # live-tenant runtime-workflow validator
├── strategy-data-modeling/SKILL.md   # Kimball-first planning layer
├── strategy-automation/SKILL.md      # NLQ router + surface classifier
├── strategy-validation/SKILL.md      # paired-query numeric-correctness validator
└── captures/                      # raw tenant payloads, dated — NOT durable knowledge
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

`requests` is the only non-stdlib dependency. If your default Python is Anaconda and you see SSL-handshake timeouts against your tenant, switch to `/usr/bin/python3` — some Anaconda builds ship an old OpenSSL that hangs on Strategy Cloud TLS.

### 3. Verify tenant connectivity

```bash
python3 skill/scripts/build_mosaic.py auth-probe
python3 skill/scripts/build_mosaic.py list-datasources
```

### 4. Wire the repo into your AI tool

The repo is **LLM-agnostic**. [`AGENTS.md`](AGENTS.md) is the canonical entry point; every shim at the repo root points there.

| Harness | Entry file | Notes |
|---|---|---|
| Claude Code | [`CLAUDE.md`](CLAUDE.md) | Skills auto-discovered via `SKILL.md` frontmatter; memory auto-loaded from `memory/MEMORY.md`. |
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

For multi-DB builds (e.g., Postgres + Snowflake), route through [`strategy-data-modeling/SKILL.md`](strategy-data-modeling/SKILL.md) first — declare conformed dims, classify tables, pick the topology before hitting REST. Case-mismatch FKs (`<entity>_id` vs `<ENTITY>_ID`) and semantically-same-but-differently-named FKs (`primary_<entity>_id` vs `<entity>_id`) silently break auto-conformance unless you pass `--conformance-map` or `--fk-map` to `build`. See [`memory/feedback_mosaic_relationship_wiring.md`](memory/feedback_mosaic_relationship_wiring.md) for the six-step recipe.

End-to-end chain in a single Python process (avoids session-cap trips — see [`memory/feedback_build_mosaic_session_leak.md`](memory/feedback_build_mosaic_session_leak.md)):

```bash
python3 skill/scripts/build_mosaic.py build-from-config --config model-spec.yaml
# or
python3 skill/scripts/build_mosaic.py build \
  --name "Sales Mosaic" \
  --source "Snowflake Prod:SALES:CUSTOMER,ORDER,LINEITEM" \
  --dictionary /tmp/sales.dict.json \
  --conformance-map /tmp/sales.conformance.json
```

### Post-build relationship wiring with pre-flight validation

For multi-DB or mixed-case builds where auto-conformance leaves orphan FKs:

```bash
python3 skill/scripts/build_mosaic.py wire-relationships \
  --model-id <model_id> \
  --hints /tmp/fk-hints.json \
  --dry-run
```

Validates step-3 (self-reference → `8004ccdb`) and step-5 (relationship_table prerequisite → `8004ccc7`) before issuing any PUT; skips PUTs that would fail and reports which ones need attribute merges first.

### Publish an in-memory Mosaic model (same process as build)

```bash
python3 skill/scripts/build_mosaic.py publish --model-id <model_id> --skip-classify
```

`--skip-classify` bypasses the `GET /api/objects/{id}?type=3` surface check when you already know the target is a Mosaic model — saves one project-scoped call against the session cap when chaining build → publish.

### Validate a model's numbers

File adapter (dump rows from any comparator, then diff):

```bash
python3 skill/scripts/strategy_validate_models.py \
  --model-file /tmp/model_rows.csv \
  --reference-file /tmp/reference_rows.csv \
  --key region,nation --measures revenue,orders \
  --out /tmp/validation.json
```

Live Mosaic-to-Mosaic (via Trino, no external files):

```bash
python3 skill/scripts/strategy_validate_models.py \
  --model "<new_model>" --reference-mosaic "<reference_model>" \
  --query 'SELECT "region (region name)", SUM("revenue") FROM %s GROUP BY 1' \
  --key 'region (region name)' --measures revenue \
  --out /tmp/validation.json
```

See [`strategy-validation/SKILL.md`](strategy-validation/SKILL.md) and [`memory/reference_strategy_data_validation.md`](memory/reference_strategy_data_validation.md) for the 5-query minimum suite, the 10-check design suite, comparator-source decision matrix, and failure-triage mapped to Kimball root causes.

### Inspect every Mosaic model in a project

```bash
python3 skill/scripts/strategy_mosaic_inventory.py --workers 12
```

Writes structured JSON to `/tmp`. Portfolio rollups + per-model attributes, metrics, relationships, security filters, external-data-model links.

### Mine a classic project for Mosaic candidates

```bash
python3 skill/scripts/strategy_semantic_mine.py --mode top-down --report "Revenue Report"
python3 skill/scripts/strategy_semantic_mine.py --mode reverse --table LU_PRODUCT
```

See [`memory/reference_strategy_legacy_to_mosaic_mining.md`](memory/reference_strategy_legacy_to_mosaic_mining.md) — it's the start-here hub for classic → Mosaic migrations (4-step sequence: mining → field-study → blueprint/clone decision → build).

### Automate an API surface that has no typed helper yet

```bash
python3 skill/scripts/build_mosaic.py openapi-search "<domain word>" --context 3
python3 skill/scripts/build_mosaic.py api-call --method GET --path /api/projects
```

Generic REST reachability is part of platform-hook coverage. Promote to a typed helper when the workflow becomes common, risky, multi-step, or needs strict verification or cleanup.

## How memory is organized

`memory/MEMORY.md` is a flat one-line index, grouped by section (meta / Kimball foundations / Mosaic design-time / Mosaic runtime / build-quality feedback / classic + legacy / validation / captures). Load individual files on demand — `AGENTS.md` auto-loads the index; individual memory files are pulled in when they match the task.

Four memory types — each file carries `type:` frontmatter:

- **user** — operator profile and style preferences.
- **project** — repo charter and long-lived goals.
- **reference** — durable knowledge: payload shapes, endpoint maps, design foundations, object taxonomies, OpenAPI probe patterns, error-code index.
- **feedback** — durable fixes learned from failures: session cap, conformance gotchas, publish endpoint collision, form-naming rules, datatype traps, etc.

When a REST call 4xx/5xx, **grep [`memory/reference_strategy_error_codes.md`](memory/reference_strategy_error_codes.md) FIRST**. Every observed `8004cc##` / `iServerCode -2147…` maps to the memory file with the fix. Don't retry blind — all observed codes are class-of-error, not transient.

## Security + scrubbing

- **No hardcoded credentials or tenant IDs** in the repo. `grep -r MSTR_PASSWORD` only finds the env-var name.
- **No industry-specific content** in durable memory files. Skills / memory / scripts / examples must work against any Strategy tenant, any DB engine, any schema, any domain, any user identity. Concrete values (tenant IDs, user names, industry-specific entities) belong in env vars, CLI flags, user-supplied inputs, or `captures/<date>-<topic>/` transcripts — never in durable text. See [`memory/feedback_generalize_durable_artifacts.md`](memory/feedback_generalize_durable_artifacts.md) for the scrub checklist.
- `.env` is gitignored; `.env.example` is the template.
- Security filters in build scripts are **opt-in and parameterized** — no example usernames.
- Read-only discovery helpers write raw tenant payloads only to `/tmp`, never to the repo.
- `captures/` contains dated tenant-specific transcripts. Raw payloads go there, not into memory.

## Conventions

- **Every script reads env vars or CLI flags.** No tenant defaults baked in.
- **Kimball first.** Classify every input table (`fact | dim | bridge | snowflake_parent_dim | degenerate_dim | noise`) and declare the overall topology before writing any payload. Non-Kimball shapes (EAV, one-big-table, graph) stop-and-confirm with the user. See [`memory/reference_data_modeling_foundations.md`](memory/reference_data_modeling_foundations.md).
- **On any Strategy REST 4xx/5xx, grep [`memory/reference_strategy_error_codes.md`](memory/reference_strategy_error_codes.md) FIRST.** Every observed error code maps to the memory file with the fix.
- **Modeling plans come before metadata writes.** For model design, review, or migration work, produce the business-logic translation artifact (entities, grain, conformed dims, attributes, metrics with additivity class, relationships, assumptions log) before calling build helpers. See [`memory/feedback_business_logic_pass_mandatory.md`](memory/feedback_business_logic_pass_mandatory.md).
- **One session, one process.** Never chain `build → publish → add-security-filter → set-acl` as separate shell invocations on Strategy ONE Cloud tenants — the iServer project-interactive sessions accumulate and won't reap on `DELETE /api/auth/login`. Use `build-from-config` or an inline Python block. See [`memory/feedback_build_mosaic_session_leak.md`](memory/feedback_build_mosaic_session_leak.md).
- **Automation coverage is explicit.** Classify each platform capability as wrapped helper, generic REST hook, specialized hook, captured fallback, or known gap. See [`memory/reference_strategy_automation_coverage.md`](memory/reference_strategy_automation_coverage.md).
- **Every Mosaic build closes with a consumer-grade-naming pass + data validation**, or an explicit validation-pending comparator note. Validation is reference-dependent: another Mosaic model, a classic report/model, warehouse SQL, a flat file, or an external system can be the comparator. See [`memory/feedback_consumer_grade_naming.md`](memory/feedback_consumer_grade_naming.md) and [`strategy-validation/SKILL.md`](strategy-validation/SKILL.md).
- **Changesets are the unit of metadata write.** Open → mutate → commit, or discard on failure. Relationships, ACLs, translations typically need a separate changeset from object creation.
- **Tenant-specific discoveries get written into memory.** When a script's endpoint 404s, probe `/api/openapi.yaml` via `openapi-search`, fix the script, and update the memory file.

## Contributing

1. **New endpoint or workflow** → prove the hook with `openapi-search` + read-only `api-call`; add a subcommand to [`skill/scripts/build_mosaic.py`](skill/scripts/build_mosaic.py) when it deserves a typed helper; update [`memory/reference_mosaic_build_skill.md`](memory/reference_mosaic_build_skill.md) and the relevant `SKILL.md`.
2. **New durable knowledge** → add a memory file with `name` / `description` / `type` frontmatter, then point to it from [`memory/MEMORY.md`](memory/MEMORY.md). New error codes MUST add a row to [`memory/reference_strategy_error_codes.md`](memory/reference_strategy_error_codes.md).
3. **New platform surface or known gap** → update [`memory/reference_strategy_automation_coverage.md`](memory/reference_strategy_automation_coverage.md) and [`memory/reference_strategy_task_catalog.md`](memory/reference_strategy_task_catalog.md).
4. **New skill surface** → sibling directory with a `SKILL.md`; add routing in [`strategy-automation/SKILL.md`](strategy-automation/SKILL.md) so other sessions find it. Skills must stay one-way (classify → plan → build → verify).
5. **Dated tenant-specific content** goes under `captures/<YYYY-MM-DD>-<topic>/`, not in memory.
6. **Do not commit** tenant IDs, usernames, passwords, personal names, or industry-specific terminology (see generalization rule above).

## License

MIT (or internal use per your org's policy).
