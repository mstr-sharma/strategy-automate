---
name: Strategy automation audit resolution 2026-04-22
description: Consolidated first audit findings, user clarifications, implementation status, and remaining follow-ups for the Strategy automation repo.
type: feedback
originSessionId: codex-session
---
This is the consolidated record from the first repo audit. The fixes landed on branch `codex/strategy-automation-audit-hardening` in commit `6d543a8`.

## User clarifications folded into the repo

- **Validation is comparator-dependent.** A valid data-correctness run can compare against another Mosaic model, a classic/legacy report or semantic model, direct warehouse SQL, a flat file, an external system/API, or a saved REST fixture. If no trusted comparator is available, mark validation pending instead of calling the build shippable.
- **Legacy/classic and Mosaic must stay separate.** Migration work should mine the existing classic/project semantic layer first and use attributes, forms, facts, metrics, relationships, filters, and reports as the blueprint for the new Mosaic layer. Brand-new models should start from warehouse discovery plus ERD/data dictionary/preflight evidence.
- **Automation coverage should be platform-wide.** The repo goal is complete Strategy automation wherever Strategy exposes an API, SDK, MCP, CLI, or reproducible hook. Each area should be classified as wrapped helper, generic REST hook, specialized hook, captured fallback, or known gap.

## Findings and status

1. **Data-correctness validator was promised but not implemented.**
   - Status: implemented for file/result-set comparisons; live adapters are explicitly incremental.
   - Changes: added `skill/scripts/strategy_validate_models.py`; updated `strategy-validation/SKILL.md`, `memory/reference_strategy_data_validation.md`, and build output to report `data_validation.status=not_run` when no comparator is supplied.
   - Follow-up: add live adapters for Mosaic MCP/Trino, classic report execution, warehouse SQL, and external REST sources as those workflows become repeatable.

2. **Mosaic security filter helper created the wrong shape.**
   - Status: fixed for Mosaic data-model security filters.
   - Changes: `build_mosaic.py` now requires structured qualification input or shorthand `ATTR_ID[:FORM_ID]=VALUE`, creates `md_security_filter`, avoids placeholder `predicate_false`, and assigns members with `/Members`.
   - Docs: `memory/reference_mosaic_security_filter.md`, `memory/reference_mosaic_modeling_concepts.md`, `memory/reference_strategy_openapi.md`, and `skill/SKILL.md` now distinguish Mosaic from classic/project security filters.

3. **Numeric ID columns could become bogus `SUM` metrics.**
   - Status: fixed and tested.
   - Changes: `build_mosaic.py` now treats numeric ID/key columns and common numeric dimensions as attributes by default unless explicitly forced as metrics; `preflight_model_check.py` no longer has the unreachable `ID_SUMMED_AS_METRIC` branch.
   - Tests: `tests/test_build_mosaic_classification.py`.

4. **Sessions were not reliably closed.**
   - Status: fixed.
   - Changes: `MSTR.logout()` uses tenant-verified `DELETE /api/auth/login`; `build_mosaic.py main()` calls logout in a `finally`; inventory/semantic/validation scripts were updated from `POST /api/auth/logout` to `DELETE /api/auth/login`.
   - Docs: session-cap guidance is preserved in `memory/feedback_mosaic_gotchas.md` and related references.

5. **Classic Modeling calls always got `X-MSTR-IdentityToken`.**
   - Status: fixed.
   - Changes: `MSTR.login(identity=True)` is now opt-in for Mosaic data-model writes; classic/project Modeling reads and patches use auth token plus project ID unless a specific endpoint proves otherwise.
   - Docs: router and gotchas now warn that identity tokens can break top-level classic Modeling Service reads on a verified tenant.

6. **Destructive model delete had no `--yes` guard.**
   - Status: fixed.
   - Changes: `delete-model` now requires `--yes`; task catalog and build skill docs mention enumerating the target ID before deletion.

7. **Write validation left enabled test artifacts.**
   - Status: fixed for workflow 9.
   - Changes: `strategy_validate.py` now tracks created duplicate users/security filters, removes membership by default, deletes objects created in the same run, and only keeps artifacts with `--keep-security-artifacts`.

8. **Repo needed an explicit complete-automation coverage model.**
   - Status: added.
   - Changes: new `memory/reference_strategy_automation_coverage.md`; wired into `AGENTS.md`, `README.md`, `strategy-automation/SKILL.md`, `memory/reference_strategy_automation_playbook.md`, `memory/reference_strategy_task_catalog.md`, and `memory/reference_strategy_surface_matrix.md`.

## Verification run

- `python3 -m py_compile skill/scripts/*.py`
- `python3 -m unittest discover -s tests` — 7 tests passed
- `git diff --check`

The local Python environment emits a known LibreSSL/urllib3 warning, but the checks pass.
