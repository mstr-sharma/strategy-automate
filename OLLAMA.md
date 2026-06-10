# OLLAMA.md — entry point for Ollama-hosted local models

Local model (llama3.x, qwen2.5-coder, mistral-small, devstral, deepseek-coder, etc.), read [`AGENTS.md`](AGENTS.md) first, then [`memory/MEMORY.md`](memory/MEMORY.md) for the durable Strategy automation index.

## Bootstrap prompt template

Because many Ollama harnesses don't auto-load Markdown files, paste the following into your system prompt (or prepend to the user turn) when you first `cd` into this repo:

```
You are an assistant with access to a Strategy (formerly MicroStrategy) automation
repo at the current working directory. Your entry point is AGENTS.md — its
"Cold-start routing" section is the authoritative skill list and precedence chain
(classify via strategy-automation/SKILL.md → plan via strategy-data-modeling/SKILL.md
→ execute via skill/SKILL.md → verify via strategy-validation/SKILL.md). Memory lives
in memory/MEMORY.md (each line is a one-liner pointing to a typed memory file).
Helper CLI scripts are in skill/scripts/ and run with python3. Credentials come from
env vars (MSTR_BASE, MSTR_USER, MSTR_PASSWORD, MSTR_PROJECT_ID, MSTR_DEST_FOLDER_ID).
Before writing, check memory/reference_strategy_surface_matrix.md and the
relevant memory file for the object family you're touching.
```

## Harness notes

- **Tool use**: any Ollama model with function-calling (`llama3.2:3b-instruct`, `llama3.3:70b`, `qwen2.5-coder:32b`, `devstral:24b`, `hermes3`, etc.) can call `run_shell(cmd)` to invoke `python3 skill/scripts/build_mosaic.py ...`. Models without function-calling can still output shell commands and let the harness execute them.
- **Context window**: load `memory/MEMORY.md` + the 2–3 memory files relevant to the task. Don't attempt to load the whole memory corpus unless the context budget exceeds 128k tokens.
- **MCP**: Ollama Chat, LibreChat, Open WebUI, LMStudio, etc. all now support MCP servers. Connect the Strategy Mosaic MCP server (vendor-specific connector) to expose `get_projects`, `get_mosaic_models`, `get_semantics`, `query`. Without MCP, use the REST fallback documented in `AGENTS.md`.
- **Memory lookup**: all memory files are plain Markdown with YAML frontmatter. A weak model can keyword-grep the index. A strong model should parse frontmatter.

Git defaults and credentials are in [`AGENTS.md`](AGENTS.md).
