# CURSOR.md — entry point for Cursor / Cline / Continue / Aider / Windsurf

Cursor-style IDE agents, read [`AGENTS.md`](AGENTS.md) first, then [`memory/MEMORY.md`](memory/MEMORY.md) for the durable Strategy automation index.

## Harness notes

- **Cursor**: the repo ships an always-applied rule at `.cursor/rules/strategy-automation.mdc` that points at `AGENTS.md` — Cursor picks it up automatically.
- **Cline / Continue / Aider / Windsurf**: this repo does not ship `.cursorrules` / `.cline/` / `.continue/` / `.aider.conf.yml`. Point your IDE agent at `AGENTS.md` as the system/rules file, or source specific memory files in your agent's persistent context.
- **Skills**: each `SKILL.md` is a plain Markdown file with YAML frontmatter (`name`, `description`), loaded on demand based on the task match. The authoritative skill list and precedence chain are in `AGENTS.md` (cold-start routing).
- **Shell execution**: all helpers are `skill/scripts/*.py` running on Python 3 stdlib + `requests`. No IDE-specific hooks.
- **Diff-based editing**: these tools are strong at file editing. When extending a memory file or adding a new one, follow the frontmatter conventions in the existing files (see `memory/user_profile.md` or `memory/reference_strategy_env.md` for templates).

Git defaults and credentials are in [`AGENTS.md`](AGENTS.md).
