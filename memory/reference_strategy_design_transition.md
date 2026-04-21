---
name: Strategy design transition knowledge
description: Conceptual bridge from classic MicroStrategy project schema design to modern Strategy Mosaic, Universal Semantic Layer, AI/MCP, validation, Git/YAML, and governance.
type: reference
originSessionId: codex-session
---
Use this when the user asks for modeling judgment: how classic MicroStrategy project design should inform modern Mosaic models, how to modernize legacy projects, or how to make agents understand old semantic-layer intent rather than just copy objects.

Do not copy the source documentation into memory. Read the official pages as needed, then keep distilled design principles, mappings, and automation implications here.

## Source corpus

Classic project design:
- Project Design overview: `https://www2.microstrategy.com/producthelp/current/ProjectDesignGuide/WebHelp/Lang_1033/Content/BookOverview.htm`
- Logical data model: `PD-LogicalData.htm`
- Warehouse structure: `PD-PhysicalWHSchema.htm`
- Project creation/configuration: `PD-IntroProjCreation.htm`, `PD-Architect.htm`
- Facts: `PD-Facts_Overview.htm`
- Attributes: `PD-Attributes_Overview.htm`
- Hierarchies: `PD-Schema_Hierarchies.htm`
- Transformations: `PD-Schema_Transformations.htm`
- Financial reporting design: `PD-ProfitLoss.htm`
- Warehouse catalog/schema maintenance: `Data_warehouse_and_project_interaction__Warehouse_.htm`, `Updating_your_MicroStrategy_project_schema.htm`

Modern Strategy/Mosaic:
- Mosaic home: `https://www2.microstrategy.com/producthelp/Current/Mosaic/en-us/Content/home_mosaic.htm`
- Universal Semantic Layer: `mosaic_connector.htm`
- Mosaic Sentinel: `mosaic_sentinel.htm`
- Current product catalog / what is new: `https://www2.microstrategy.com/producthelp/Current/Readme/en-us/content/whats_new.htm`

## Core thesis

Classic MicroStrategy projects were powerful because the schema layer was a governed semantic contract over warehouse reality:

- physical columns and tables become logical tables;
- facts express numeric business events at specific grains;
- attributes and forms express business entities, keys, descriptions, and drill paths;
- hierarchies encode navigable business structure;
- transformations encode reusable time-relative or comparison logic;
- filters, prompts, metrics, security filters, VLDB, and reports sit on top of that contract.

Modern Strategy Mosaic should not discard that thinking. The modern path is to use Mosaic models as the source-controllable, validated, AI/MCP-accessible form of the same semantic intent, with better automation, Git/YAML restore, model validation, Universal Semantic Layer connectivity, and governance monitoring.

## Classic-to-modern concept map

| Classic project design concept | Modern/Mosaic interpretation | Automation action |
| --- | --- | --- |
| Warehouse columns | Catalog columns / table fields | Discover through datasource catalog; classify IDs, descriptors, measures, dates, noise columns. |
| Logical tables | Mosaic model tables | Seed from data dictionary, ERD, legacy table dependencies, or report/document mining. |
| Facts | Base measures / fact metrics | Create fact metrics or base metrics from numeric columns and legacy fact expressions. |
| Attributes | Mosaic attributes | Preserve key/display forms, lookup table intent, entity grain, parent-child relationships, and display names. |
| Attribute forms | Attribute key/display fields | Map ID/DESC forms explicitly; do not collapse display forms into metrics or labels. |
| Hierarchies | Mosaic hierarchies / drill paths | Recreate only meaningful navigation paths; avoid overfitting one report's row layout. |
| Transformations | Time transformation metrics / reusable date logic | Recreate year-to-date, month-to-date, quarter-to-date, prior-period, and comparison logic using Mosaic-supported transformation patterns. |
| Project filters | Model filters or runtime/dashboard filters | Decide whether logic is semantic default, runtime view behavior, or security/governance. |
| Security filters | Mosaic data-model security filters or classic project security filters | Route by ownership: model-owned security in Mosaic, project-owned security in legacy. |
| Prompts | Runtime interaction, model filter parameterization, or dashboard UX | Preserve user intent, but do not force every prompt into the model. |
| Reports/documents | Validation fixtures and usage signals | Mine for objects/tables/metrics; after build, compare Mosaic results to legacy report outputs. |
| Warehouse Catalog / Architect | Automated catalog discovery and config generation | Use datasource catalog, ERD, dictionary, and lineage mining to generate model config. |
| Schema update | Model validation, publish, refresh, Git/YAML lifecycle | Validate before publish; save/restore from YAML/Git when available; document generated changes. |
| VLDB/performance settings | Model serve mode, pushdown/live/in-memory, query validation | Preserve intent where relevant; re-evaluate for Mosaic engine and source connectivity. |

## Modern product direction to account for

From current Mosaic and What's New pages, new-world automation should assume:

- Mosaic Studio is the modeling workspace for quickly preparing, modeling, and enriching data.
- The Universal Semantic Layer is the cross-tool contract for governed definitions, metrics, and access.
- Mosaic Sentinel is the monitoring/governance lens for risk detection and enforcement.
- Mosaic models increasingly need lifecycle artifacts: YAML export/restore, Git save/restore, undo/redo, and model validation.
- Time transformation metrics now matter in the modern modeling lane, including quarter-to-date, year-to-date, and month-to-date functions.
- AI and MCP are becoming consumption surfaces over Mosaic models. The model must be explainable enough for agents, not merely executable.
- Auto Dashboard and AI features can create derived metrics and view filters; agents must distinguish those runtime/generated artifacts from governed model definitions.

## Automation pattern: legacy project to Mosaic candidate

1. Intake: read ERD, data dictionary, table list, project/report names, user/security needs, and desired access mode.
2. Mine legacy intent:
   - top-down from reports/documents using `strategy_semantic_mine.py`;
   - reverse from table IDs using dependency and bounded definition scans;
   - read legacy attribute/fact/metric/filter definitions with Modeling Service.
3. Classify warehouse roles:
   - entity lookup, descriptor lookup, fact/transaction, snapshot/aggregate, bridge, calendar, administrative/noise.
4. Generate Mosaic seed config:
   - tables first;
   - attributes/forms next;
   - relationships/hierarchies after grain review;
   - base measures/fact metrics;
   - derived metrics and transformations;
   - filters/security/access controls.
5. Build and validate:
   - create model through helper;
   - validate model;
   - publish with requested serve/access mode;
   - compare against legacy report outputs where possible.
6. Operationalize:
   - export/save model definition as YAML/Git when the tenant supports it;
   - record object IDs, assumptions, skipped legacy constructs, and validation results.

## Modeling judgment rules

- Preserve semantic intent, not just object count. A legacy report is a clue, not the entire model.
- Facts and attributes are grain contracts. Never create relationships before identifying each table's grain.
- Attribute forms matter because they separate identity from display. Keep key/display choices explicit.
- Transformations and level/dimensional metrics carry business meaning. Clone/remap from legacy definitions where possible instead of guessing formulas.
- Security filters, ACLs, roles, privileges, and runtime filters are different concepts. Translate each to the right modern surface.
- Use multiple reports/documents or usage metrics to distinguish core domain tables from incidental report-specific tables.
- Treat Mosaic model validation, Git/YAML, and MCP queryability as first-class success criteria for the modern world.
