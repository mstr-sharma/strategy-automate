# AGENTS.md — entry point for AI coding agents

You are operating inside the **strategy-automation** repo: a one-stop automation brain for **Strategy** (formerly MicroStrategy) that covers Mosaic semantic models, the classic / legacy semantic layer, admin tasks, and data validation.

This file is the cross-tool entry point (Codex CLI, Gemini CLI, Cursor, Cline, etc.). Claude Code also reads `memory/MEMORY.md` directly; the two indexes point at the same content.

## First move on any task

1. **Identify the surface.** Strategy concepts are duplicated across Mosaic and classic. Before touching endpoints, decide whether the user is asking about Mosaic data models, classic / project semantic layer, runtime analytics, cubes / datasets, AI agents, platform admin, or data validation. When uncertain, consult `memory/reference_strategy_surface_matrix.md`.
2. **Read the relevant memory file.** `memory/MEMORY.md` is the index — every other file has a `type` frontmatter (`user`, `project`, `feedback`, `reference`) and a one-line description. Load only the files you need.
3. **Use the skills when they fit.**
   - `skill/SKILL.md` — the `build-mosaic-model` skill (discovery + build + ACL + security filter + publish + post-build edits).
   - `strategy-automation/SKILL.md` — the NLQ router: points you at the right memory + helper for any Strategy task.
   - `strategy-validation/SKILL.md` — paired-query data-correctness validation against any reference source.
4. **Use environment configuration, never hardcoded values.** `MSTR_BASE`, `MSTR_USER`, `MSTR_PASSWORD`, `MSTR_PROJECT_ID` or `MSTR_PROJECT_NAME`, `MSTR_DEST_FOLDER_ID`. See `.env.example` + `memory/reference_strategy_env.md`.
5. **Probe live specs when endpoint details matter.** `python3 skill/scripts/build_mosaic.py openapi-summary` and `... openapi-search "<term>"` hit `/api/openapi.yaml` directly.

## Operating rules (apply to every tool)

- **Consumer-grade naming is the ship bar.** Any model you build or modify must pass the checklist in `memory/feedback_consumer_grade_naming.md` — business-named attributes, non-empty form names, business-friendly descriptions, sensible metric formats, no hardcoded example usernames or personal names.
- **Every Mosaic build closes with data validation.** Route through `strategy-validation/SKILL.md`; the reference source can be another Mosaic model, a classic project report, a flat file, direct warehouse SQL, or a saved REST fixture (NOT Mosaic-to-Mosaic only).
- **Changesets are the unit of write.** Open → mutate → commit, or discard on failure. Relationships / ACLs / translations typically require a separate changeset after object creation.
- **Preserve tenant-verified gotchas.** When a script's endpoint returns 404 or a payload shape changes, update both the script and the corresponding memory file. Never silently work around.
- **Never hardcode credentials, tenant IDs, or personal names.** Pull from env vars; parameterize security filters.
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
