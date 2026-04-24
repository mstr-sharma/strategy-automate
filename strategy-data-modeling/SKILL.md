---
name: strategy-data-modeling
description: Design, review, migrate, and operationalize Strategy semantic models: business process, grain, attributes, facts, metrics, relationships, hierarchies, time semantics, and validation plans for Mosaic and classic surfaces.
---

# Strategy Data Modeling

Use this skill when the user asks to design, inspect, explain, review, migrate, validate, or improve a Strategy / MicroStrategy semantic model. This skill is the planning layer that sits before execution skills such as `build-mosaic-model`, classic semantic mining, or `strategy-validation`.

## Required memory

Read these first:

- `memory/reference_data_modeling_foundations.md`
- `memory/reference_strategy_schema_objects.md`
- `memory/reference_strategy_attribute_design.md`
- `memory/reference_strategy_fact_metric_design.md`
- `memory/reference_strategy_relationship_design.md`
- `memory/reference_strategy_hierarchy_design.md`
- `memory/reference_strategy_time_modeling.md`
- `memory/reference_strategy_model_validation.md`

For Mosaic work also read:

- `memory/reference_strategy_mosaic_modeling.md`
- `memory/feedback_mosaic_relationship_wiring.md`
- `memory/feedback_consumer_grade_naming.md`

For classic / migration work also read:

- `memory/reference_strategy_legacy_semantic_modeling.md`
- `memory/reference_strategy_legacy_to_mosaic_mining.md`

## Use this before execution

Route through this skill before:

- `skill/SKILL.md` when building or patching a Mosaic model from tables
- `strategy-validation/SKILL.md` when defining what to validate
- legacy semantic mining when the user has not yet declared the target business process, grain, or object map

## Output contract

For any modeling request, produce or update a model plan containing:

1. Business process
2. Declared grain
3. Source systems and tables
4. Attributes and forms
5. Facts
6. Governed metrics
7. Relationships
8. Hierarchies
9. Time roles and transformations
10. Security / governance notes
11. Assumptions and open questions
12. Validation suite
13. Build sequence

Prefer the templates in `skill/examples/`:

- `model_plan_template.yaml`
- `attribute_plan_template.yaml`
- `relationship_plan_template.yaml`
- `validation_suite_template.yaml`

## Non-negotiable rules

- Do not create facts, dimensions, or relationships before declaring grain.
- Do not mix grains in one fact table.
- Do not create relationships from column-name similarity alone.
- Validate relationship cardinality before relying on rollups.
- Prefer governed metric definitions over exposing many raw aggregations.
- Treat hierarchies as user navigation, not merely joins.
- Use changesets for metadata writes and discard on failure.
- Close every build with validation or an explicit validation-pending note.

## Required workflow

1. Parse the business intent.
2. Identify the business process or processes.
3. Declare the grain in one sentence.
4. Identify candidate fact tables and dimension tables.
5. Draft attributes, forms, facts, metrics, and time roles.
6. Draft relationship and hierarchy plans.
7. Identify security, governance, and naming constraints.
8. Turn the draft into a structured plan file.
9. Run discovery / profiling to confirm keys, nulls, and cardinality.
10. Refine the plan from evidence before writes.
11. Hand off to the execution skill.
12. Validate and write durable findings back to memory.

## Relationship safety checks

Before relationship writes:

1. Confirm child and parent attributes exist.
2. Confirm both have ID forms.
3. Confirm required expressions exist on the relevant tables.
4. Confirm cardinality with profiling evidence.
5. Confirm the relationship is not already implied by co-resident attribute mappings.
6. Confirm the current changeset stage accepts relationship writes.

## When to ask for clarification

Stop and ask when:

- multiple grains are plausible
- metric definitions are ambiguous
- fiscal / calendar rules are unknown
- a many-to-many path may duplicate totals
- security requirements are unclear

You may proceed best-effort only when the user explicitly wants automation from known tables, the grain is high-confidence, and assumptions will be recorded and validated.

## Final answer format

Use this structure:

- Modeling summary
- Decisions made
- Model plan
- Validation plan
- Build steps
- Risks / assumptions
- Files changed or commands to run
