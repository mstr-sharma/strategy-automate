---
name: Build Mosaic models by mirroring the legacy semantic layer
description: When a source project already has a classic/legacy semantic model for the same domain, use it as the authoritative blueprint for the Mosaic model instead of inferring shape from warehouse columns.
type: feedback
---

Auto-inference from warehouse columns produces a messy, unusable Mosaic model when a legacy semantic layer already exists for the same domain. Always treat the legacy project as the blueprint.

**Why:** Validated against a classic retail tutorial semantic layer (a Products attribute folder with ~18 clean attributes — Brand, Category, Subcategory, Item, Supplier, Warranty, etc. — each with proper ID+DESC+locale forms, a single key form, and correct M:M/1:M relationships via item-level and bridge tables). Running `build_mosaic.py build` against the same physical warehouse tables produced 44 junk attributes (every `*_DESC_DE/ES/FR/…` locale column became its own attribute), 14 junk `Total <ID>` fact metrics (ID columns summed), and no entity attributes for FK-only dimensions like Brand/Supplier (those FK columns became attributes but had no parent-entity shape). Cartesian joins emerged at query time because intermediate bridging entity attributes were missing.

**How to apply:**
1. **Before touching the warehouse.** Read the source classic project's attribute folder(s). `GET /api/folders/{attrFolderId}` → for each attribute `GET /api/model/attributes/{id}?showExpressionAs=tokens`. Capture: `forms[]` (ID + DESC + custom), `keyForm.id`, `attributeLookupTable`, `relationships[]`, `displays.reportDisplays/browseDisplays`.
2. **Mine facts, not metrics.** Metric definitions reference facts by `objectId` with `subType:"fact"`. Pull the fact list from `Schema Objects → Facts` folder and `GET /api/model/facts/{id}?showExpressionAs=tokens` for the raw column formulas. Metrics themselves wrap facts with `Sum/Avg/...`; the fact holds the column formula (e.g., `QUANTITY * (UNIT_PRICE - DISCOUNT)`).
3. **Build the Mosaic model by cloning shape.** One Mosaic attribute per legacy attribute. ID form column = legacy ID form's column. DESC/custom forms mirror 1:1. Multi-table expressions (e.g., a parent attribute's ID form on both its lookup table AND the bridging child table) must be preserved — this is what makes the join work. Do **not** let the auto-builder invent entity names from column patterns.
4. **Skip columns the legacy model skipped.** Locale-variant description columns (`*_DE`, `*_ES`, `*_FR`, …) are multilingual storage for ONE descriptor form with `isMultilingual:true`, not 9 separate attributes. Audit columns (`LOAD_TS`, `ETL_BATCH_ID`) do not appear as attributes/metrics.
5. **Relationships come from `relationships[]` in the legacy attribute bodies**, not from shared-column inference. Pass them as an explicit ERD to the build, or wire in a post-build changeset.
6. **Metrics come from the Metrics folder's definitions**, not from numeric columns. `Total Unit Price`-style auto-metrics from raw columns are almost always wrong — the legacy model's KPI metrics are derived via fact formulas (e.g., revenue = quantity × discounted-price), not column sums.

When the user says "recreate/replicate/port the model" and a legacy project exists, assume this workflow unless they explicitly ask for fresh auto-inference. Record the legacy object IDs in the build config so the mapping is reproducible.
