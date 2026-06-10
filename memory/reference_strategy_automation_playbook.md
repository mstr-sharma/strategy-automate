---
name: Strategy automation playbook
description: NLQ-to-action operating model for making Claude/Codex an expert Strategy automation agent across REST, Mosaic, MCP, Trino, and mstrio-py.
type: reference
originSessionId: codex-session
---
Goal: a user should be able to ask in natural language for nearly any Strategy (formerly MicroStrategy) task, and the agent should route it to the right automation surface without guessing. The target is complete platform automation wherever Strategy exposes an API, SDK, MCP, CLI, or reproducible hook, with explicit known-gap notes where no reliable hook exists.

## Operating loop
1. Classify the request: read-only inspect, create/update, destructive, query published data, build/modify Mosaic model, governance/security, admin/platform.
2. Load only the needed references from `MEMORY.md`.
   - For broad audits or "can this automate everything?" requests, load `reference_strategy_automation_coverage.md` and classify each area by coverage level.
   - If the noun is overloaded (`attribute`, `metric`, `prompt`, `filter`, `security filter`, `ACL`, `cube`, `dataset`, `report`, `dashboard`, `document`, `model`, `agent`), load `reference_strategy_surface_matrix.md` before choosing endpoints.
   - If the user drops files or says "use this ERD / dictionary / user list", load `reference_strategy_intake_patterns.md`.
   - If the user wants to modernize legacy reports/documents/tables into Mosaic, load `reference_strategy_legacy_to_mosaic_mining.md`.
   - If the task requires modeling judgment, classic schema interpretation, or translation from old MicroStrategy project design to the new world, load `reference_strategy_design_transition.md`.
3. Find the endpoint or wrapper:
   - Known Mosaic build/modeling: `skills/build-mosaic-model/scripts/build_mosaic.py` and `reference_mosaic_modeling_concepts.md`.
   - Unknown REST: `openapi-search`, then `api-call`.
   - Published model query/semantics: Mosaic MCP or Trino.
   - Stable admin wrappers: mstrio-py if faster/cleaner than raw REST.
4. Probe read-only first whenever possible (`GET`, search, list, or dry-run shape).
5. For Modeling Service writes: open changeset, create/update objects, commit, verify with `GET`.
6. Return object IDs, URLs, names, access/security changes, skipped items, and verification status.
7. Persist durable tenant-specific lessons in memory.

## Safety model
- Never store secrets; use `MSTR_PASSWORD`, user-provided runtime flags, or existing authenticated sessions.
- Ask before destructive actions unless the user explicitly asked to delete/remove/revoke.
- Treat ACL, security filters, user/group changes, subscriptions, migrations, and server/project settings as high-impact. Verify target IDs before writing.
- Prefer committed object IDs over names when modifying existing objects.
- If docs conflict with tenant behavior, prefer `feedback_mosaic_gotchas.md`, then live `/api/openapi.yaml`, then public docs.

## Core command patterns
```bash
cd "$REPO"
python3 skills/build-mosaic-model/scripts/build_mosaic.py openapi-summary --limit 80
python3 skills/build-mosaic-model/scripts/build_mosaic.py openapi-search "securityFilters" --context 2
python3 skills/build-mosaic-model/scripts/build_mosaic.py api-call --method GET --path /api/projects
python3 skills/build-mosaic-model/scripts/build_mosaic.py api-call --method PATCH --path /api/model/dataModels/ID --json-file /tmp/body.json
python3 skills/build-mosaic-model/scripts/build_mosaic.py resolve-users --file users.csv
python3 skills/build-mosaic-model/scripts/build_mosaic.py search-objects --name "Customer" --limit 20
python3 skills/build-mosaic-model/scripts/build_mosaic.py get-model-object --kind legacy_attribute --object-id ATTR_ID --show-expression-as tokens
python3 skills/build-mosaic-model/scripts/strategy_semantic_mine.py --mode top-down --report "Revenue Report"
python3 skills/build-mosaic-model/scripts/strategy_semantic_mine.py --mode reverse --seed TABLE_ID;15
```

## Choosing the automation surface
- Surface matrix: first stop for ambiguous nouns and product-generation boundaries.
- REST helper: default for anything in OpenAPI, especially writes. A generic `api-call` path is the baseline hook for every exposed REST endpoint; typed helper commands are added for repeatable, risky, or multi-step workflows.
- Mosaic builder: warehouse table discovery through semantic model creation, relationships, metrics, security, publish.
- MCP: read/query already-published Mosaic models; do not use MCP for Modeling Service writes.
- mstrio-py: admin/read-heavy workflows and stable wrappers; still capture REST if a workflow becomes canonical.
- Browser automation: only when REST/MCP/mstrio/CLI cannot expose the needed UI-only action; capture the network request if possible and record it as a captured fallback or known gap.

## Coverage discipline
- Use `reference_strategy_automation_coverage.md` to distinguish wrapped helpers from generic hooks.
- When adding a new platform surface, update the task catalog with the endpoint family, the preferred hook, and the verification/read-back expectation.
- If an API is unavailable or tenant-specific, record the tested date, tenant behavior, and workaround instead of promising automation.

## Verification expectations
- REST write: follow with `GET` or folder/search lookup.
- Model build: return Library model URL and object counts/maps.
- In-memory publish: poll publish status when available or query through MCP/Trino after publish.
- Security/ACL: read back members/ACL where endpoint supports it.
- Translation/certification/VLDB/settings: read back the object or settings endpoint.
- User/admin changes: dry-run from the roster first, resolve existing users/groups, then execute only after explicit intent.

## Live validation
- For broad coverage testing, use `reference_strategy_validation_workflows.md`.
- Do not execute the proposed 10-workflow suite until the user signs off on the selected workflows and cleanup behavior.
- Validation runs should exclude Mosaic and AI/Agent/Bot workflows unless the user explicitly changes the scope.
