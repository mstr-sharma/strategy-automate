# SuperCube → schema simulation tables (2026-08-25)

Simulates the field email's "cube maths" scenario the supported way: the
semiconductor test dataframes that today get pushed into a SuperCube are instead
landed in warehouse tables, so a semantic layer (classic schema objects or a
Mosaic model) can bind to them and carry a reusable metric library
(Cpk / GRR / stat limits) that dashboard users pick by name.

## Tables (Neon PG `neondb.public`, star topology)

| Table | Grain | Rows | Purpose |
|---|---|---|---|
| `SEMI_PARAMETRIC_MEASUREMENTS` | device × test insertion × test | 64,800 | raw "Test Name / Float Value" fact — sigma math needs this grain |
| `SEMI_TEST_CATALOG` | test | 12 | test dimension: category, units, LSL/USL/target spec limits |
| `SEMI_LIMIT_OVERRIDES` | test (chosen limit) | 3 seeds | write-back target for the "pick your stat limit" transaction UX |

Scale: 24 lots × 3 wafers × 75 devices × 12 tests, 2026-01-05 → 2026-08-22,
4 testers, sites 1–4, stage WAFER_SORT.

## Planted signals (verified post-load)

1. `VDD_LEAKAGE_UA` mean drifts 1.99 → 4.12 µA across the window; monthly
   Cpk(upper) decays 2.32 → 0.68 and August pass rate dips to 98.22%.
2. `VTH_N_MV` site 3 reads ~+14 mV vs sites 1/2/4 (463.55 vs 447.7–450.2).
3. ~0.15% gross outliers (6–12σ) across all tests for PAT stories.

## Files

- `ddl.sql` — DROP+CREATE, quoted-UPPERCASE identifiers (Studio-friendly)
- `generate.py` — deterministic generator (seeded per row key; re-run = identical)
- `load.py` — DDL + COPY load; creds via standard libpq env vars, none in repo
- `validate.sql` — counts, per-test Cp/Cpk/pass-rate profile, both planted signals
- `semi_*.csv` — generated loads (gitignored; re-create with `python3 generate.py`)

## Status — COMPLETE (2026-08-25, end-to-end validated)

Full classic-route build on the <tenant-b> env, project '<operator>':

1. **Schema objects** (`build_uma_schema.py`): 10 attributes (multi-form Test
   spanning all 3 tables) + 7 facts in the system Schema Objects folders.
2. **Relationships + metric library** (`build_uma_semantics.py`,
   `build_uma_compounds.py`, `rebuild_metrics_tokens.py`, `dynamic_agg_fix.py`):
   Category→Test + Lot→Wafer edges; 20 metrics — 11 bases + `Mean Square`
   plumbing + Cp/Cpu/Cpl/Cpk (IF-smart) + 3σ stat limits + Active Upper/Lower
   coalesce. Metrics are parser-built (raw-token expressions), carry
   Aggregation-subtotal dynamic aggregation, and Sigma uses the sum-of-squares
   smart compound so σ-math is exact at every view level.
3. **Trim-proof overrides** (`view_active_limits.sql`, `finish_option1*.py`):
   `SEMI_ACTIVE_LIMITS` LEFT-JOIN view registered as a logical table; Manual
   facts re-pointed there.
4. **"SEMI Parametric Cube"** (`build_final_cube.py`, `vldb_fix_and_finish.py`):
   9 attributes × 20 metrics, derived-table VLDB (pooled-Postgres-safe SQL),
   project governors raised to 1M, publishes in ~40 s.

**Validation:** Test-level cube results match Postgres to 4 decimals on all 12
tests (mean/sigma/Cpk); `FMAX_MHZ` Active USL = manual 2550, all other tests =
mean+3σ (`cube_validation.json`). Durable gotchas recorded in
`memory/reference_strategy_legacy_semantic_admin.md` and the error-code index.

> **Naming note (2026-09-04):** company, person, and tenant identifiers in this capture are stand-ins (`EReaderCo`, `PharmaCo`, `<operator>`, …) per `memory/feedback_generalize_durable_artifacts.md`. The gitignored local scripts/payloads in this folder and the live warehouse objects keep the original identifiers, so table, plan, and file names here will not match them verbatim.
