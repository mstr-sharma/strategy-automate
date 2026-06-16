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
data_serve_mode: connect_live   # connect_live | in_memory | hybrid
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
- For formula metrics over existing metric IDs, run `create-compound-metric --model-id M --name N --formula 'METRIC_ID1 / METRIC_ID2'`.
- For filtered metrics, create/reuse a filter or security filter first, then run `create-conditional-metric --model-id M --name N --source-metric MID --filter FID`.
- For prior-period / time-shift metrics, run `create-transformation`, then `attach-transformation`.
- On {MSTR_BASE host}, if token-based compound metrics fail on commit, use the known fallback: a fact metric with an inline column formula using `character` operator tokens (`TOTAL_COST`, `/`, `QUANTITY_ORDERED`) and an aggregate function such as `avg`.

When extending `build-from-config`, add deterministic support for a top-level `derived_metrics:` list rather than asking future agents to hand-write ad hoc post-build code.
