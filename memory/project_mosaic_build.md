---
name: Mosaic Build project
description: This working dir is the "fully automated Mosaic model builder" project; sibling token-savings dir holds the benchmark harness that proves it out.
type: project
originSessionId: cef55f31-c57d-4220-b4dc-eddfff684771
---
Directory: `/Users/<operator-user>/Desktop/Mosaic Build/` — empty at session start on 2026-04-20; purpose is to hold the build-mosaic-model skill + helper, without being contaminated by the benchmark harness next door.

Sibling: `/Users/<operator-user>/Desktop/token savings/harness/` contains:
- `build_tpch_mosaic_model.py` — canonical reference build script (clone-and-remap pattern against an existing TPCH model). Copy payload shapes from here when unsure.
- `benchmark_extended_mosaic*.py` — benchmark scripts proving agents can query the published model via MCP or Trino.
- `tpch_semantic_model.yaml` — YAML snapshot of the semantic layer used in benchmarks.

**Why:** user wants a single, composable Strategy automation brain. It should stand up Mosaic models end-to-end and also let Claude/Codex automate nearly any Strategy task through NLQ by combining memory, OpenAPI, REST helper calls, mstrio-py, MCP, and tenant-specific gotchas.

**How to apply:** when extending, add features as new subcommands on `~/.claude/skills/build-mosaic-model/scripts/build_mosaic.py`; do not scatter logic across the benchmark harness. Keep skill docs in sync with script flags. Probe `/api/openapi.yaml` with `openapi-summary` before trusting old endpoint notes, and keep credentials in `MSTR_PASSWORD`, not memory.

**Hardening direction:** the tool should accept drop-in artifacts (ERDs, data dictionaries, user/email rosters, legacy object briefs), normalize them, resolve names to IDs, dry-run high-impact admin changes, write through Strategy REST/Modeling Service with changesets, and verify after every mutation.
