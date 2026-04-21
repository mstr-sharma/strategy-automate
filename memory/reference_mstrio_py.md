---
name: mstrio-py reference for Strategy automation
description: How to use MicroStrategy/mstrio-py alongside direct REST calls when building Mosaic automation.
type: reference
originSessionId: local-codex-2026-04-21
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
- Use direct REST via `skill/scripts/build_mosaic.py` for scratch Mosaic model creation because tenant behavior can differ from public wrappers and the helper already encodes studio.strategy.com quirks.
- Use mstrio-py for admin/read workflows where wrappers are stable: listing projects/users/groups, object search, security roles, schedules/subscriptions, cache operations, VLDB/admin settings, and object metadata inspection.
- If mstrio-py has a first-class class for a requested operation, it can be used as a readable wrapper, but capture the equivalent REST path/payload in memory if the workflow becomes part of the build skill.
- Never let mstrio-py hide a failing Modeling Service payload. For schema/model writes, prefer `GET` working object -> clone/remap -> `POST/PATCH` with explicit JSON so future Claude/Codex sessions can reproduce it without wrapper internals.
