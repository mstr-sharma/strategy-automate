# AGENTS.md — canonical, LLM-agnostic entry point

You are operating inside the **strategy-automate** repo: a one-stop automation brain for **Strategy** (formerly MicroStrategy) that aims for complete platform automation wherever Strategy exposes an API, SDK, MCP, CLI, or reproducible hook. It covers Mosaic semantic models, the classic / legacy semantic layer, runtime analytics, cubes / datasets, platform admin, AI agents, and data validation.

This file is the **canonical cross-tool entry point**. Every LLM-specific shim at the repo root (`CLAUDE.md`, `GEMINI.md`, `CODEX.md`, `GROK.md`, `OLLAMA.md`, `CURSOR.md`, etc.) points here. If you are a model or tool not listed there, read this file + `memory/MEMORY.md` and proceed — nothing else is tool-specific.

**Harness assumptions (apply across LLMs):**
- The repo is plain Markdown + Python 3 (standard library + `requests`). No Anthropic-specific, OpenAI-specific, or Google-specific SDK calls — every helper is `requests` against Strategy REST or subprocess to `mstrio-py`.
- `SKILL.md` frontmatter (`name`, `description`) follows Anthropic's skill convention, but any harness that reads Markdown with YAML frontmatter can use it. A skill-unaware LLM can read each `SKILL.md` as a normal instruction file.
- `memory/MEMORY.md` is a flat index with one-line hooks; any LLM can `grep` or keyword-match to find the relevant memory file on demand.
- Shell helpers live in `skill/scripts/`. Invoke them via whatever tool-call mechanism your harness exposes (Bash, shell, execute_command, tool-use-bash, etc.).
- Credentials come from env vars (`MSTR_BASE`, `MSTR_USER`, `MSTR_PASSWORD`, `MSTR_PROJECT_ID`/`MSTR_PROJECT_NAME`, `MSTR_DEST_FOLDER_ID`) — see `memory/reference_strategy_env.md`. Never hardcode.

## Git workflow

- Operator configures their own remotes and git identity locally (`git remote -v`, `git config user.email`) — do not hardcode remote URLs or identities here.
- Default pull/push targets `origin`. Run `git pull --ff-only` before starting shared work and `git push` after commit.
- Before committing, run the relevant tests plus `git diff --check`.
- Never commit `.env`, `.claude/`, credentials, SSH keys, tenant IDs, raw tenant payloads, personal names, corporate email addresses, local logs, or anything else enumerated in `memory/feedback_generalize_durable_artifacts.md`.

## Cold-start routing — pick the right branch FIRST

```
User task → which branch?
0. Error code in the transcript (8004…, iServerCode -2147…)?
     → memory/reference_strategy_error_codes.md   (fastest path symptom → fix)
1. Building a NEW model?
     → strategy-data-modeling/SKILL.md  (plan grain, dims, conformance, topology)
     → skill/SKILL.md                  (execute via build_mosaic.py)
2. Modifying an existing model / admin / runtime task?
     → strategy-automation/SKILL.md    (NLQ router)
3. Validating numbers / checking data correctness?
     → strategy-validation/SKILL.md
4. Legacy (classic) → Mosaic migration?
     → memory/reference_strategy_legacy_to_mosaic_mining.md (start-here hub)
     → strategy-data-modeling/SKILL.md → skill/SKILL.md
5. Unknown endpoint / unfamiliar payload shape?
     → openapi-summary / openapi-search → clone-and-remap (reference_mosaic_clone_pattern.md)
```

**Skill precedence is strict: classify (automation) → plan (data-modeling) → execute (build) → verify (validation).** No skill routes back up the chain. `strategy-automation` and `strategy-data-modeling` do NOT route to each other in a loop.

**Kimball first on every modeling task.** Strategy's SQL engine is built for star / snowflake schemas and conformed dimensions. Declare topology (`star | snowflake | galaxy | bridge-heavy | non-Kimball`) and classify every table (fact / dim / bridge / snowflake-parent / degenerate / noise) BEFORE writing any payload. Non-Kimball topologies stop-and-confirm — see `memory/reference_data_modeling_foundations.md`.

## First move on any task

1. **Identify the surface.** Strategy concepts are duplicated across Mosaic and classic. Before touching endpoints, decide whether the user is asking about Mosaic data models, classic / project semantic layer, runtime analytics, cubes / datasets, AI agents, platform admin, or data validation. When uncertain, consult `memory/reference_strategy_surface_matrix.md`.
2. **Read the relevant memory file.** `memory/MEMORY.md` is the index — every other file has a `type` frontmatter (`user`, `project`, `feedback`, `reference`) and a one-line description. Load only the files you need.
3. **Use the skills when they fit** (precedence above).
   - `strategy-data-modeling/SKILL.md` — the modeling-planning layer: declare business process, grain, attributes, facts, metrics, relationships, hierarchies, time semantics, and validation before build / migration / review work.
   - `skill/SKILL.md` — the `build-mosaic-model` skill (discovery + build + ACL + security filter + publish + post-build edits).
   - `strategy-automation/SKILL.md` — the NLQ router: points you at the right memory + helper for any Strategy task.
   - `strategy-validation/SKILL.md` — paired-query data-correctness validation against any reference source.
4. **Use environment configuration, never hardcoded values.** `MSTR_BASE`, `MSTR_USER`, `MSTR_PASSWORD`, `MSTR_PROJECT_ID` or `MSTR_PROJECT_NAME`, `MSTR_DEST_FOLDER_ID`. See `.env.example` + `memory/reference_strategy_env.md`.
5. **Probe live specs when endpoint details matter.** `python3 skill/scripts/build_mosaic.py openapi-summary` and `... openapi-search "<term>"` hit `/api/openapi.yaml` directly.
6. **Classify automation coverage honestly.** Use `memory/reference_strategy_automation_coverage.md`: wrapped helper, generic REST hook, specialized hook, captured fallback, or known gap. Generic `api-call` reachability is an API hook, but not a finished workflow wrapper.
7. **On any REST failure, grep `memory/reference_strategy_error_codes.md` FIRST.** Every observed `8004cc##` / iServerCode maps to the memory file with the fix. Do not retry blind — all observed codes are class-of-error, not transient.

For Mosaic work, distinguish the entry path:
- **Modeling design / review first:** if the request is still deciding business process, grain, facts, dimensions, relationships, hierarchies, time semantics, or validation scope, route through `strategy-data-modeling/SKILL.md` before touching build helpers.
- **Legacy-to-Mosaic migration:** mine/read the classic semantic layer first, then use its attributes, forms, facts, metrics, relationships, filters, and reports as the blueprint for the new Mosaic model.
- **Brand-new Mosaic model:** start from warehouse discovery plus ERD/data dictionary/preflight checks, then build and validate against the best available comparator.

## Operating rules (apply to every tool)

- **Classify Mosaic vs legacy before every write.** Before hitting any endpoint that differs between the two families (publish, refresh, execute, serve-mode, ACL, security filter), call `GET /api/objects/{id}?type=3` and branch on `subtype`: 779 → Mosaic data model, 776 → classic Intelligent Cube, anything else → stop and classify further. See `memory/reference_mosaic_vs_legacy_surfaces.md` for the endpoint-pair cheat sheet. For publishing, `memory/reference_mosaic_publish_path.md` is canonical: both trigger paths work on a properly-typed Mosaic model (`POST /api/cubes/{id}?cubeAction=publish` is what the UI uses and the reliable trigger on the observed Strategy ONE Cloud family; the Modeling-native 3-step flow returns per-table status). Never trust the 202/204 alone — poll `publishStatus` (or probe the model via a Trino/MCP `count(*)` query) until tables are loaded before declaring success.
- **Consumer-grade naming is the ship bar.** Any model you build or modify must pass the checklist in `memory/feedback_consumer_grade_naming.md` — business-named attributes, non-empty form names, business-friendly descriptions, sensible metric formats, no hardcoded example usernames or personal names.
- **Every Mosaic build closes with data validation or an explicit pending note.** Route through `strategy-validation/SKILL.md`; validation is comparator-dependent, and the reference source can be another Mosaic model, a classic project report/model, a flat file, direct warehouse SQL, an external system/API, or a saved REST fixture (NOT Mosaic-to-Mosaic only). If no trusted comparator is available, say validation is pending and do not call the build shippable.
- **Changesets are the unit of write.** Open → mutate → commit, or discard on failure. Relationships / ACLs / translations typically require a separate changeset after object creation.
- **Preserve tenant-verified gotchas.** When a script's endpoint returns 404 or a payload shape changes, update both the script and the corresponding memory file. Never silently work around.
- **Never hardcode credentials, tenant IDs, or personal names.** Pull from env vars; parameterize security filters.
- **Keep every durable artifact generalizable.** Skills, memories, scripts, examples, and templates in this repo must work against *any* Strategy tenant, DB engine, schema, or domain — concrete tenant / DB / user / model values belong in env vars, CLI flags, user-supplied inputs, or `captures/`, never hardcoded into durable text. See `memory/feedback_generalize_durable_artifacts.md` for the scrub checklist and the self-audit grep.
- **Prefer `/usr/bin/python3`** on machines whose Anaconda Python has an older OpenSSL — TLS handshakes to some Strategy Cloud tenants hang otherwise.
- **For destructive operations** (deletes, force patches, migration commits), enumerate the target IDs and confirm before acting unless the user explicitly requested the destruction.

## Repo layout (quick reference)

- `memory/` — durable knowledge, indexed by `memory/MEMORY.md`.
- `skill/` — `build-mosaic-model` skill + all REST helper CLIs under `skill/scripts/`.
- `strategy-data-modeling/SKILL.md` — modeling-planning layer for grain, dimensions, metrics, relationships, hierarchies, and validation design.
- `strategy-automation/SKILL.md` — NLQ router.
- `strategy-validation/SKILL.md` — data-correctness validator.
- `.env.example` — env-var template (copy to `.env`).
- `README.md` — human setup guide, per-AI-tool onboarding.

## Memory index

`memory/MEMORY.md` is the authoritative index — one line per file, grouped by section. Grep or scan it on demand; do not maintain (or trust) a second list of memory files anywhere else, including here. The handful you will reach for constantly:

- `reference_strategy_error_codes.md` — every observed error code → the memory with the fix. Grep FIRST on any 4xx/5xx.
- `reference_strategy_env.md` — env-var + CLI-flag convention.
- `reference_strategy_surface_matrix.md` — route ambiguous nouns to the right surface (Mosaic vs classic vs runtime).
- `reference_data_modeling_foundations.md` — Kimball foundations backing every modeling decision.
- `reference_strategy_automation_coverage.md` — coverage levels and the gap register.
- `feedback_generalize_durable_artifacts.md` — the scrub checklist for anything you write back into the repo.

## MCP tools (configured separately per AI tool)

Each AI tool configures MCP servers through its own settings — this repo does NOT ship MCP server configuration. When a correctly-configured Mosaic MCP session exists, the following tool names are available and referenced by memory/skills:

- `get_projects` — list projects in the connected catalog.
- `get_mosaic_models` — list Mosaic data models (published catalog view).
- `get_semantics` — return the annotated attribute/metric surface for a Mosaic model.
- `query` — execute a Trino-compatible SQL query against the published Mosaic layer.

The memory writes say "MCP" — don't hunt for a server-id prefix. If your tool exposes these four tool names under any namespace, you're good.

**If your harness has no MCP support**, every MCP tool has a REST fallback:
- `get_projects` → `GET /api/projects`
- `get_mosaic_models` → folder walk for `subtype==779` via `/api/folders/{id}` + `/api/searches`
- `get_semantics` → `GET /api/model/dataModels/{id}/attributes` + `/factMetrics`
- `query` → direct Trino HTTPS connection (host `<tenant>:443`, catalog `sql`, schema `<project-name-lower>`, basic auth with MSTR creds), or `POST /api/dataModels/{id}/instances` + report/cube execution APIs for result-set equivalents.

## Running under specific LLM harnesses

All harnesses follow the same contract: read this file, load `memory/MEMORY.md` on demand, invoke `skill/scripts/build_mosaic.py` (and siblings) via whatever shell/tool-call mechanism is available. Harness-specific notes live in the root shim for that harness (`CLAUDE.md`, `CODEX.md`, `GEMINI.md`, `GROK.md`, `OLLAMA.md`, `CURSOR.md`) — one file per harness, maintained there only. Any harness without a shim needs no configuration: read this file plus the memory index and follow the routing.

Note for skill-aware harnesses (Claude Code included): the `SKILL.md` files here are read on demand via the routing above — they are NOT auto-discovered project skills unless you copy them under `.claude/skills/` or install them as a plugin.
