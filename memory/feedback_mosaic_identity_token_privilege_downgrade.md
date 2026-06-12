---
name: Identity token can DOWNGRADE Mosaic write privileges (403 8004cb09)
description: Verified 2026-06-09 on a Strategy ONE Cloud tenant — when "Use Mosaic Studio" (priv 316) is granted at PROJECT level only (isUserLevelAllowed=false), sending X-MSTR-IdentityToken on a Mosaic Modeling write makes the server evaluate config/user-level privileges and 403s. Drop the identity token; standard auth token + X-MSTR-ProjectID carries the project-level grant.
type: feedback
tags: [mosaic, auth, identity-token, privilege, error-code, 8004cb09]
---

**Rule.** For Mosaic data-model Modeling writes (e.g. `PATCH /api/model/dataModels/{id}/factMetrics/{mid}`), do NOT assume `X-MSTR-IdentityToken` is required. If the user's Mosaic privilege is granted at the **project** level but not the **user/configuration** level, the identity-token passthrough makes the server evaluate the privilege at config level and returns:

```
HTTP 403 8004cb09: "You do not have Use Mosaic Studio privilege(s) to perform the task."
```

The SAME changeset + PATCH **succeeds** when you log in WITHOUT the identity token and rely on the standard `X-MSTR-AuthToken` + `X-MSTR-ProjectID` header — that path evaluates the project-scoped privilege, which is granted.

**How to confirm the diagnosis (not a real privilege gap):**
`GET /api/sessions/privileges` → find the privilege by name. If you see
`{"id":"316","name":"Use Mosaic Studio","isUserLevelAllowed":false,"projects":[{"id":"<proj>","isAllowed":true}]}`
then the grant is project-only and the identity token is the culprit, not a missing privilege.

**How to apply.**
- Mosaic model writes on this tenant: `m.login(identity=False)` then set `m.s.headers["X-MSTR-ProjectID"]=<projectId>`, open changeset, PATCH/POST, commit.
- This DIRECTLY CONTRADICTS the blanket "X-MSTR-IdentityToken mandatory for Modeling writes" note in [[feedback_mosaic_gotchas]]. Reality is tenant/grant-dependent: identity token is needed on some tenants, harmful on others. Decision rule: **try standard-token + project header first; only add the identity token if you get a "wrong project / no changeset context" style error, never to fix an 8004cb09 privilege 403.**
- Reads (`GET .../dataModels/...`) already must DROP the identity token (false-projectId 8004c768) — see [[feedback_mosaic_gotchas]]. So on this tenant family, BOTH Mosaic reads and writes work best with identity token OFF.

**Observed context.** A Mosaic pharma model in the tenant's shared project (IDs in the operator-local capture for that run). `open_cs` (POST /api/model/changesets) succeeded with identity token on, but the object PATCH inside it 403'd — opening a changeset does not require the privilege; writing the object does.

**2026-06-11 addendum.** `GET /api/sessions/privileges` now shows priv 316 granted at USER level too (`isUserLevelAllowed: true`) — the grant was upgraded sometime after 2026-06-09, so the downgrade trigger may no longer fire on this tenant. The decision rule stands unchanged: identity-token-OFF ran an entire 4-table build (model, tables, attributes, metrics, relationships, validate) clean on 2026-06-11, so standard-token + `X-MSTR-ProjectID` remains the safe default for Mosaic work here; re-test the identity path only when a "wrong project / no changeset context" error forces it.
