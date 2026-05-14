---
name: Strategy REST error-code index
description: Flat lookup of every Strategy / Mosaic error code observed in this repo — 8004cc## / 8004cd## / 8004cf## / 8004e4## codes plus signed iServerCodes — keyed to the specific memory file that teaches the fix. Grep this file first when a 4xx/5xx response surfaces before grepping anywhere else.
type: reference
tags: [error-code, mosaic, classic, publish, build, session-management, kimball]
---

## How to use this file

When a Strategy REST call returns 4xx or 5xx, you'll see a `code` field (e.g., `8004ccdb`) and often an `iServerCode` (e.g., `-2147072486`). Grep this file for the code — each row points to the memory file with the root cause and fix. This is the fastest path from symptom to resolution.

**Do not retry blind on any of these codes.** All are class-of-error conditions (structural / resource / permission), not transient network issues. Retry without diagnosis burns session cap.

## Code index — Mosaic / Modeling Service

| Code | Symptom | Root cause / Kimball lens | Fix file |
| --- | --- | --- | --- |
| `8004cb0a` (iServerCode `-2147072486`) | "Maximum number of interactive session per user for project exceeded" | iServer project-interactive session cap. `DELETE /api/auth/login` does NOT reap these — they age out on ~30-min idle. | `feedback_build_mosaic_session_leak.md` |
| `8004cc10` | "Object Description …" — PATCH with >250-char description rejected | Mosaic data-model description has an undocumented ~250-char cap. Truncate; detail goes in external docs. | `feedback_mosaic_description_length_cap.md` |
| `8004cc63` | "Attribute does not contain a form with the ID" on PATCH | Post-build form-category PATCH is fragile. Fix form names at CREATE time. | `feedback_consumer_grade_naming.md` |
| `8004cc7c` *(if seen)* / `8004c767` | "attribute_form_custom … not found in metadata" for predicate_form_qualification on a CUSTOM DESC form | Use `predicate_element_list` (Shape B) for SF qualifications on custom forms. | `reference_mosaic_security_filter.md` |
| `8004ccc7` | "Table cannot be used as the join table for a relationship involving attribute" | `relationship_table` does not contain an expression of BOTH parent AND child attribute. Kimball: the fact row must physically connect both conformed dims. Pre-flight with `validate_join_table_membership()` from `build_mosaic.py`. | `feedback_mosaic_relationship_wiring.md` |
| `8004ccdb` | "Attribute appears in a relationship more than once" | Self-reference — parent and child resolve to the same conformed attribute object id. Kimball: you don't declare a relationship between two columns of the same conformed dim; the dim IS the join. | `feedback_mosaic_relationship_wiring.md` |
| `8004ccde` | "The tree or token is required for expression" on attribute PATCH | A form expression was sent with only `text` (read-only on GET). Writes require `tokens` or `tree`. Use `mosaic_safety.make_expression()` or `normalize_expressions()`. | `reference_mosaic_safety_helpers.md` |
| `8004ccfc` | "Duplicate model name in folder" | Old model still present. Delete via `DELETE /api/objects/{oldMID}?type=3`. | `reference_mosaic_clone_pattern.md` |
| `8004cd0a` | "form property requires a non-empty name" | During UPDATE every form in `forms[]` must have a non-empty name. At CREATE, name can be omitted. | `feedback_consumer_grade_naming.md` |
| `8004cd15` | "Object (of type: Attribute) not allowed in this place" — PATCH refs auto-generated managed attribute IDs | PATCH validator resolves column-reference tokens against MSTR's managed-attribute objects. Use `character` operator tokens instead. | `feedback_mosaic_gotchas.md` |
| `8004cf06` | "attribute has no report display" at commit | Step 4 of the clone-and-remap PATCH was missed — `displays.reportDisplays` not set. | `reference_mosaic_clone_pattern.md` |
| `8004d232` | "The table change will make connect-live Mosaic model invalid" | Multi-DB (≥2 databaseInstance.objectId) under `dataServeMode: connect_live`. Use `in_memory` instead. | `feedback_mosaic_multi_db_connect_live.md` |
| `8004e409` | "Duplicate attribute name" | Conformed dim not declared — same logical entity created as N separate attributes. Kimball: promote to one conformed attribute with multi-table expressions. | `feedback_mosaic_relationship_wiring.md` |
| `8004e42f` | "Table has no attribute/metric" at commit | A table was created without any attribute or metric bound to it. Commit rejects. | `reference_mosaic_clone_pattern.md` |
| `8004e457` | "Given object is not a Mosaic model" | Object is not subType 779. Call `GET /api/objects/{id}?type=3` and check `subType` before any `/api/model/dataModels/*` call. | `reference_mosaic_vs_legacy_surfaces.md` |
| iServerCode `-2147072194` | 500 "Cube report … is being published by job N" on `GET /api/dataModels/{id}/publishStatus` | Two publish endpoints fired concurrently — `/api/cubes/{id}?cubeAction=publish` AND `/api/dataModels/{id}/publish`. The losing instance's `publishStatus` locks out for the full job. | `feedback_mosaic_publish_endpoint_collision.md` |
| iServerCode `-2147212544` | CubeServer parallel-mode stall on in-memory publish | Physical-table `dataType` values carry warehouse-catalog sentinels (`variable_length_string`, `fixed_length_string`, `precision=-1`, etc.). Clone UI-verified types. | `feedback_mosaic_publishable_datatypes.md` |
| iServerCode `-2147209151` (404) | `/api/projects/{id}` reports project not loaded | Project is unloaded. Probe `/api/projects` + `/api/projects/{id}` before use. | `reference_strategy_project_loading.md` |

## Code index — classic / project semantic layer + ACL

| Code | Symptom | Root cause | Fix file |
| --- | --- | --- | --- |
| `8004c738` | "User does not have Control access" on `GET /api/model/dataModels/{id}/securityFilters` | Session user is not the owner. Only the SF owner can list per-model SFs. Expected response when sweeping across a tenant — filter these out of inventory. | `reference_strategy_mosaic_field_study.md` |
| `ERR001` (generic) | Generic platform error wrapper | Inspect `iServerCode` to classify. Not actionable on its own. | — |

## Symptom index (when you don't know the code)

| Symptom | Likely code | Fix file |
| --- | --- | --- |
| "Model has no joins" in the Mosaic UI despite shared columns | — (no error, silent fail) | `feedback_mosaic_relationship_wiring.md` |
| Trino query returns zero rows across a cross-table group-by | — (silent) | `feedback_mosaic_relationship_wiring.md` |
| Metric totals balloon by a factor of N vs source | — (silent Cartesian) | `feedback_mosaic_relationship_wiring.md` |
| Publish status stuck at 500 for minutes, cube actually materialized | `-2147072194` | `feedback_mosaic_publish_endpoint_collision.md` |
| Publish silently never produces a queryable cube | `-2147212544` | `feedback_mosaic_publishable_datatypes.md` |
| Changeset commit fails with no clear reason after many calls | `8004cb0a` | `feedback_build_mosaic_session_leak.md` |
| Conformed dim duplicated across tables (`Customer`, `Customer (Orders)`, `Customer (Shipments)`) | `8004e409` OR silent conformance skip | `feedback_mosaic_relationship_wiring.md` |
| Form name shows as "R Regionkey ID" or "None" in UI | — (quality issue) | `feedback_consumer_grade_naming.md`, `feedback_mosaic_forms_and_formats.md` |

## Housekeeping

- Every new durable feedback file that teaches a fix for a new code MUST add a row here. This is the index-of-record.
- Do not delete rows. If a code is no longer reproducible on a newer iServer build, annotate with `(verified fixed in iServer <version>)` — future operators on older tenants still need the note.
- Kimball lens: many of these codes surface when the model violates a conformed-dim or star-schema invariant (`8004ccc7`, `8004ccdb`, `8004e409`). When you see one, ask "what would Kimball do here?" before reaching for a REST workaround.
