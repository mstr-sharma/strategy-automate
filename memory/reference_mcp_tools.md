---
name: MCP tools available on this Mac
description: Which MCP servers are connected in Claude Code and what they do; specifically whether a Strategy or Postman MCP is available.
type: reference
originSessionId: initial-session
---
**Mosaic MCP (connected):** prefix `mcp__<mosaic-server>__` — read-only over an *already-published* Mosaic model.
- `get_projects` — list Strategy projects the user can access.
- `get_mosaic_models` — list models in a project.
- `get_semantics` — fetch attribute + metric list for one model (the shape the benchmark scripts embed in system prompts).
- `query` — execute Trino SQL against the model (`schema` + `query`).

**Postman MCP:** NOT connected. `mcp-registry.search_mcp_registry(['postman','api'])` returns empty; `claude mcp list` shows no Postman server. When the user asks to "use the Postman agent", remind them it isn't connected and fall back to direct REST calls via the `build-mosaic-model` skill's helper script.

**Strategy REST:** no first-class MCP; invoked directly by `$REPO/skills/build-mosaic-model/scripts/build_mosaic.py` using credentials from memory.

**Claude Preview / Claude in Chrome:** browser-automation MCPs — useful if we ever need to click through Strategy Library UI (e.g., to confirm a model shows up after commit), but not a substitute for the REST API.
