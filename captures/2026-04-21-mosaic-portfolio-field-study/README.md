---
name: Mosaic portfolio field study snapshot 2026-04-21
description: Dated single-tenant snapshot from the 2026-04-21 REST portfolio sweep — model counts (133 MCP vs 156 REST), portfolio totals, dataServeMode distribution, tenant dataset/model names, permission stats, and the anomalous non-Mosaic subType-779 model id. Durable rules live in memory/reference_strategy_mosaic_field_study.md.
type: feedback
---
Single-tenant snapshot from the live REST sweep on **2026-04-21** against `{MSTR_BASE host}` / project `{MSTR_PROJECT_NAME}` (id `{MSTR_PROJECT_ID}`). Raw inventory was written to `/tmp/strategy-mosaic-inventory-full.json` (raw tenant payloads stay in `/tmp`, never committed). All numbers below describe that tenant's state at run time — illustrative of shape, not an expectation for other tenants. Durable discovery rules, the sub-resource map, and the classic→Mosaic translation matrix live in `memory/reference_strategy_mosaic_field_study.md`.

Regenerated with:

```bash
cd $REPO
MSTR_PASSWORD=... /usr/bin/python3 skill/scripts/strategy_mosaic_inventory.py \
  --workers 12 --out /tmp/strategy-mosaic-inventory-full.json
```

## Counts and access stats

- MCP `get_mosaic_models` returned **133** models in `{MSTR_PROJECT_NAME}`; REST search (`type=3`, subType 779) returned **156**. The extra 23 were legacy Hyper / MTDI datasets that still carry subType 779 but have no modern `dataServeMode`. (This 133-vs-156 gap is the evidence for the durable "MCP shows published-catalog-only; prefer REST for metadata truth" rule.)
- One data model — id `2E5BC134AF423523BAF8C2A628980B86` — returned `8004e457 "Given object is not a Mosaic model"` on every `/api/model/dataModels/{id}/*` endpoint despite searching as subType 779.
- **117/156** `GET /api/model/dataModels/{id}/securityFilters` calls returned `8004c738 "User does not have Control access"` — the normal response when the session user did not author the filter; only 1 security filter was readable.

## Portfolio totals (156 models)

- 3309 attributes, 1419 fact metrics, 168 custom metrics, 585 physical tables, 1 readable security filter (117 privilege-denied), 23 external-data-model links, 168 folders, 2693 hierarchy relationships.

## Distributions

- **`dataServeMode`:** 119 `in_memory`, 22 `connect_live`, 15 blank. The blank ones are legacy Hyper/MTDI datasets: Finanzas, Trimble Hyper, Customer Hyper, Agents Hyper, HomeDepot Sample Retail Data, Penguin Tenant/Cluster Hyper Dataset, etc.
- **Physical tables:** 585/585 are `physicalTable.type = "pipeline"` — the pipeline (build-from-cube) pattern was universal, even for `connect_live` models. `warehouse_partition_table` and `freeform_sql` were not in active use.
- **Attribute forms:** 3085 system + 415 custom. Custom forms were almost always extra descriptive columns (e.g., `MANAGER_NAME`, `PRODUCT_NAME`, `region_name`) with category `"<Attr> None"` rather than `DESC`; expressions stayed simple single-column. Complex `Concat`/`ApplySimple(...)` expressions (common in classic Tutorial) were rare here.
- **Relationships:** 1830 `one_to_many` + 1 `many_to_many`; **zero `one_to_one`**. (Classic Tutorial has 58/14/1 across the three types — evidence for the auto-inference-bias translation rule.)
- **Metric shapes:** 1517/1587 carried `dimty|dimensionality|levels`; 98 had `hasConditionality`. **Zero** `compound`, `transformation`, or `smartMetric` — every advanced shape was an inline expression tree.
- **External data models:** 12 models referenced others — BREAD Comprehensive Analysis Suite referenced 5+ models; also Unified Supplier Model, TB Integrated Asset Health, Cardmember Rewards Model, etc.

## Tenant-specific helper invocations used during the sweep

```bash
# Narrow by name fragment for iterative analysis
MSTR_PASSWORD=... /usr/bin/python3 skill/scripts/strategy_mosaic_inventory.py \
  --model-name "BREAD" --out /tmp/mosaic-bread.json

# Single known model
MSTR_PASSWORD=... /usr/bin/python3 skill/scripts/strategy_mosaic_inventory.py \
  --model-name "snowflake tpch_sf1 test" --max-models 1
```
