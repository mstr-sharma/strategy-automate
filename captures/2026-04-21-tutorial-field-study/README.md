---
name: Tutorial semantic field study snapshot 2026-04-21
description: Dated inventory snapshot from the 2026-04-21 REST sweep of the MicroStrategy Tutorial project on a verified Strategy Cloud tenant — per-family search/read counts, system-hierarchy totals, and top-table rankings. Durable anatomy and translation rules live in memory/reference_strategy_tutorial_semantic_field_study.md.
type: feedback
originSessionId: codex-session
---
Dated inventory snapshot from live REST reads of the `MicroStrategy Tutorial` project on a verified Strategy Cloud tenant on **2026-04-21**. Raw field-study output was written to `/tmp/strategy-tutorial-semantic-inventory-full.json`, with supplemental hierarchy verification at `/tmp/strategy-tutorial-hierarchies.json` (raw tenant payloads stay in `/tmp`, never committed). Counts reflect that tenant's Tutorial install at run time — the demo schema itself is public and stable, but installs vary (agent/template objects, training content, locale dupes). Durable object anatomy, endpoint map, gotchas, and legacy→Mosaic translation rules live in `memory/reference_strategy_tutorial_semantic_field_study.md`.

## Inventory outcome (as of 2026-04-21)

Classic object search found:

| Family | Search count | Definition reads OK | Definition reads failed | Main lesson |
| --- | ---: | ---: | ---: | --- |
| Attributes | 149 | 100 | 49 | Search returns real schema attributes plus Agent object-template attributes and transformation attributes. Filter by ancestor/subtype before editing. |
| Facts | 36 | 36 | 0 | Fact bodies are very complete: expressions, table mappings, entry level, and fact extensions. |
| Filters | 166 | 157 | 9 | Normal filter bodies read well; custom groups appeared in search as filter subtype `257` but are not supported by `/api/model/filters/{id}`. |
| Metrics | 715 | 692 | 23 | Metric bodies expose expression trees, nested metrics, dimty, conditionality, transformations, subtotals, smart totals, thresholds, and formatting. Managed/training/system-subtotal variants can fail. |
| Prompts | 189 | 91 | 98 | User-created prompts read; system prompts return an explicit "system prompt" error and should not be edited. |
| User hierarchies | 6 | 6 | 0 | Hierarchy bodies expose drill/browse attributes and parent/child paths; combine with system hierarchy for relationship tables. |

The system hierarchy read returned **73 relationships and 3 isolated attributes**:

- Relationship types: 58 one-to-many, 14 one-to-one, 1 many-to-many.
- Top relationship tables: `LU_CUSTOMER`, `LU_SUPPLIER`, `LU_EMPLOYEE`, `LU_ITEM`, `LU_STORE`, `ORDER_FACT`.

## Top table signals from definitions (snapshot ranking)

- Attributes: `LU_CUSTOMER`, `LU_EMPLOYEE`, `LU_SUPPLIER`, `ORDER_FACT`, `ORDER_DETAIL`, `F_TUTORIAL_TARGETS`, `LU_ITEM`, `LU_STORE`, `LU_CALL_CTR`.
- Facts: `ORDER_DETAIL`, `ORDER_FACT`, `CUSTOMER_SLS`, `F_TUTORIAL_REGION_TARGETS`, `INVENTORY_CURR`, `CITY_CTR_SLS`, `CITY_MNTH_SLS`, `CITY_SUBCATEG_SLS`.
