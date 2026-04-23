# CURSOR.md — entry point for Cursor / Cline / Continue / Aider / Windsurf

Cursor-style IDE agents, read [`AGENTS.md`](AGENTS.md) first, then [`memory/MEMORY.md`](memory/MEMORY.md) for the durable Strategy automation index.

## Harness notes

- **`.cursorrules` / `.cline/` / `.continue/` / `.aider.conf.yml`**: this repo does not ship those files. Point your IDE agent at `AGENTS.md` as the system/rules file, or source specific memory files in your agent's persistent context.
- **Skills**: each `SKILL.md` (under `skill/`, `strategy-automation/`, `strategy-validation/`) is a plain Markdown file with YAML frontmatter (`name`, `description`). Cursor-family agents treat these as reference documents loaded on demand based on the task match.
- **Shell execution**: all helpers are `skill/scripts/*.py` running on Python 3 stdlib + `requests`. No IDE-specific hooks.
- **Diff-based editing**: these tools are strong at file editing. When extending a memory file or adding a new one, follow the frontmatter conventions in the existing files (see `memory/user_profile.md` or `memory/reference_strategy_env.md` for templates).

Git defaults and credentials are in [`AGENTS.md`](AGENTS.md).
