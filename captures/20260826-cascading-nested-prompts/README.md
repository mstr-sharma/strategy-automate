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

## Day 2 (2026-08-27): operator dashboards + real-data asset rebuild

Operator hand-built two dashboards in the same folder (each = 1 chapter / 1 grid
viz on the corresponding prompted demo report, no filter-panel filters):
"Cascading Prompt - Year, Quarter, Month" `0AAC02C345417364A65EF6898F87FA1F` and
"Cascading Prompt - Category, Subcategory, Item" `942701A89C429C0996DF17BEA7AB1ECD`.
Session verified + captured against them:

- **Dashboards over prompted reports prompt at document-instance creation**
  (status 2); the nested cascade answers through the DOCUMENT prompt endpoints
  (`GET/PUT /api/documents/{id}/instances/{mid}/prompts[...]`) exactly like the
  report flow — Year offered 4 → Quarter 4 (chosen year) → Month 3, and
  Category 4 → Subcategory 6 → Item 15, on dashboard instances.
- **PDF export of a dashboard instance**: `POST /api/documents/{id}/instances/{mid}/pdf`
  — this build's `orientation` enum is `NONE|AUTO` (`LANDSCAPE` → ERR006);
  response is JSON `{data: <base64>}`. Rendered PNGs via pymupdf.
- **Full-cascade data extract**: answering every prompt with ALL elements returns
  the whole fact slice — 36 month rows (2020–2022), total revenue $35,023,708.15;
  2023 has calendar elements but no fact rows. 2021 Q2 = Apr $827,244.30 /
  May $892,637.30 / Jun $964,882.00 (matches dashboard render).
- **Library is not frame-blocked** on this env (`/app` serves no X-Frame-Options
  and CSP has no frame-ancestors) — plain-iframe embedding works when the viewer
  is signed in; artifact host CSP still forbids third-party frames, so the asset
  embeds REST-rendered PNGs + links, with a local `cascading-prompts-live-embed.html`
  companion for true iframes. Later on 2026-08-27 that companion grew into the full
  **live-edition educational page** at `~/Desktop/cascading-prompts-embed/` (index.html +
  start.sh → http://localhost:8811): annotated wizard replay + build walkthrough with the
  Workstation gap/workaround inline + exactly one live iframe per example (YQM prompted
  report, CSI dashboard, hierarchy dashboard; YQM dashboard link-only to avoid duplication).
  Final form (same day): **customer-facing wording** (no local-hosting or operator
  references; generic "embedding Library in your pages" guidance) packaged as
  **cascading-prompts.war** (webapp/ + build-war.sh + DEPLOY.md in the same Desktop
  folder) for drop-in Tomcat deployment — same-Tomcat-as-Library placement makes the
  session first-party (Safari-safe). Recipe re-proven same day by `api_proof.py`:
  fresh temp 2-level chain created via the documented calls, cascade verified at
  runtime (Movies → 6 Movies subcats), then all temp objects deleted (204s).
  DEPLOYED 2026-08-27: operator dropped the WAR into the env's Tomcat webapps
  next to MicroStrategyLibrary; auto-deploy unpacked it — live at
  `https://<env-base>/cascading-prompts/` (verified HTTP 200; iframes now
  SAME-ORIGIN with Library → first-party session, works in every browser
  including Safari, independent of the SameSite setting).
  Then (per user, for easy showcasing) the deployed build got **hardcoded demo
  auto-login**: a small script POSTs the shared demo creds to
  `/MicroStrategyLibrary/api/auth/login` on load; being same-origin, that sets a
  first-party session so all three iframes render with NO login prompt (status
  pill flips to "Connected as demo user"; iframes held on about:blank until auth
  resolves; URLs relativized so the page is origin-portable). The credentialed
  index.html is NOT committed here (repo no-creds rule) — creds live only in the
  Desktop webapp/deployed WAR. Verified: on localhost the login no-ops → warn
  fallback → frames still load (logic sound); the 204/green path is the deployed
  same-origin behavior. **Redeploy = rebuild WAR + re-upload (overwrite) → Tomcat
  auto-redeploys.**
- Spec-observed (not exercised): this env family documents dashboard import
  (`POST /api/dashboards` from .mstr), deprecated create-from-report
  (`POST /api/dashboards/json`), and `POST /api/dossiers/instances`
  (DashboardCreationInfo) + `POST /api/documents/{id}/instances/{mid}/saveAs` —
  a candidate in-memory→persist authoring path if programmatic dashboard
  creation is ever needed.

Later on day 2 the operator added a third dashboard: **"Cascading Prompt -
Product Hierarchy Prompt"** `B24CEE0BF04483AF3098548E682A2E18` on **"Product
Hierarchy Prompted Report"** `C6F2BADA634DB0FE36882E880C33D8DD`, whose filter is
a `predicate_prompt_qualification` wrapping **"Product Hierarchy Prompt"**
`E692DE28B8A245EBB5B8DC72AD65D146` (`prompt_expression`, `expressionType:
hierarchy`, question.predefinedObjects = Products user hierarchy `B793B568…`,
optional). Verified answers + facts:

- Runtime prompt type is `EXPRESSION`; the **answer body uses the runtime
  `{operator, operands}` expression grammar**, NOT the Modeling predicate tree:
  `{"prompts":[{"key":k,"type":"EXPRESSION","answers":{"expression":{"operator":"In","operands":[{"type":"attribute","id":<Category>},{"type":"elements","elements":[{"id":"h2;<Category>","name":"Electronics"}]}]}}}]}`
  → 204. (Modeling-style `predicate_element_list` under `answers.expression` →
  ERR006.) Sending the key with NO answers closes an optional prompt (204) and
  renders unfiltered (21-page grid vs 6 pages qualified to Electronics).
- **Local-iframe blocker diagnosed**: `/api/auth/login` Set-Cookie for
  `iSession`/`JSESSIONID` carries **no SameSite and no Secure** → browsers
  default to Lax and never send the session into a cross-origin iframe
  (file:// parents are always cross-origin) → login screen/loop in frames even
  though the app itself has no X-Frame-Options/frame-ancestors. Fix: Library
  Admin → Security Settings → SameSite=None (+ enable embedding / allowed
  origins), host the embed page on https, or use the Embedding SDK / same-site
  hosting (mandatory for Safari & blocked-third-party-cookie browsers).

Asset v2 ("real-env edition") replaced all simulated content with captured data:
live YQM wizard replay, both dashboard renders inline (data URIs), targeted-filter
replica driven by the 36 real rows. Files: `render2.py`, `inspect_render.py`,
`real_data.json`, `dash_info.json`, `dash_*.pdf/png`.

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
