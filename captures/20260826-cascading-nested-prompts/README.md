# N-level nested (cascading) prompts — verified live (2026-08-26)

Customer ask: cascading prompts in classic BI — pick a car maker, then only that
maker's models, then only that model's parts (each answer unlocks the next list).
This is the KB10434 prompt-in-prompt pattern. The operator hit a Workstation
error at step 2 ("The filter … contains prompts. Filtered element browsing is
not supported with a filter that contains prompts"); this session proved the
error is an **editor-preview limitation only** and verified the whole pattern
end-to-end over REST on the <tenant-b> env's MicroStrategy Tutorial project.

Durable lessons live in `memory/reference_strategy_legacy_semantic_admin.md`
("Classic prompts, N-level nested…") and two new rows in
`memory/reference_strategy_error_codes.md`. Customer-facing interactive
explainer artifact: "Cascading Prompts, Three Ways" (see session notes).

## What was built (all in Tutorial › Public Objects › Reports › <operator>)

3-level chain, Category → Subcategory → Item (retail stand-in for
maker → model → trim), each level = element prompt + filter wrapping it:

| Object | Name | ID |
|---|---|---|
| Prompt L1 | Cascade 1 - Category | `D06322279D924343BD2E40D546A8DF62` |
| Filter L1 | Cascade Filter - Category (prompted) | `CDA3EF28B525463981C07178CFC67E2E` |
| Prompt L2 | Cascade 2 - Subcategory (restricted by F1) | `0E06A21541FD46D4BE9C17E18E99D3D8` |
| Filter L2 | Cascade Filter - Subcategory (prompted) | `9F0A32D5CB2C4F2699A7ED95D1B167E2` |
| Prompt L3 | Cascade 3 - Item (restricted by F2) | `C79C11B488914F9DB25BFFABE68031CB` |
| Filter L3 | Cascade Filter - Item (prompted) — the report filter | `9F19563360BA448889CE08DFE24A4B6D` |
| Report | Cascading Prompts Demo (Category - Subcategory - Item) | `FB1F79D0E745CB34B9C82D951051A4B0` |
| WK-trick filter | WK Trick - Placeholder Filter (static → prompted swap, committed) | `C95EB723936444989D5A863241FF4ED3` |
| WK-trick prompt | WK Trick - Subcategory (restricted by placeholder) | `F922C8D405F449EB9505167A394550DD` |

Tutorial standard IDs used: Category `8D679D3711D3E4981000E787EC6DE8A4`,
Subcategory `8D679D4F11D3E4981000E787EC6DE8A4`, Item
`8D679D4211D3E4981000E787EC6DE8A4`, Revenue `4C05177011D3E877C000B3B2D86C964F`,
<operator> folder `A0C79F1CFF4A672C9684F199187A2A41`. The operator's own
Workstation-created filter that triggered the error: "Year Filter Prompted"
`2479E6FC856040168842913F112E6293` (element-list qualification backed by an
**embedded** prompt, `isEmbedded: true` — proof Workstation's filter editor can
save prompted filters).

## Runtime evidence (REST, one session)

`POST /api/v2/reports/{id}/instances` → status 2, then per round
`GET …/prompts` / `GET …/prompts/{key}/elements` / `PUT …/prompts/answers`:

| Round | Prompt open | Elements offered | Answered |
|---|---|---|---|
| 1 | Cascade 1 - Category | 4 (Books, Electronics, Movies, Music) | Electronics |
| 2 | Cascade 2 - Subcategory | **6 — Electronics subcats only** | Cameras |
| 3 | Cascade 3 - Item | **15 — cameras/camcorders only** | Hitachi DVD Camcorder |
| 4 | none left | report executed, 1 row | — |

Prompt list is progressive (round N lists N prompts, one open) — nested prompts
render as sequential steps in Web/Library.

## Second chain (same day): Year → Quarter → Month on the operator's own filter

Built on request, reusing the operator's Workstation-created **"Year Filter
Prompted"** (`2479E6FC…`, embedded prompt "Elements of Year") as level 1 —
completing their exact original attempt and proving **embedded-prompt filters
cascade the same as standalone ones**:

| Object | Name | ID |
|---|---|---|
| Filter L1 (existing, untouched) | Year Filter Prompted | `2479E6FC856040168842913F112E6293` |
| Prompt L2 | Elements of Quarter (cascading) — restricted by Year Filter Prompted | `F08C1B10CC79458AA94E8D9DE58285D1` |
| Filter L2 | Quarter Filter Prompted | `FCC08EA4B3444354A06A3C0AF1EBEBA7` |
| Prompt L3 | Elements of Month (cascading) — restricted by F2 | `6D3A680831194C74B96F33BAC3F33478` |
| Filter L3 | Month Filter Prompted — the report filter | `9EC06A0A227F437F97ACC7D5148FA185` |
| Report | Cascading Prompts Demo (Year - Quarter - Month) | `52F8FB50AB4C3A2E7937598E9D5B39F6` |

Runtime evidence: Year offered 2020–2023 → answered 2021 → Quarter offered
**2021 Q1–Q4 only** → answered 2021 Q2 → Month offered **Apr/May/Jun 2021 only**
→ report ran (1 row). Schema time attributes: Year `8D679D5111D3E4981000E787EC6DE8A4`,
Quarter `8D679D4A11D3E4981000E787EC6DE8A4`, Month `8D679D4411D3E4981000E787EC6DE8A4`
(and Month of Year `8D679D45…` is the generic Jan–Dec one — not for this chain).

Caveat noted: the operator's embedded "Elements of Year" prompt has
`required: false` (Workstation default) — a user can skip Year and get all
quarters. Fix in Workstation by editing the filter's embedded prompt settings
(no filtered-elements preview involved, so no error).

## Gotchas hit and fixed this run

1. `POST /api/model/reports` rejected the OpenAPI-documented
   `{"standaloneFilter": …}` report-filter shape (`8004c90a`) — use
   `predicate_filter_qualification` + `isIndependent: 0` (shape real reports carry).
2. `PUT /api/model/filters/{id}` is full-replace — resend `information` or
   `8004c901`. With it, the static→prompted swap commits and the referencing
   prompt's `question.filter` survives (= the pure-Workstation authoring trick).
3. Report create is instance-based (no changeset): grab the `X-MSTR-MS-Instance`
   response header, persist via `instances/saveAs`.
4. **Managed-attribute search trap** (time chain): `/api/searches/results?type=12`
   returned managed/template attributes named "Quarter"/"Month" with EMPTY
   ancestors; prompts created against them committed fine, but report create
   failed `8004da0c` "Managed object cannot be added to normal report template."
   Resolve real schema attributes via `GET /api/model/systemHierarchy` or an
   existing report's `dataTemplate.units`. Repaired in place: `PUT
   /api/model/prompts/{id}` (full-replace: echo information/title/instruction/
   question/restriction, swap `question.attribute`) — object IDs survive, so the
   wrapping filters needed no touch.

## Files (local-only per .gitignore)

- `cascade_build.py` — one-session build + runtime-verify script (env-driven creds)
- `cascade_ids.json` — created object IDs
- `cascade_evidence.json` — full request/response evidence incl. element lists
- `swap_result.json` — placeholder-swap after-state (filter + prompt GETs)
