# AGENTS.md — canonical, LLM-agnostic entry point

You are operating inside the **strategy-automation** repo: a one-stop automation brain for **Strategy** (formerly MicroStrategy) that aims for complete platform automation wherever Strategy exposes an API, SDK, MCP, CLI, or reproducible hook. It covers Mosaic semantic models, the classic / legacy semantic layer, runtime analytics, cubes / datasets, platform admin, AI agents, and data validation.

This file is the **canonical cross-tool entry point**. Every LLM-specific shim at the repo root (`CLAUDE.md`, `GEMINI.md`, `CODEX.md`, `GROK.md`, `OLLAMA.md`, `CURSOR.md`, etc.) points here. If you are a model or tool not listed there, read this file + `memory/MEMORY.md` and proceed — nothing else is tool-specific.

**Harness assumptions (apply across LLMs):**
- The repo is plain Markdown + Python 3 (standard library + `requests`). No Anthropic-specific, OpenAI-specific, or Google-specific SDK calls — every helper is `requests` against Strategy REST or subprocess to `mstrio-py`.
- `SKILL.md` frontmatter (`name`, `description`) follows Anthropic's skill convention, but any harness that reads Markdown with YAML frontmatter can use it. A skill-unaware LLM can read each `SKILL.md` as a normal instruction file.
- `memory/MEMORY.md` is a flat index with one-line hooks; any LLM can `grep` or keyword-match to find the relevant memory file on demand.
- Shell helpers live in `skill/scripts/`. Invoke them via whatever tool-call mechanism your harness exposes (Bash, shell, execute_command, tool-use-bash, etc.).
- Credentials come from env vars (`MSTR_BASE`, `MSTR_USER`, `MSTR_PASSWORD`, `MSTR_PROJECT_ID`/`MSTR_PROJECT_NAME`, `MSTR_DEST_FOLDER_ID`) — see `memory/reference_strategy_env.md`. Never hardcode.

## Git setup

- `origin` is the work repository: `git@<ssh-alias>:<org-user>/strategy-automate.git`.
- `personal` is the old/private mirror: `https://github.com/<personal-handle>/strategy-automation.git`.
- Use the local work identity `<operator> <redacted@example.com>`.
- Default pull/push should target `origin`; use `git pull --ff-only` before starting shared work and `git push` after commit.
- Do not commit `.env`, `.claude/`, credentials, tenant IDs, raw tenant payloads, or local logs.

## First move on any task

1. **Identify the surface.** Strategy concepts are duplicated across Mosaic and classic. Before touching endpoints, decide whether the user is asking about Mosaic data models, classic / project semantic layer, runtime analytics, cubes / datasets, AI agents, platform admin, or data validation. When uncertain, consult `memory/reference_strategy_surface_matrix.md`.
2. **Read the relevant memory file.** `memory/MEMORY.md` is the index — every other file has a `type` frontmatter (`user`, `project`, `feedback`, `reference`) and a one-line description. Load only the files you need.
3. **Use the skills when they fit.**
   - `skill/SKILL.md` — the `build-mosaic-model` skill (discovery + build + ACL + security filter + publish + post-build edits).
   - `strategy-automation/SKILL.md` — the NLQ router: points you at the right memory + helper for any Strategy task.
   - `strategy-validation/SKILL.md` — paired-query data-correctness validation against any reference source.
4. **Use environment configuration, never hardcoded values.** `MSTR_BASE`, `MSTR_USER`, `MSTR_PASSWORD`, `MSTR_PROJECT_ID` or `MSTR_PROJECT_NAME`, `MSTR_DEST_FOLDER_ID`. See `.env.example` + `memory/reference_strategy_env.md`.
5. **Probe live specs when endpoint details matter.** `python3 skill/scripts/build_mosaic.py openapi-summary` and `... openapi-search "<term>"` hit `/api/openapi.yaml` directly.
6. **Classify automation coverage honestly.** Use `memory/reference_strategy_automation_coverage.md`: wrapped helper, generic REST hook, specialized hook, captured fallback, or known gap. Generic `api-call` reachability is an API hook, but not a finished workflow wrapper.

For Mosaic work, distinguish the entry path:
- **Legacy-to-Mosaic migration:** mine/read the classic semantic layer first, then use its attributes, forms, facts, metrics, relationships, filters, and reports as the blueprint for the new Mosaic model.
- **Brand-new Mosaic model:** start from warehouse discovery plus ERD/data dictionary/preflight checks, then build and validate against the best available comparator.

## Operating rules (apply to every tool)

- **Classify Mosaic vs legacy before every write.** Before hitting any endpoint that differs between the two families (publish, refresh, execute, serve-mode, ACL, security filter), call `GET /api/objects/{id}?type=3` and branch on `subtype`: 779 → Mosaic data model, 776 → classic Intelligent Cube, anything else → stop and classify further. **Never call `/api/cubes/*` on a Mosaic model** — it returns 2xx but leaves the model unpublished. See `memory/reference_mosaic_vs_legacy_surfaces.md` for the full endpoint-pair cheat sheet and the verified 3-step Mosaic publish flow. The `build_mosaic.py publish` helper now routes by subType and polls `publishStatus` to completion; do not reintroduce "first 2xx wins" logic.
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
- `strategy-automation/SKILL.md` — NLQ router.
- `strategy-validation/SKILL.md` — data-correctness validator.
- `.env.example` — env-var template (copy to `.env`).
- `README.md` — human setup guide, per-AI-tool onboarding.

## Memory index

See `memory/MEMORY.md` for the full list. The most load-bearing entries:

- `user_profile.md` — typical operator (Strategy Sales Engineer) and style expectations.
- `project_mosaic_build.md` — repo purpose and how to extend it.
- `reference_strategy_env.md` — env-var + CLI-flag convention.
- `reference_strategy_automation_playbook.md` — NLQ-to-action loop, safety model.
- `reference_strategy_automation_coverage.md` — complete-platform coverage levels and gap-register rules.
- `reference_strategy_surface_matrix.md` — route ambiguous nouns to the right surface.
- `reference_mosaic_rest_api.md` + `reference_mosaic_modeling_concepts.md` — Mosaic endpoints + payload shapes.
- `reference_strategy_mosaic_field_study.md` — live portfolio inventory + legacy↔Mosaic translation matrix.
- `reference_strategy_tutorial_semantic_field_study.md` — live classic-layer inventory.
- `feedback_consumer_grade_naming.md` — ship-bar checklist.
- `reference_strategy_data_validation.md` — validation-suite reference.
- `feedback_mosaic_gotchas.md` — precedence/encoding bugs and clone-and-remap pattern.

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

All harnesses follow the same contract: read this file, load `memory/MEMORY.md`, invoke `skill/scripts/build_mosaic.py` (and siblings) via whatever tool-call mechanism is available. Per-harness notes:

- **Claude Code** (`CLAUDE.md`) — skills in `skill/`, `strategy-automation/`, `strategy-validation/` auto-discovered by `SKILL.md` frontmatter. Memory auto-loaded via `memory/MEMORY.md` index.
- **Codex CLI** (`CODEX.md`) — reads `AGENTS.md` on `cd`. Scripts run under its shell tool.
- **Gemini CLI** (`GEMINI.md`) — reads `GEMINI.md` → `AGENTS.md`.
- **Grok / xAI CLIs** (`GROK.md`) — same contract; if no skills concept, treat each `SKILL.md` as a long-form instruction file.
- **Ollama local models** (`OLLAMA.md`) — load this file + targeted memory files into the system prompt. Call scripts via subprocess. Works with any tool-calling model (`llama3.2`, `qwen2.5-coder`, `mistral-small`, `devstral`).
- **Cursor / Cline / Continue / Aider** (`CURSOR.md`) — point the agent at `AGENTS.md` as the root instruction; skills and memories are ordinary Markdown files.
- **Any other LLM** — no configuration needed. Read this file + memory index; follow the routing.
