---
name: MCP tools available on this Mac
description: Which MCP servers are connected in Claude Code and what they do; specifically whether a Strategy or Postman MCP is available.
type: reference
originSessionId: initial-session
---
**Mosaic MCP (connected):** prefix `mcp__<mosaic-server>__` — read-only over **certified** models. Published is not enough (corrected 2026-10-05).
- `get_projects` — list Strategy projects the user can access.
- `get_models` (older servers: `get_mosaic_models`) — lists **certified** models only. Each row is typed `Mosaic Model` or `Other Model` (governed cubes/datasets); `only_mosaic_models=true` filters to Mosaic. A published but uncertified model is missing from the list.
- `get_semantics` — fetch attribute + metric list for one model (the shape the benchmark scripts embed in system prompts). Lookup is by model name and fails until the model is certified. To make a fresh build visible to MCP, run `build_mosaic.py certify --object-id <modelId>` (or `--certify` at build) after publish. Until then, use REST (`/api/model/dataModels/{id}/attributes` + `/factMetrics`) and direct Trino.
- `query` — execute Trino SQL against the model (`schema` + `query`).

**Postman MCP:** NOT connected. `mcp-registry.search_mcp_registry(['postman','api'])` returns empty; `claude mcp list` shows no Postman server. When the user asks to "use the Postman agent", remind them it isn't connected and fall back to direct REST calls via the `build-mosaic-model` skill's helper script.

**Strategy REST:** no first-class MCP; invoked directly by `$REPO/skills/build-mosaic-model/scripts/build_mosaic.py` using credentials from memory.

**Claude Preview / Claude in Chrome:** browser-automation MCPs — useful if we ever need to click through Strategy Library UI (e.g., to confirm a model shows up after commit), but not a substitute for the REST API.
