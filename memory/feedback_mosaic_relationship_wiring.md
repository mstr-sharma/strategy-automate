---
name: Mosaic relationship wiring + conformance — pre-flight, post-build verify, fix-forward
description: End-to-end recipe for getting Mosaic attribute conformance and relationships correct on multi-DB / mixed-case builds (Postgres lowercase + Snowflake uppercase is the canonical case). Covers the auto-conformance case-sensitivity trap, the dictionary grouping rule, the post-build attribute-expression check, the relationship PUT contract (8004ccdb / 8004ccc7), and the canonical fix recipe. Star-schema first; conformed dimensions are how Strategy's engine joins across facts.
type: feedback
tags: [mosaic, build, relationships, conformance, kimball, error-code]
---

## Rule

A shippable multi-source Mosaic model must have every cross-table query path either (a) carried by a **conformed attribute** with expressions on every participating table OR (b) wired by an explicit relationship whose `relationship_table` appears in BOTH parent and child attribute expressions. Nothing else joins. This is the Kimball conformed-dimension principle expressed through Mosaic's object model.

**Why:** on every multi-DB, mixed-case warehouse build so far (Postgres lowercase + Snowflake uppercase is the canonical case), `build_mosaic.py`'s auto-conformance silently merges some columns, orphans others, and leaves a third class (semantically-same but differently-named FKs) as standalone attributes with no path back. Issuing relationship PUTs blindly then fails with `8004ccdb` / `8004ccc7`, and operators waste the session-cap budget retrying.

## Root causes — why conformance breaks silently

Three distinct failure modes that compound in mixed-case multi-DB builds:

1. **Case-sensitive auto-conformance.** The helper groups shared column names only when they match exactly (case-sensitive). So:
   - `<dim>_id` in Postgres and `<DIM>_ID` in Snowflake do NOT conform — first match wins, the second becomes orphaned.
   - `<entity>_id` and `<ENTITY>_ID` produce an `<Entity>` attribute with only one case's expressions; the other is orphaned.
2. **FK-name divergence.** Columns that ARE the same logical FK but are named differently (e.g. `primary_<entity>_id` vs `<entity>_id`) never get grouped at all. They become standalone attributes with no path back to the dim — the Mosaic UI renders "no joins" between the event fact and the dim, which reads as "broken" to end users.
3. **Auto-conformance dedupe drops case variants silently.** When the uppercase wins the race, the lowercase column never gets added to the attribute's expression list. Relationships through the orphaned fact table then have no path.

## Why blind relationship PUTs fail — `8004ccdb` and `8004ccc7`

Even with an explicit `relationships[]` block in the dictionary, `PUT /api/model/dataModels/{id}/attributes/{childAttrId}/relationships` returns:

- **`8004ccdb`** — *"Attribute (id '…') appears in a relationship more than once."*
  - Fires when auto-conformance has already merged an attribute across ≥2 tables. Issuing a relationship whose parent is `<DIM>.<ENTITY>_ID` and child is `<FACT>.<ENTITY>_ID` is **a self-reference** — the build script resolves both sides to the same attribute object id.
- **`8004ccc7`** — *"Table (id '…') cannot be used as the join table for a relationship involving attribute (id '…')."*
  - Fires when the `relationship_table` doesn't contain an expression of BOTH parent and child. If the parent attribute has no expression on that table (e.g. `<Entity>` has no expression on the event-fact table because `primary_<entity>_id` became its own standalone attribute), `8004ccc7` fires.

## How to apply — six-step canonical recipe

1. **Write the logical-attribute plan on paper BEFORE `build`.** This is the Kimball conformed-dimension pass. For every physical column, decide: (i) it becomes a conformed dimension attribute spanning N tables, or (ii) it stays table-scoped, or (iii) it's metric fodder. Record it as a map:
   ```
   <Entity>       ← <DIM>.<ENTITY>_ID, <FACT_A>.<ENTITY>_ID, <fact_b>.<entity>_id, <event_fact>.primary_<entity>_id
   <Resource>     ← <event_fact>.<resource>_id, <fact_b>.<resource>_id, <FACT_A>.<RESOURCE>_ID
   <Timestamp>    ← <fact_b>.<service>_ts, <FACT_A>.<USAGE>_TS
   ```
   This plan is the single source of truth for the dictionary. In Kimball terms: every row here is a conformed dimension surfaced in multiple fact tables at compatible grain.

2. **Express conformance in the dictionary via identical `name`.** The build script groups `attributes[table.col]` entries by their `name` field, not by column name. So to conform `primary_<entity>_id` and `<entity>_id` into one `<Entity>` attribute:
   ```json
   "attributes": {
     "<DIM>.<ENTITY>_ID":                     {"name": "<Entity>", "description": "…"},
     "<FACT_A>.<ENTITY>_ID":                  {"name": "<Entity>"},
     "<fact_b>.<entity>_id":                  {"name": "<Entity>"},
     "<event_fact>.primary_<entity>_id":      {"name": "<Entity>"}
   }
   ```
   The auto-conformance pass collapses these into a single multi-table attribute regardless of case or column-name mismatch. The case-sensitive inference only fires when the dictionary does NOT cover the column.

   **Dictionary `relationships[]` is NOT for conformance.** Conformance is expressed by repeating the same attribute `name`. `relationships[]` is for semantically-distinct attributes that need a join path (dim → fact, role-playing dims, etc.).

3. **Declare ONLY the relationships you cannot express via conformance.** Shared-attribute joins happen for free. The dictionary `relationships[]` block is for genuinely different attributes joined through a fact table (e.g. `Event → <Entity>` through `<event_fact>` when Event is not an entity-keyed attribute). Never list a relationship where both parent and child resolve to the same logical attribute name — Mosaic rejects it as `8004ccdb`.

4. **After `build` returns, immediately GET every conformed attribute and verify `forms[*].expressions[*].tables` covers every expected table.** A missing table means auto-conformance dropped the case-mismatched variant despite the dictionary. Fix with a single PATCH changeset that adds the missing expression (clone-and-remap pattern from `reference_mosaic_clone_pattern.md`). Do this BEFORE any relationship PUTs.

5. **For each relationship, verify the `relationship_table` prerequisite: the parent attribute must have an expression on that table AND the child attribute must have an expression on that table.** If either is missing, `8004ccc7` fires. Add the missing expression first (same PATCH pattern), then issue the relationship.

6. **Validate with a Trino rollup query AT THE ATTRIBUTE GRAIN you expect users to query.** `SELECT "<entity>", SUM("<measure>") FROM "<project>"."<model_name>" GROUP BY 1` on a model with broken entity conformance will either return one row (all aggregated) or error; a correctly-conformed model returns one row per `<entity>`. If the number of rows is off by a factor of 2–N, conformance is wrong.

## Fallback — explicit ERD

If the dictionary approach is too verbose (many tables, many FKs), supply an ERD (`.dbml` / `.sql` / `.json`) covering every cross-table join. The ERD disables auto-conformance, so EVERY shared-column pair must be listed. Do not mix styles.

Relationships in an ERD, same rule as step 3: never declare parent/child that share a logical attribute — auto-conformance will have already merged them, and Mosaic will reject.

## Common failure modes this recipe catches

- *"Model has no joins"* — step 4 check fails; add missing expressions.
- *"Relationship PUT returns 8004ccdb"* — step 3 violation; parent+child already share a logical attribute.
- *"Relationship PUT returns 8004ccc7"* — step 5 violation; pick a different relationship_table or add the missing expression.
- *"Trino query returns zero rows when grouping by two attributes from different tables"* — the joining attribute is not conformed; step 2 was skipped for one of the tables.
- *"Metric values balloon vs source-table totals"* — Cartesian product because the conformance path doesn't exist; relationships are serving a Cartesian fallback. Step 4 + step 5 fix this.

## Session-cap corollary

Steps 4 and 5 typically need 2–4 `/api/model/dataModels/{id}/attributes/{aid}` GETs + 1 PATCH each. That's 10–20 project-scoped calls for a 4-table model. Batch them all inside a SINGLE Python process with one login — see `feedback_build_mosaic_session_leak.md`. Do not run them as individual `api-call` shell invocations or you will cap the user mid-fix.

## Helper script — wire-relationships subcommand

`build_mosaic.py wire-relationships --model-id <M> --hints <file>` implements the six-step recipe above:

- Validates step 3 (self-reference rejection) — skips any hint whose parent and child resolve to the same attribute id.
- Validates step 5 (relationship_table prerequisite) — skips any hint where either endpoint has no expression on the declared `relationship_table`, with a clear message pointing at the PATCH-first workflow.
- Issues only the PUTs that will succeed, in one changeset.
- `--dry-run` prints the plan and skip reasons without writing.

Hint file shape (JSON or YAML):

```json
{"relationships": [
  {"parent_attribute": "<Entity>",
   "child_attribute":  "Event",
   "relationship_table": "<event_fact>",
   "type": "one_to_many"}
]}
```

Parent/child accept either a logical attribute name or an attribute objectId; `relationship_table` accepts either a table name or table id.

## Helper-script features that implement conformance

- **`build --conformance-map <file>`** — explicit logical-name-to-columns map. File shape (JSON/YAML): `{"<Logical Name>": ["<TABLE>.<COLUMN>", ...]}`. Each listed table.column gets an attributes entry with the shared `name`, triggering conformance grouping at build time.
- **`build --fk-map <file>`** — normalize semantically-same-but-differently-named FKs. File shape: `{"<CHILD_TABLE>.<CHILD_COL>": "<PARENT_TABLE>.<PARENT_COL>"}`. Child column inherits the parent's logical name so they conform. Useful for multi-DB builds with e.g. `primary_<entity>_id` vs `<entity>_id`.

Both flags augment `--dictionary` (do not replace it). Apply order at build time: `--dictionary` loads first → `--conformance-map` overwrites `name` on listed columns → `--fk-map` overwrites `name` on listed children → column-name inference fills remaining gaps. The later flags "win" for the `name` field only; `description` and `function` from the dictionary are preserved.

## Related

- `feedback_build_mosaic_session_leak.md` — session-cap budget and batching rules.
- `reference_mosaic_relationship_archetypes.md` — the 6 canonical join patterns (star, snowflake, bridge, composite-FK, descriptive, date-hierarchy) — pick one before writing a relationship.
- `reference_mosaic_clone_pattern.md` — the PATCH-with-GET-first procedure for adding a missing expression to an existing attribute.
- `reference_data_modeling_foundations.md` — Kimball conformed-dimension principle, grain declaration, star vs snowflake topology.
