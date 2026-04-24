---
name: Mosaic data-model description is capped (≈250 chars) — keep PATCH bodies short
description: PATCH `/api/model/dataModels/{id}` with `information.description` longer than ~250 characters is rejected 400 `8004cc10` "Object Description ... " on Strategy ONE Cloud tenants. Rephrase to fit under the cap; detail belongs in attached documentation, not the description field.
type: feedback
---

## Observation

Observed on a Strategy ONE Cloud tenant (captured run):
- PATCH attempt with a ~700-char description → `400 8004cc10 "Object Description <full text> ..."` (the server echoes the rejected text; the error text itself is the truncation).
- PATCH attempt with a ~480-char description → same error.
- PATCH attempt with a ~205-char description → `200 ok`, commit 201.

Empirically, ~250 chars is the safe ceiling for Mosaic data-model descriptions on this tenant family. The iServer may be enforcing the classic MicroStrategy 255-char `ObjectInfo.Description` limit. Any automation that derives a description from warehouse metadata must truncate — or, better, summarize — before the PATCH.

## How to apply

- Keep the description to one or two sentences, under ~250 chars. Prioritize: purpose, primary source DBs, grain, and any row-level security note.
- Put fuller modeling notes (aggregation rules, grain per table, ratio-safety caveats) in an external README or a `captures/<run>/model-design.md`, not the Mosaic description.
- If the model's automation wants to attach the full dictionary / ERD / validation artifact, store it in the repo or the skill's `examples/` directory and link it from the model's README rather than trying to cram it into the description.
- Do NOT retry blindly on 8004cc10 — it's a length-class error, not transient. Truncate and retry once.

## Related

- Consumer-grade naming memory (`feedback_consumer_grade_naming.md`) already covers the "what should a description communicate" side. This memory covers the "how long can it be" side.
- Attribute and metric descriptions on the same tenant appear to have a similar cap, though measurement is less rigorous. Err on the side of one-sentence descriptions when PATCHing in bulk.
