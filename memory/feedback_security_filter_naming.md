---
name: Security filter names must describe the qualification
description: Every Mosaic / classic security filter created by automation must have a name that describes WHAT the filter restricts. Generic names like "SF <user>" or "Row-level filter" are not acceptable. Use the qualification itself as the name: "{Attribute} {operator} {value}" (e.g. "Region = EMEA", "Country IN (US, CA)", "Category_ID <= 5").
type: feedback
---

## Rule

When creating a security filter via `POST /api/model/dataModels/{id}/securityFilters` (Mosaic) or `/api/model/securityFilters` (classic), the `information.name` must describe the qualification itself, not the user it's assigned to or the date it was created.

**Why:** SFs are reused across users, groups, and audits. A name keyed to "who" (e.g., "SF <username> access") goes stale the moment the membership changes and hides the security rule from reviewers. Names keyed to "what" ("Region = EMEA") remain accurate for the life of the qualification.

**How to apply:**
- Single-value equals qualification → `"{Attribute} = {value}"`.
- In-list → `"{Attribute} IN ({v1}, {v2})"`.
- Range / inequality → `"{Attribute} >= {value}"`, `"{Attribute} BETWEEN {a} AND {b}"`.
- Compound → join with ` AND ` / ` OR ` at the top level: `"Region = EMEA AND Segment = Enterprise"`.
- If the qualification references a metric ranking → `"{Metric} top {N}"`.
- Prefer the human-readable display value, not the element ID (e.g., "Region = EMEA", not "Region.REGION_ID = hEMEA"). The element-ID / form binding is an implementation detail of the REST payload, not a consumer-facing name.
- Keep the `description` field for extra context (e.g., "Row-level security — restricts to a single tenant for scoped access"), not the qualification itself.

## When not applied

If a filter is genuinely generic (e.g., a named operator role with multiple qualifications spliced together for a specific business reason), use a short business-domain name AND include the qualification summary in the description. Never use a purely administrative placeholder like `SF_NEW_1`.

## Automation rule

`build_mosaic.py add-security-filter` takes `NAME=ATTR_ID[:FORM_ID]=VALUE|USER,...`. Any automation that wraps this must derive a qualification-descriptive `NAME` from the attribute name and value, not accept an arbitrary placeholder. Similarly, scripts that create SFs directly via REST must assemble the name from the qualification fields before POST.
