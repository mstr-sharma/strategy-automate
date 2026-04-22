---
name: Mosaic attribute form displays + metric formatting rules
description: Mandatory defaults for every Mosaic model Claude builds — DESC forms drive report/browse displays, and numeric metrics get sensible end-user formats (currency, percent, integer, scientific) based on semantic context.
type: feedback
---

## Rule 1 — All DESC forms are the display + browse forms

When creating a multi-form attribute, the ID form is the key for joins but **must never** be the form a user sees on a report or a prompt element list. Always set:

```json
"displays": {
  "reportDisplays":  [ {"id": "<desc form id>", "name": "DESC"} ],
  "browseDisplays":  [ {"id": "<desc form id>", "name": "DESC"} ]
}
```

- If the attribute has one DESC form, both arrays reference it.
- If the attribute has multiple DESC-category forms (DESC + Long Desc + Foreign Name, etc.), `reportDisplays` lists them in priority order; `browseDisplays` uses the most-readable one (typically DESC).
- If the attribute is ID-only (no DESC exists), **don't** leave displays as `[{"id":ID_FORM}]`; either skip the `displays` block entirely or add a compact text form synthesized from the ID (e.g., `"Brand " + BRAND_ID`).

**Why:** users in Library/Dossier/prompts see raw ID numbers instead of names when the display form defaults to ID. Every consumer-grade complaint I've seen against auto-built models traces to this default. The legacy semantic layer already has this configured correctly — mirror it when porting.

**How to apply:** after every `make_attr()` call in the build helper, update the displays block before POST. For the build-mosaic skill, change the default `displays` generator to use the first non-ID form if one exists; only fall back to ID when no descriptor exists.

## Rule 2 — Metrics get sensible numeric formats

The Modeling Service `format.values[]` token list drives how numbers render. Never ship a metric with the default "generic" format — pick a format based on what the metric represents:

| Metric kind | Format category | Token shape |
|---|---|---|
| Dollar/currency (Revenue, Cost, Profit, Sales, Price) | currency | `[{"type":"number_category","value":"2"},{"type":"number_decimal_places","value":"2"},{"type":"number_format","value":"$#,##0.00;($#,##0.00)"}]` |
| Percent (Discount Rate, Margin, Growth %) | percent | `[{"type":"number_category","value":"5"},{"type":"number_decimal_places","value":"2"},{"type":"number_format","value":"0.00%"}]` |
| Count / Units / Quantity | integer | `[{"type":"number_category","value":"1"},{"type":"number_decimal_places","value":"0"},{"type":"number_format","value":"#,##0"}]` |
| Fixed decimal (Price per unit, Ratio) | fixed | `[{"type":"number_category","value":"1"},{"type":"number_decimal_places","value":"2"},{"type":"number_format","value":"#,##0.00"}]` |
| Very large magnitudes (Trade Volume, Population) | scientific | `[{"type":"number_category","value":"7"},{"type":"number_decimal_places","value":"2"},{"type":"number_format","value":"0.00E+00"}]` |
| Date-like numeric (YearMonth, YYYYMMDD key) | integer, no thousands sep | `[{"type":"number_category","value":"1"},{"type":"number_decimal_places","value":"0"},{"type":"number_format","value":"0"}]` |

**Verified format.values shape (Strategy ONE 2026):** entries use `{type, value}` pairs, NOT `{category, formatString}` pairs. The Modeling Service rejects `{category: X}` payloads with `Unrecognized field: category`. Each format property is its own entry — `number_category`, `number_decimal_places`, `number_format` are independent. `number_category` values: 0=General, 1=Number, 2=Currency, 3=Date, 4=Time, 5=Percentage, 6=Fraction, 7=Scientific, 9=Accounting.

Assignment heuristic (apply **before** build, cache in the dictionary):

1. **Name-based first pass.** If metric name contains `Revenue|Sales|Cost|Profit|Amount|Price|Spend|Expense` → currency. If it contains `%|Percent|Rate|Margin|Growth|Share` → percent. If it contains `Count|Qty|Quantity|Units|Orders|Transactions` → integer. `Ratio|Index|Score` → fixed decimal.
2. **Datatype fallback.** Integer/bigint source column → integer. Decimal with scale ≥ 2 → currency (conservative) unless the metric is ID-flavored. Decimal with scale 0 → integer.
3. **Scientific only when justified.** Use for columns whose observed magnitudes exceed 10⁹ in the warehouse, not by default.

**Why:** a validation dossier in Library that shows `Revenue: 41735.50` for every row is non-consumable. Finance users reject it before touching the data. The legacy MSTR project carries formats on every metric (see `format.values` in `GET /api/model/metrics/{id}`); the auto-builder omits them.

**How to apply:** extend `build_mosaic.py` so every metric POST includes a `format.values` block derived from (name, datatype). Add a `--format-override` CLI flag for per-metric explicit formats when the heuristic picks wrong. When mirroring a legacy model, copy the legacy metric's `format.values` array verbatim — MSTR formats are JSON-portable across tenants.

## Combined impact

These two rules are the difference between "Mosaic model that technically works" and "Mosaic model I can hand to an SE for a customer demo." Every new model must pass both before `validate-model` is considered done. Update `reference_mosaic_build_validation.md` so the checklist explicitly fails a model that has:
- Any attribute with multiple forms whose `displays.reportDisplays[0].id == ID_FORM`
- Any metric with empty `format.values[]` or `category:"Generic"`
