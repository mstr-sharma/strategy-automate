# CODEX.md — entry point for OpenAI Codex CLI

Codex CLI, read [`AGENTS.md`](AGENTS.md) first, then [`memory/MEMORY.md`](memory/MEMORY.md) for the durable Strategy automation index.

Everything else (skills, scripts, env-var setup) is in the repo structure documented in [`README.md`](README.md).

Notes specific to Codex:
- Skills live as `SKILL.md` files with YAML frontmatter. Codex does not implement Anthropic's skills protocol natively; treat each `skill/SKILL.md`, `strategy-automation/SKILL.md`, `strategy-validation/SKILL.md` as a long-form instruction file loaded on demand when the task matches the `description` field.
- All shell commands run via Codex's default shell tool. Prefer `/usr/bin/python3` on machines with Anaconda OpenSSL mismatch (see `memory/reference_strategy_env.md`).
- MCP tool names (`get_projects`, `get_mosaic_models`, `get_semantics`, `query`) are referenced in memory. If you have no MCP, see the REST fallback in `AGENTS.md`.

Git defaults and credentials are in [`AGENTS.md`](AGENTS.md).
