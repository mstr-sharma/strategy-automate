# GROK.md — entry point for xAI Grok / Grok Code

Grok, read [`AGENTS.md`](AGENTS.md) first, then [`memory/MEMORY.md`](memory/MEMORY.md) for the durable Strategy automation index.

Everything else (skills, scripts, env-var setup) is in the repo structure documented in [`README.md`](README.md).

Notes specific to Grok:
- No native skills protocol — each `SKILL.md` is a Markdown instruction file; load whichever matches the user's ask based on its `description` frontmatter. The authoritative skill list and precedence chain are in `AGENTS.md` (cold-start routing) — do not rely on any list here.
- Bash/shell tool calls execute `skills/build-mosaic-model/scripts/build_mosaic.py` and siblings. These are plain `requests`-based Python with no LLM-specific dependencies.
- If the Grok harness exposes only synchronous tool calls, the existing scripts still work — they're all one-shot CLI invocations.

Git defaults and credentials are in [`AGENTS.md`](AGENTS.md).
