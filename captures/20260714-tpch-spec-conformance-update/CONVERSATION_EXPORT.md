# Conversation Export — TPCH_SF10 Mosaic Model: build check → data-dictionary conformance update

**Environment:** Claude Code (model: Opus 4.8) · working dir `/Users/<operator-login>/Desktop/strategy-automate` · git branch `main`
**Date:** 2026-07-14
**Tenant:** <tenant>.strategy.com (Shared Studio project)
**Model in scope:** `Snowflake TPCH_SF10 Model` — id `86B0BB9DF6F44F7D9A2BF3D25F99705E` (connect_live)

> **Redaction note:** The studio password surfaced in `<creds-file>` and in an env file during the session. It is shown here as `<REDACTED>`. The live value remains in `ignore/<creds-file>`.

---

## Table of contents
1. [Original request (create model)](#1-original-request)
2. [Skill load + context gathering](#2-skill-load--context-gathering)
3. [Auth + existing-model discovery](#3-auth--existing-model-discovery)
4. [Decision point — user redirect to "update per data dictionary"](#4-decision-point)
5. [Locating and reading the spec PDF](#5-locating-and-reading-the-spec-pdf)
6. [Diffing the live model against the spec](#6-diffing-the-live-model-against-the-spec)
7. [Applying the 10 attribute-description updates](#7-applying-the-10-attribute-description-updates)
8. [Verification + validate-model quality gate](#8-verification--validate-model)
9. [Memory update](#9-memory-update)
10. [Second pass — full technical-spec audit (types/formats/PII)](#10-second-pass--full-technical-spec-audit)
11. [Video tag lines](#11-video-tag-lines)
12. [This export](#12-this-export)
13. [Appendix A — spec.json (structured spec used for diffing)](#appendix-a--specjson)
14. [Appendix B — key tenant IDs](#appendix-b--key-tenant-ids)

---

## 1. Original request

**User:** (with an attached TPC-H SF10 ERD image)

> You are tasked to create a Mosaic model based on tables in the Snowflake TPCH database:
> 1. Use the 'Snowflake Sample Data' DB and the 'TPCH_SF10' schema.
> 2. Use the attached ERD as a guide for how to construct the model.
> 3. Use the <creds-file> file in the repo for access details to the Studio Environment
> 4. Create a live connect model in the Studio project, name it 'Snowflake TPCH_SF10 Model'
> 5. Save and publish the model in Shared Reports > Collaboration > <operator>

The attached ERD showed the standard TPC-H 8-table schema: REGION → NATION → (SUPPLIER, CUSTOMER), PART/PARTSUPP sourcing bridge, CUSTOMER → ORDERS → LINEITEM, with LINEITEM joining PART and SUPPLIER.

---

## 2. Skill load + context gathering

**Action:** Invoked the `build-mosaic-model` skill (execution layer for Mosaic model creation/modification).

**Tool: Skill** — `build-mosaic-model` with args describing the build request. The skill instructed loading memory files, resolving the DB instance, discovering tables, translating business logic, preflight, build, verify, relationships, validate, publish.

**Context reads (parallel):**

- `Bash` — read `<creds-file>` (repo root had no studio block; creds live in `ignore/<creds-file>`) and listed `captures/20260617-tpch-studio-build/`.
  - Studio creds block:
    ```
    studio:
      login: <operator-login>
      url: https://<tenant>.strategy.com/MicroStrategyLibrary/app
      password: "<REDACTED>"
    ```
  - Capture dir contained a **complete proven recipe**: `README.md`, `dictionary.json`, `merge-hints.json`, `wire-hints.json`, `desc-hints.json`, `polish.py`, `tq.py`, `build-summary.json`.

- `Read` — `~/.claude/.../memory/project-studio-tenant-quickref.md`. Key facts:
  - Base: `https://<tenant>.strategy.com/MicroStrategyLibrary`
  - Project "Shared Studio": `1FC5A43B374C963CC773C285DF86E2F6`
  - DB instance "Snowflake Sample Data": `245EBDFD85458E568C76FCB353406E93` (schema `TPCH_SF10`)
  - Dest folder "Collaboration > <operator>": `DC377018BD4CACD81B7E4CAEB8DB62B4`
  - **A model named "Snowflake TPCH_SF10 Model" (`86B0BB9DF6F44F7D9A2BF3D25F99705E`) was already built 2026-07-10** — connect_live, in the target folder, 8 tables / 35 attrs / 10 metrics / 36 rels, validate PASS with 7 by-design WARNs.
  - Tenant rules: identity-token OFF is the verified-working default; one process/one session per pipeline; connect_live models are Trino-queryable with no cube publish; avoid bare `COUNT(*)`; avoid CASE on metric columns.

- `Read` — the capture `README.md`, `dictionary.json`, `merge-hints.json`, `wire-hints.json`, `desc-hints.json`, `tq.py`, and `memory/reference_mosaic_build_skill.md` (subcommand index), and `memory/reference_strategy_env.md` (env-var configuration model).

**Recipe summary (from README):** TPC-H prefixed keys (R_/N_/S_…) defeat auto-conformance, so the canonical build is: `build --skip-relationships` + dictionary → `merge-attributes` (conform 9 FK cols into 6 key dims) → `wire-relationships` (9 entity joins) → `wire-relationships` (27 descriptor joins) → `polish.py` (formats) → `validate-model`.

**Verified `merge-attributes` subcommand exists** (`Bash` grep of `build_mosaic.py`), and reviewed the one-line local diff to `build_mosaic.py`:
```diff
-    "data_model": {"path": ".../dataModels/{model_id}", "needs_model": True, "changeset": False},
+    "data_model": {"path": ".../dataModels/{model_id}", "needs_model": True, "changeset": True},
```
(benign).

---

## 3. Auth + existing-model discovery

**Env file written** to scratchpad (`studio.env`), sourced into each Bash call:
```bash
export MSTR_BASE="https://<tenant>.strategy.com/MicroStrategyLibrary"
export MSTR_USER="<operator-login>"
export MSTR_PASSWORD="<REDACTED>"
export MSTR_LOGIN_MODE=1
export MSTR_PROJECT_ID="1FC5A43B374C963CC773C285DF86E2F6"
export MSTR_DEST_FOLDER_ID="DC377018BD4CACD81B7E4CAEB8DB62B4"
export TRINO_SCHEMA="shared studio"
export TRINO_CATALOG="sql"
```

**`build_mosaic.py auth-probe`** →
```json
{ "ok": true, "base": "https://<tenant>.strategy.com/MicroStrategyLibrary",
  "project_id": "1FC5A43B374C963CC773C285DF86E2F6", "user": "<operator-login>",
  "has_auth_token": true, "has_identity_token": true, "project_access": true }
```

**`search-objects --name "Snowflake TPCH_SF10 Model" --type 3`** — fuzzy search returned many models; exact-name filter initially returned no match, so I confirmed the recorded id directly:

**`api-call GET /api/objects/86B0BB9DF6F44F7D9A2BF3D25F99705E?type=3`** → HTTP 200. Body:
- name = **Snowflake TPCH_SF10 Model**
- owner = **<operator>**
- dateModified = **2026-07-10T17:54:00Z**
- path = **Shared Studio > Public Objects > Reports > Collaboration > <operator>**

**`list-tables --instance-id 245EBDFD85458E568C76FCB353406E93 --namespace TPCH_SF10`** → confirmed the 8 TPC-H tables present (REGION, NATION, SUPPLIER, CUSTOMER, PART, PARTSUPP, ORDERS, LINEITEM) with base64 catalog IDs.

**Conclusion:** the exact deliverable already existed in the exact target folder.

---

## 4. Decision point

Because re-creating would collide on name or leave a stale duplicate, I surfaced the finding and asked how to proceed.

**Tool: AskUserQuestion** — options: *Rebuild fresh* / *Reuse & verify* / *Build a duplicate*.

**User answer (free-text override):**
> "make updates to the model specifically for the data dictionary that was just uploaded. Focus on object descriptions, relationships, and metric aggregations"

This redirected the task from *create* to *update the existing model to conform to a newly-uploaded data dictionary*, focused on **descriptions, relationships, metric aggregations**.

---

## 5. Locating and reading the spec PDF

**`Bash`** — searched for recently-modified / dictionary-like files. Candidates:
- `ignore/tpch_sf10_dictionary.json` (Jun 17 — old)
- **`/Users/<operator-login>/Desktop/TPCH_SF10_Model_Spec.pdf` (created today, Jul 13 13:38)** ← the just-uploaded spec

**`Read` (PDF, 4 pages)** — "Data Dictionary & Metric Specification", v1.0 · 2026-07-13, DRAFT — for build. Contents:
- **§1 Entities & grain** — 8 tables with roles (REGION/NATION/SUPPLIER/CUSTOMER/PART dims, PARTSUPP bridge, ORDERS fact-header, LINEITEM primary fact) and grain descriptions.
- **§2 Attributes** — 35 attributes (ATTR-01…35): business name, technical column, type, role (entity key / descriptor / bridge grain / grain key / time), sample-domain values, **and terse business descriptions** (domain enums kept in a *separate column*, not in the description). 4 marked **PII**: Supplier Address, Supplier Phone, Customer Address, Customer Phone.
- **§3 Metrics** — 10 measures (MET-01…10): expression, aggregation (6× SUM, 4× AVG), type, format (Currency `$#,##0.00` / Percent `0.00%` / Integer `#,##0`), additivity, description.
- **§4 Relationships** — 9 one-to-many entity joins.

**Key insight:** the spec's descriptions are the *cleaned* form — e.g. `Order status code.` where the live model had `Order status (O = open, F = finalized, P = partial).` (live model was built from the June recipe, which embedded domain enums in the description).

---

## 6. Diffing the live model against the spec

**Structured spec written** to `scratchpad/spec.json` (attributes → description; metrics → function/description/format; tables → description; relationships list). See [Appendix A](#appendix-a--specjson).

**Live model pulled via modeling sub-resource endpoints:**
- `GET /api/model/dataModels/{id}/attributes?limit=500` → **35** attributes
- `GET /api/model/dataModels/{id}/factMetrics?limit=500` → **10** metrics
- `GET /api/model/dataModels/{id}/tables?limit=500` → **8** tables
- `dataServeMode` = **connect_live**
- (`.../relationships` returned 404 — relationships are embedded per-attribute instead)

**Object structure learned:**
- Attribute: `information.{name, description, objectId}`, `forms[]` (ID/DESC, each with `dataType`, expression, tables), `relationships[]`.
- Metric: `information.{name, description, objectId}`, `function` (sum/avg), `fact.dataType`, `format.values[]` (number_category / number_format / decimal_places).
- Logical table: `information` only — **no description field** (table descriptions not editable in this layer).

**Diff results:**

**(a) Attribute descriptions — 10 differ.** Live carried parenthetical domain enums; spec wants them terse:

| Attribute | Live (before) | Spec |
|---|---|---|
| Region Name | Geographic region name (AFRICA, AMERICA, ASIA, EUROPE, MIDDLE EAST). | Geographic region name. |
| Nation Name | Country name (e.g., UNITED STATES, GERMANY, CHINA). | Country name. |
| Market Segment | Customer market segment (AUTOMOBILE, BUILDING, FURNITURE, HOUSEHOLD, MACHINERY). | Customer market segment. |
| Part Size | Part size code (1-50). | Part size code. |
| Order Status | Order status (O = open, F = finalized, P = partial). | Order status code. |
| Order Priority | Order priority tier (1-URGENT, 2-HIGH, 3-MEDIUM, 4-NOT SPECIFIED, 5-LOW). | Order priority tier. |
| Return Flag | Line return flag (R = returned, A = accepted, N = none). | Line return flag. |
| Line Status | Line status (O = open, F = fulfilled). | Line status code. |
| Ship Instructions | Shipping instructions (DELIVER IN PERSON, COLLECT COD, NONE, TAKE BACK RETURN). | Shipping instructions. |
| Ship Mode | Shipping mode (AIR, FOB, MAIL, RAIL, REG AIR, SHIP, TRUCK). | Shipping mode. |

The other 25 attribute descriptions already matched.

**(b) Metrics — 0 differ.** All 10 already had the correct function (6 SUM / 4 AVG), description, and format token. No change needed.

**(c) Relationships — 0 differ.** Aggregating the per-attribute `relationships[]` gave **36 unique** logical relationships. All **9** spec entity joins present:
```
Region 1:M Nation (NATION)            OK
Nation 1:M Supplier (SUPPLIER)         OK
Nation 1:M Customer (CUSTOMER)         OK
Customer 1:M Order (ORDERS)            OK
Order 1:M Line Number (LINEITEM)       OK
Part 1:M Part-Supplier Comment (PARTSUPP)      OK
Supplier 1:M Part-Supplier Comment (PARTSUPP)  OK
Part 1:M Line Number (LINEITEM)        OK
Supplier 1:M Line Number (LINEITEM)    OK
```
(plus 27 descriptor→entity joins = 36 total logical / 72 directional).

**Net delta to apply: 10 attribute descriptions.**

---

## 7. Applying the 10 attribute-description updates

To honor the one-process/one-session rule, a single script (`scratchpad/apply_desc.py`) was written that:
1. Reuses the `MSTR` class + `open_cs`/`commit_cs`/`discard_cs` helpers from `build_mosaic.py`.
2. Logs in **once** with `identity=False` (per the studio tenant rule that identity-off works for reads AND writes).
3. For each changed attribute: `GET` full object → set `information.description` → `open_cs(schema_edit=False)` → `PATCH {"information": <full info + new description>}` → `commit_cs` → re-`GET` to verify.
4. Per-attribute changeset (so a failure can't roll back already-committed edits); dry-run mode when `--commit` absent.

**PATCH body shape** (minimal-safe — replaces only the `information` top-level field, preserving all sub-keys; leaves `forms`/`relationships`/etc. untouched):
```json
{ "information": { ...all existing info keys..., "description": "<new terse description>" } }
```

**Run 1 — dry run (all):** listed 10 planned changes, 25 already-matching, 0 errors.

**Run 2 — live single-attribute test (`--only "Region Name"`):**
```json
{ "commit": true,
  "changed": [{ "attr": "Region Name",
    "from": "Geographic region name (AFRICA, AMERICA, ASIA, EUROPE, MIDDLE EAST).",
    "to": "Geographic region name.", "status": "OK" }],
  "errors": [] }
```
Confirmed identity-off writes succeed and the verify read reflects the change.

**Run 3 — remaining 9 (`--commit`):** all 9 changed with `status: OK`, 0 errors. (Region Name already done, so it appeared under `already_matching`.)

---

## 8. Verification + validate-model

**Fresh re-fetch of attributes** + full spec comparison:
```
ATTRIBUTE DESCRIPTIONS: 35/35 match spec
METRICS (func+desc):    10/10 match spec  ALL OK
```

**`validate-model --model-id 86B0BB9DF6F44F7D9A2BF3D25F99705E`** → **PASS**
```
counts: tables=8 attributes=35 factMetrics=10 relationships=72
WARN (7):
  [W6] 4 date attributes missing derived grains (Day/Month/Quarter/Year) — Commit/Order/Receipt/Ship Date
  [W3] REGION has only 1 distinct parent dim declared — heuristic false positive
  [W4] Supplier/Customer Account Balance are SUM but name suggests rate/price/balance
```
All 7 WARNs are the **same by-design** items from the original build. W4 is **spec-correct** — MET-01/MET-02 are explicitly defined SUM / Additive. Nothing regressed (metadata-only edit).

---

## 9. Memory update

**`Edit`** to `project-studio-tenant-quickref.md` — appended to the model's entry: updated 2026-07-13 to spec v1.0; cleaned 10 attribute descriptions (spec keeps descriptions terse, enums in a separate column); metrics + relationships already matched; PATCH shape recorded; **identity-off login reconfirmed working for these writes**; W4 acctbal-SUM WARN is spec-correct.

---

## 10. Second pass — full technical-spec audit

**User:** re-attached `TPCH_SF10_Model_Spec.pdf` — "also use the attached data dictionary for business and technical specifications."

Interpreted as: ensure the **full** spec (business *and* technical) is applied, not just descriptions. Ran a comprehensive audit.

**Metric technical audit** (function / data type / format string):

| Metric | fn | type | format | verdict |
|---|---|---|---|---|
| Supplier Account Balance | sum | double | `$#,##0.00;($#,##0.00)` | OK |
| Customer Account Balance | sum | double | `$#,##0.00;($#,##0.00)` | OK |
| Avg Retail Price | avg | double | `$#,##0.00;($#,##0.00)` | OK |
| Total Available Quantity | sum | int64 | `#,##0` | OK (`int64` = bigint) |
| Avg Supply Cost | avg | double | `$#,##0.00;($#,##0.00)` | OK |
| Total Order Price | sum | double | `$#,##0.00;($#,##0.00)` | OK |
| Avg Discount Rate | avg | double | `0.00%` | OK |
| Total Extended Price | sum | double | `$#,##0.00;($#,##0.00)` | OK |
| Total Quantity | sum | double | `#,##0` | OK |
| Avg Tax Rate | avg | double | `0.00%` | OK |

**Attribute data-type audit:** DESC-form `dataType` vs spec TYPE (bigint/varchar/date), normalized → **0 diffs across all 35**.

**PII / classification scan:** scanned every attribute object key for `class`/`sensi`/`pii`/`tag`/`secur`/`privac` → **NONE**. Mosaic attributes in this modeling layer have **no native PII/classification property**.

**Full conformance matrix:**

| Spec element | Status |
|---|---|
| Business names (35 attrs + 10 metrics) | ✅ all match |
| Business descriptions (35 attrs) | ✅ all match |
| Attribute data types | ✅ 0 diffs |
| Metric expressions / aggregation / type / format / additivity | ✅ all match |
| Relationships (9 entity joins) | ✅ all present (36 logical / 72 directional) |
| Roles (key/conformed/bridge/grain/time) | ✅ reflected via conformance + relationships |
| **PII flags (4 attrs)** | ⚠️ no native model field — governance-only |
| **Table (entity) descriptions** | ⚠️ no editable field on logical tables |

**Surfaced to user:** PII classification can only be enforced via a governance mechanism (row/column security filter or ACL) which changes data access — not taken unprompted; asked whether to apply a governance mechanism or leave PII as documentation-only. (Awaiting decision.)

---

## 11. Video tag lines

**User:** requested tag lines for 5 video scenes. Delivered (primary + alternate each):

1. **Reading from the ERD** — "From diagram to data model — Claude reads the schema at a glance." / *"Every table, key, and join path — understood in seconds."*
2. **Reading from the tech spec** — "Business names, aggregations, PII flags — the spec becomes the blueprint." / *"One data dictionary in. A fully governed semantic layer out."*
3. **Finishing the model build** — "8 tables, 35 attributes, 10 governed metrics — wired, validated, done." / *"Star schema, conformed dimensions, clean rollups — built right the first time."*
4. **Exploring the model in the Mosaic GUI** — "Live-connected to Snowflake — explore 60M line items, no cube required." / *"Trusted metrics, ready the moment the model lands."*
5. **Using Claude for analysis + dashboard** — "Ask a question, get an answer, get a dashboard — analytics at the speed of thought." / *"From semantic model to insight to dashboard — Claude closes the loop."*

---

## 12. This export

**User:** requested a full export of the conversation (all steps, tool calls, arguments, results, intermediary steps). This document is that export, written to
`captures/20260714-tpch-spec-conformance-update/CONVERSATION_EXPORT.md`. The studio password is redacted.

---

## Appendix A — spec.json

The structured spec used for diffing (written to scratchpad):

```json
{
  "attributes": {
    "Region": "Region identifier (key); top of the geographic hierarchy.",
    "Region Name": "Geographic region name.",
    "Nation": "Nation identifier (key); a country within a region.",
    "Nation Name": "Country name.",
    "Supplier": "Supplier identifier (key).",
    "Supplier Name": "Supplier company name.",
    "Supplier Address": "Supplier street address.",
    "Supplier Phone": "Supplier contact phone number.",
    "Customer": "Customer identifier (key).",
    "Customer Name": "Customer name.",
    "Customer Address": "Customer street address.",
    "Customer Phone": "Customer contact phone number.",
    "Market Segment": "Customer market segment.",
    "Part": "Part identifier (key).",
    "Part Name": "Part descriptive name.",
    "Manufacturer": "Part manufacturer.",
    "Brand": "Part brand.",
    "Part Type": "Part type / specification.",
    "Part Size": "Part size code.",
    "Container": "Part packaging container.",
    "Part-Supplier Comment": "Part-supplier sourcing record; the bridge grain joining Part and Supplier.",
    "Order": "Order identifier (key).",
    "Order Status": "Order status code.",
    "Order Date": "Date the order was placed.",
    "Order Priority": "Order priority tier.",
    "Order Clerk": "Clerk who recorded the order.",
    "Ship Priority": "Order shipping priority code.",
    "Line Number": "Line number within an order; identifies the line-item grain.",
    "Return Flag": "Line return flag.",
    "Line Status": "Line status code.",
    "Ship Date": "Date the line item shipped.",
    "Commit Date": "Committed delivery date for the line item.",
    "Receipt Date": "Date the line item was received.",
    "Ship Instructions": "Shipping instructions.",
    "Ship Mode": "Shipping mode."
  },
  "metrics": {
    "Supplier Account Balance": {"function": "sum", "format": "currency"},
    "Customer Account Balance": {"function": "sum", "format": "currency"},
    "Avg Retail Price": {"function": "avg", "format": "currency"},
    "Total Available Quantity": {"function": "sum", "format": "integer"},
    "Avg Supply Cost": {"function": "avg", "format": "currency"},
    "Total Order Price": {"function": "sum", "format": "currency"},
    "Avg Discount Rate": {"function": "avg", "format": "percent"},
    "Total Extended Price": {"function": "sum", "format": "currency"},
    "Total Quantity": {"function": "sum", "format": "integer"},
    "Avg Tax Rate": {"function": "avg", "format": "percent"}
  },
  "relationships": [
    ["Region", "Nation", "NATION"],
    ["Nation", "Supplier", "SUPPLIER"],
    ["Nation", "Customer", "CUSTOMER"],
    ["Customer", "Order", "ORDERS"],
    ["Order", "Line Number", "LINEITEM"],
    ["Part", "Part-Supplier Comment", "PARTSUPP"],
    ["Supplier", "Part-Supplier Comment", "PARTSUPP"],
    ["Part", "Line Number", "LINEITEM"],
    ["Supplier", "Line Number", "LINEITEM"]
  ]
}
```

---

## Appendix B — key tenant IDs

| Object | ID |
|---|---|
| Base URL | `https://<tenant>.strategy.com/MicroStrategyLibrary` |
| Project "Shared Studio" | `1FC5A43B374C963CC773C285DF86E2F6` |
| DB instance "Snowflake Sample Data" | `245EBDFD85458E568C76FCB353406E93` (schema `TPCH_SF10`) |
| Dest folder "Collaboration > <operator>" | `DC377018BD4CACD81B7E4CAEB8DB62B4` |
| Model "Snowflake TPCH_SF10 Model" | `86B0BB9DF6F44F7D9A2BF3D25F99705E` |
| Model URL | `https://<tenant>.strategy.com/MicroStrategyLibrary/app/library#/model/86B0BB9DF6F44F7D9A2BF3D25F99705E` |
| Trino | host `<tenant>.strategy.com`, catalog `sql`, schema `"shared studio"` |

---

*End of export.*
