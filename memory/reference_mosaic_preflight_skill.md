---
name: Mosaic preflight contextual data check
description: Reference for `skills/build-mosaic-model/scripts/preflight_model_check.py`. This is the gate the `build-mosaic-model` skill runs BEFORE build; it is not a standalone skill. Documents the 6 check categories, blueprint JSON schema, invocation syntax, and tunable lists.
type: reference
---

Preflight is step 6 of the `build-mosaic-model` execution flow (see `skills/build-mosaic-model/SKILL.md`). It is not wrapped as its own `SKILL.md` — the script is invoked directly, and ERROR-severity findings stop the build.

Location: `skills/build-mosaic-model/scripts/preflight_model_check.py`.

## When to run

Before every `build_mosaic.py build` invocation when:
- the warehouse tables are new to this project (no prior Mosaic model to diff against)
- a user has asked you to port a legacy semantic model to Mosaic (pass the blueprint JSON)
- CI is gating a config-driven build

If the build is a tiny tweak to an existing model (single attribute rename, metric formula change), skip preflight and lean on `validate-model` post-build instead.

## Invocation

```bash
python3 skills/build-mosaic-model/scripts/preflight_model_check.py \
  --instance "<Your DB Instance>" --schema <YOUR_SCHEMA> \
  --tables T1 T2 T3 FACT \
  --blueprint /tmp/model_blueprint.json \
  --out /tmp/preflight.json \
  --fail-on ERROR
```

Exit code `1` when any finding at `--fail-on` severity or above is present — wire this into CI or a pre-build Makefile target.

## What it checks (6 categories)

1. **Naming convention** — mixed-case duplicates, locale-column explosion (`*_DE/_ES/_FR/...`), audit-column pollution (`LOAD_TS`, `ETL_BATCH_ID`, ...), non-identifier characters requiring quoting.
2. **Attribute vs metric classification** — for each column, predicts the build's role assignment and flags mismatches: numeric ID columns that would get SUM'd (`Total X ID` anti-pattern), natural numeric dimensions (YEAR/MONTH/QUARTER) misclassified as metrics, text columns that look like dates.
3. **Datatype sanity** — `decimal(38,0)` IDs (valid but flagged), text columns named `*_DATE`, over-wide varchar.
4. **Relationship inferability** — no shared ID columns across tables (ERROR), bridge-table candidates (INFO), orphan key columns with no join partner.
5. **Contextual fit vs legacy blueprint** (when `--blueprint` given) — missing attributes, expected multi-form attributes, blueprint relationships to propagate, metric definitions that are derived formulas (not plain sums).
6. **Governance guards** — PII-looking columns (EMAIL, SSN, DOB, PHONE, ADDRESS, LAT/LON, CREDIT_CARD) prompting ACL/security-filter decisions.

## Blueprint JSON schema

Produced by `strategy_semantic_mine.py blueprint <attr-folder-id>` (or hand-written):

```json
{
  "attributes": {
    "Category": {
      "forms": [
        {"category":"ID","col":"CATEGORY_ID","table":"LU_CATEGORY"},
        {"category":"DESC","col":"CATEGORY_DESC","table":"LU_CATEGORY","isMultilingual":true}
      ]
    }
  },
  "relationships": [
    {"parent":"Category","child":"Subcategory","type":"one_to_many","table":"LU_SUBCATEG"}
  ],
  "metrics": {
    "Revenue": {"function":"sum","expression":"QTY_SOLD * (UNIT_PRICE - DISCOUNT)","tables":["ORDER_DETAIL"]}
  }
}
```

## Output

- `--out /tmp/preflight.json` — full report including column counts, summary counts per severity, and each finding's `{severity, code, subject, message, fix}`.
- Human-readable table to stdout, grouped by severity.

## Tunable lists

The script's `LOCALE_SUFFIXES`, `AUDIT_COLS`, `PII_HINTS`, `ID_TOKENS`, `NATURAL_NUMERIC_DIMS`, `NUMERIC_DATATYPES` constants should be edited if the org uses different conventions. Keep customizations in a config file rather than forking the script when possible.

## Why this exists

Without preflight, the default `build_mosaic.py build` inference produces unusable models on any warehouse with:
- locale-variant description columns (N attributes per language)
- numeric ID columns (`Total X ID` junk metrics)
- FK columns without a corresponding dim table (missing entity attributes → cartesian at query time)

Each of these was caught empirically on prior Mosaic builds across different warehouse schemas. The preflight codifies those lessons so they don't recur. Applicable to any DB engine — the checks are driven by column names, datatypes, and relationship topology, not a specific vendor.

## Contextual-sense validation (the "does this make sense?" question)

Beyond column-level checks, the preflight checks whether the *model as a whole* matches the domain. When a blueprint is supplied, it treats the legacy model as the oracle: any attribute, form, or relationship in the blueprint that can't be mapped to warehouse columns is an ERROR. Without a blueprint, the script falls back to heuristics (shared-key join inferability, PII exposure, bridge detection). Both modes call out findings with a concrete `fix:` line so the operator can either fix the warehouse input or annotate a dictionary/ERD before the build.
