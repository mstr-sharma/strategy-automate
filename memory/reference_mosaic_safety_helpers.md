---
name: mosaic_safety.py — defensive helpers index
description: Stateless utilities any Strategy automation script can call — error parsing, expression builders, attributeLookupTable bulk-response readers, role-playing dimension detection, session-cap detection.
type: reference
---

## What's in there

`skill/scripts/mosaic_safety.py` collects the pure-function defensive helpers
that surfaced from the TPC-DS Galaxy build. The file holds NO network calls
and NO MSTR session state — every function takes already-fetched response
bodies or plain dicts and returns parsed data or fresh payloads.

Import pattern from any sibling script:

```python
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mosaic_safety as ms
```

## Function map

### Error parsing — `parse_mstr_error`, `format_mstr_error`, `is_session_cap_error`

Surfaces Strategy `code` and `iServerCode` fields out of an error response so
operators can match `memory/reference_strategy_error_codes.md` without manual
JSON parsing. `format_mstr_error` returns a one-line, grep-friendly string
including the HTTP status, code, iServerCode, and message.

```python
ok = resp.ok
if not ok:
    print(ms.format_mstr_error(resp, prefix="wire-relationships"))
    if ms.is_session_cap_error(resp):
        print(ms.SESSION_CAP_MESSAGE)   # 30-min wait advisory
```

The `8004cb0a` session cap is named explicitly. The wait can't be skipped, but
naming it saves the next operator from grepping memory.

### Expression helpers — `make_expression`, `normalize_expressions`

Strategy returns expressions in a read-only `text` form on plain GET but
requires `tokens` or `tree` on write. Round-tripping a GET response into a
PATCH body produces `8004ccde` ("The tree or token is required for
expression"). Use these to avoid the trap:

- `make_expression(column, table_id, table_name=..., dtype=...)` — build a
  fresh form expression in the writable tokens shape.
- `normalize_expressions(attr_json)` — walk a GET-response attribute and
  convert any `text`-only expressions to `tokens` for safe re-submission.

### Bulk attribute response — `attribute_lookup_table_map`, `attribute_table_name_map`

`GET /api/model/dataModels/{id}/attributes?limit=1000` returns
`attributeLookupTable` per attribute. Use the maps to group attributes by
their owning dim table without N individual fetches.

```python
attrs = m.get(f"/api/model/dataModels/{mid}/attributes?limit=2000").json()["attributes"]
lookup = ms.attribute_lookup_table_map(attrs)  # {attr_id → table_id}
```

### Role-playing dimensions — `detect_role_playing_secondaries`

Splits a relationship-hint list into `(primaries, secondaries)` so wiring
scripts can wire primaries and explicitly log skipped secondaries. See
`feedback_mosaic_role_playing_dimensions.md` for the pattern and remediation.

## Stateful companions (live in build_mosaic.py)

These need a live `MSTR` session and call into `mosaic_safety` for the
underlying logic:

- `put_relationships_merged(m, model_id, attr_id, new_rels, cs)` — GET existing
  rels, dedupe, PUT the union; default for `cmd_wire_relationships`. See
  `feedback_mosaic_relationship_put_wipes.md`.
- `get_attribute_relationships(m, model_id, attr_id)` — read current rels.
- `validate_join_table_membership(m, model_id, p_id, c_id, join_id)` — verify
  both attribute endpoints have an expression on the join table; pre-flight
  for `8004ccc7`.
- `post_build_validate_topology(m, model_id, expected_tables=...)` — structured
  report: isolated attrs, fact tables without relationships, missing expected
  tables, numeric-named attrs that look like measures.
- `open_cs(m, schema_edit=True|False)` — explicit changeset typing.
- `assert_changeset_type(m, cs, schema_edit=...)` — fail fast if a write path
  is using the wrong changeset type.

## CLI surface added

```bash
# Validate post-build topology — recommended as the LAST step of every
# wiring or build script:
python3 skill/scripts/build_mosaic.py validate-topology \
  --model-id <id> --strict --json

# Wire relationships in merge-aware mode (default) — pass --replace only
# when you explicitly want the destructive wipe:
python3 skill/scripts/build_mosaic.py wire-relationships \
  --model-id <id> --hints rels.yaml

# Full validate-model now includes the W7 topology rollup with
# --strict-isolation to promote isolated-attribute findings to FAIL:
python3 skill/scripts/build_mosaic.py validate-model \
  --model-id <id> --strict-isolation
```

## When to update this file

- Add a row to the function map whenever a new helper lands in
  `mosaic_safety.py`.
- Cross-link the corresponding `feedback_*` file whenever a new defensive
  helper is added that addresses a tenant-observed failure.
