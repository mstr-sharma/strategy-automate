---
name: Strategy environment reference
description: Base URL, project ID, destination folder, credentials, and login mode for the studio.strategy.com tenant.
type: reference
originSessionId: cef55f31-c57d-4220-b4dc-eddfff684771
---
**Tenant:** `https://studio.strategy.com/MicroStrategyLibrary`
**User:** `<operator-user>`
**Password:** do not store in memory or skills. Set `MSTR_PASSWORD` in the shell/keychain environment, or pass `--password` only for one-off local probes.
**Login mode:** `1` (standard)
**Project ID:** `1FC5A43B374C963CC773C285DF86E2F6`  (primary project the user works in — matches "Shared Studio" schema in Trino queries)
**Destination folder for models:** `DC377018BD4CACD81B7E4CAEB8DB62B4`
**Universal attribute ID form:** `45C11FA478E745FEA08D781CEA190FE5`

**Trino federation:** host `studio.strategy.com:443`, HTTPS, catalog `sql`, schema `"shared studio"` (quoted — has a space), basic-auth with the same creds. Each published Mosaic model appears as one Trino table whose columns are the model's attributes + metrics.

**Known Snowflake datasources (as of 2026-04-20):**
- `Snowflake Sample Data` — id `245EBDFD85458E568C76FCB353406E93`
- `WACSE Snowflake` — id `A8FF8DDD064B31A3D67668AEDB8BF954` (has schemas including PUBLIC, ENTERPRISE, HEALTHCAREDEMO, AD_SALES, INSURANCEDEMO, FREDDIE_MOSAIC, POWERUP_2025_CAPSTONE, etc.)

**Reference model to clone from when payload shape is unknown:** "Snowflake TPCH_SF1", id `3D4154B75ACF47DCB90806983EF57160` — used by `build_tpch_mosaic_model.py`.

**Machine-readable REST spec:** `{Tenant}/api/openapi.yaml` returns OpenAPI 3.0.1 YAML. Use `python3 skill/scripts/build_mosaic.py openapi-summary` from `/Users/<operator-user>/Desktop/Mosaic Build/` to verify the current tenant paths without logging in.

**MCP tools connected:** one Mosaic MCP server under prefix `mcp__df3a3274-2371-452c-ac93-7d58f2af669f__*` exposing `get_projects`, `get_mosaic_models`, `get_semantics`, `query`. **No Postman MCP** connected; Strategy REST is invoked directly via the helper script.
