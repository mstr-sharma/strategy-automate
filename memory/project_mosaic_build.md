---
name: Strategy automation repo — purpose and layout
description: What this repo is for (single Strategy automation brain), where each surface lives (skills, scripts, memory), and how new work should be added.
type: project
---
This repo is a **one-stop Strategy (formerly MicroStrategy) automation brain** for Claude Code / Codex. It should let an operator (typically a Sales Engineer; see `user_profile.md`) drive any Strategy task from natural-language requests wherever Strategy exposes an API, SDK, MCP, CLI, or reproducible hook: Mosaic model build, legacy semantic-layer inspection and migration, runtime analytics, cubes/datasets, data validation, administration, governance, and AI/agent workflows.

## Repo layout

- `memory/` — the durable knowledge base. `MEMORY.md` is the index; every other file is a typed memory (user / feedback / project / reference).
- `skill/` — the `build-mosaic-model` skill: SKILL.md plus `scripts/` (the REST helper CLIs: `build_mosaic.py`, `strategy_mosaic_inventory.py`, `strategy_semantic_inventory.py`, `strategy_semantic_mine.py`, `strategy_validate.py`).
- `strategy-automation/` — the NLQ router skill that chooses between surfaces and points Claude at the right memory + helper.
- `strategy-validation/` — the data-validation skill (paired-query correctness checks against any reference source — Mosaic, legacy report, flat file, warehouse SQL, REST fixture).
- Root: `README.md`, `.env.example`, `.gitignore`.

## Why

A single, composable Strategy automation brain that:
- Stands up new Mosaic models end-to-end from warehouse tables + an ERD / data dictionary.
- Inspects, mines, and modernizes legacy / classic project semantic-layer content.
- Automates administrative tasks through REST (and mstrio-py where appropriate).
- Provides a generic REST hook for every tenant-exposed OpenAPI endpoint, then promotes common/risky/multi-step flows into typed helpers.
- Proves every change correct via paired-query validation before it ships.
- Records known gaps when Strategy does not expose a reliable automation hook, instead of pretending the workflow is covered.
- Captures every tenant-verified gotcha into memory so the next session doesn't re-learn them.

## How to add to this repo

1. **New endpoint or workflow?** First prove the hook with `openapi-search` and a read-only or dry-run call. Add a subcommand to `skill/scripts/build_mosaic.py` when the workflow is common, risky, multi-step, or needs payload construction/read-back. Keep `skill/SKILL.md` in sync with the script's flags.
2. **New kind of durable knowledge?** Add a memory file in `memory/` with the standard frontmatter (`name`, `description`, `type`), then add a one-line pointer to `memory/MEMORY.md`.
3. **New platform surface or unavailable API?** Update `reference_strategy_automation_coverage.md` and `reference_strategy_task_catalog.md` with the hook level or known gap.
4. **New skill surface?** Sibling directory with a `SKILL.md`. Add routing in `strategy-automation/SKILL.md` so other sessions find it.
5. **Tenant-specific value discovered?** Do **not** commit it. Add an env-var lookup and document it in `.env.example` / `reference_strategy_env.md`.
6. **Before trusting an old endpoint note?** Re-probe with `openapi-summary` / `openapi-search` against the live `/api/openapi.yaml` and update the memory file.

## Hardening direction

The tool should accept drop-in artifacts (ERDs, data dictionaries, user/email rosters, legacy object briefs), normalize them, resolve names to IDs, dry-run high-impact admin changes, write through Strategy REST / Modeling Service with changesets, verify after every mutation, and close every build with a data-validation pass.
