---
name: Mosaic build config schema
description: Declarative YAML/JSON shape accepted by build_mosaic.py build-from-config, plus post-build metric operations agents should run when needed.
type: reference
originSessionId: codex-session
---
`build-from-config --config spec.yaml` rehydrates this shape and calls the normal `build` flow.

Minimal:
```yaml
name: Customer 360
data_serve_mode: connect_live   # connect_live | in_memory | off_memory (spec enum; there is no hybrid)
publish: false                  # meaningful for in_memory
sources:
  - instance: Snowflake Prod
    schema: SALES
    tables: [CUSTOMER, ORDERS, LINEITEM]
dictionary: /path/to/data_dictionary.json   # JSON/YAML/CSV, optional
erds: [/path/to/model.dbml, /path/to/joins.sql]
```

Supported build keys:
```yaml
destination_folder: {MSTR_DEST_FOLDER_ID}
attr_cols: [CUSTOMER_ID]
metric_cols: [REVENUE, COST]
skip_cols: [ORDERS.O_COMMENT]   # TABLE.COLUMN or bare column; excluded from the model (stays physical, not modeled)
skip_relationships: false
security_filters:
  - name: EMEA Only
    qualification: REGION = 'EMEA'
    members: [USER_OR_GROUP_ID]
grants:
  - trustee: USER_OR_GROUP_ID
    rights: [read, browse, execute]
denies:
  - trustee: USER_OR_GROUP_ID
    rights: [write, delete]
translations:
  - object: OBJECT_ID
    locale: "1036"
    text: Client
certify: false
publish: true
```

Name/description and relationship enrichment can be included in config with:
- `dictionary` or `data_dictionary`: JSON/YAML/CSV dictionary path.
- `erd`: one ERD path.
- `erds`: list of ERD paths.

For image/PDF ERDs, the agent should read the image/document first and write a JSON/DBML/Mermaid/SQL relationship file, then reference that file from `erd`/`erds`.

Derived metric workflow:
- For formula metrics over existing metric IDs, POST a derived metric to `/api/model/dataModels/{id}/metrics` with an `expression.tree` (`operator` nodes with `function: plus|minus|times|divide`, `object_reference` leaves, `dimty: null`) — verified bodies in `reference_mosaic_derived_metrics.md` §0. Corrected 2026-10-05: `create-compound-metric --formula 'METRIC_ID1 / METRIC_ID2'` still emits `metric_reference` / `operator` *tokens* to `/factMetrics?changesetId=` — neither token type nor that query parameter exists in the spec — so don't rely on it until it is rewritten.
- For filtered metrics, run `create-conditional-metric --model-id M --name N --source-metric "<fact metric>" --attribute "<attribute>" --elements V1 [V2 ...]` — it creates the filter embedded in the metric, so no separate filter object is needed (verified path: `reference_mosaic_derived_metrics.md` §0c).
- For prior-period / time-shift metrics, `create-transformation` + `attach-transformation` exist but are unverified and target shapes the spec lacks: transformations are project-level (`POST /api/model/transformations`; there is no `/api/model/dataModels/{id}/transformations`), and the fact-metric schema has no `transformation` field (corrected 2026-10-05). Capture a UI-built transformation metric before scripting one.
- On {MSTR_BASE host}, if token-based compound metrics fail on commit, use the known fallback: a fact metric with an inline column formula using `character` operator tokens (`TOTAL_COST`, `/`, `QUANTITY_ORDERED`) and an aggregate function such as `avg`.

When extending `build-from-config`, add deterministic support for a top-level `derived_metrics:` list rather than asking future agents to hand-write ad hoc post-build code.
