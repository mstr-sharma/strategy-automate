---
name: mstrio-py reference for Strategy automation
description: How to use MicroStrategy/mstrio-py alongside direct REST calls when building Mosaic automation.
type: reference
originSessionId: codex-session
---
mstrio-py is useful, but the build-mosaic-model helper should remain REST-first.

Official sources:
- GitHub: `https://github.com/MicroStrategy/mstrio-py`
- Docs: `https://www2.microstrategy.com/producthelp/current/mstrio-py/index.html`

Current docs observed 2026-04-21:
- mstrio-py wraps Strategy One REST APIs into Python workflows for data access, dataset/cube work, and administration.
- Current GitHub README says version `11.6.4.101` (17 Apr 2026), Python 3.10-3.14, Strategy / MicroStrategy 2019 Update 4+.
- Module tree includes `mstrio.modeling`, with subpackages for `expression`, `filter`, `metric`, `schema`, and `security_filter`.
- Modeling docs expose helper objects such as `DataType`, `TableColumn`, `PhysicalTableType`, `SchemaObjectReference`, and attribute display/sort helpers.
- Metric docs expose `Metric`, metric listing, default subtotals, thresholds, and dimensionality/format helpers.

How to apply:
- Use direct REST via `skills/build-mosaic-model/scripts/build_mosaic.py` for scratch Mosaic model creation because tenant behavior can differ from public wrappers and the helper already encodes {MSTR_BASE host} quirks.
- Use mstrio-py for admin/read workflows where wrappers are stable: listing projects/users/groups, object search, security roles, schedules/subscriptions, cache operations, VLDB/admin settings, and object metadata inspection.
- For classic project security filters, mstrio-py is useful because `SecurityFilter.create(...)` can accept an `Expression`, a dict, or a string qualification and wraps `POST /api/model/securityFilters`; `SecurityFilter.apply(...)` wraps `PATCH /api/securityFilters/{id}/members`.
- Relevant modules/packages confirmed in the public repo: `mstrio.api.security_filters`, `mstrio.modeling.security_filter.security_filter`, `mstrio.users_and_groups.user`, and `mstrio.users_and_groups.user_group`.
- Additional confirmed modules/examples for broader automation: `mstrio.access_and_security.security_role`, `mstrio.access_and_security.privilege`, `mstrio.utils.acl`, `mstrio.api.cubes`, `mstrio.api.datasets`, `mstrio.project_objects.datasets.olap_cube`, `mstrio.project_objects.datasets.super_cube`, `mstrio.project_objects.datasets.cube_cache`, `code_snippets/acl_mgmt.py`, `code_snippets/intelligent_cube.py`, `code_snippets/create_super_cube.py`, and `code_snippets/cube_cache.py`.
- If mstrio-py has a first-class class for a requested operation, it can be used as a readable wrapper, but capture the equivalent REST path/payload in memory if the workflow becomes part of the build skill.
- Never let mstrio-py hide a failing Modeling Service payload. For schema/model writes, prefer `GET` working object -> clone/remap -> `POST/PATCH` with explicit JSON so future Claude/Codex sessions can reproduce it without wrapper internals.
