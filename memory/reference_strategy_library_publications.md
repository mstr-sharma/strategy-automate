---
name: Strategy Library publications (who has what, and replaying it)
description: How to list which dashboards/documents/reports/agents are published to which users and user groups (per-object GET /api/library/{id}), how to republish them in another project (POST /api/library, additive + idempotent, groups stay groups), what project duplication does and does not carry, mstrio-py version traps, and the helper script.
type: reference
---
## The one fact that matters

There is **no** endpoint that answers "what is published to user/group X" — no admin/bulk Library listing, no impersonation (`GET /api/library?userId=` / `?user=` / `?ownerId=` are ignored and return the caller's own Library; `GET /api/users/{id}/library` is 404). The publication list lives **on each object**:

```
GET /api/library/{objectId}          header X-MSTR-ProjectID: <project>   (required: 400 ERR006 without it)
-> 200 {"id": "<objectId>", "recipients": [{"id","name","description","subtype"}]}
```

- `subtype` 8704 = user, 8705 = user group. Groups are returned **as the group** (not expanded to members); recipients are direct grants only.
- Never-published object -> `200` with `"recipients": []` (not 404), so a scan over every object needs no special casing.
- Live responses carry only `id` + `recipients`; the spec's `PublishResponse` fields (owner, author, publish times, managedCopyId, viewId) are not populated.
- Works for type 55 (dashboards/documents, subtype 14081; agents 14084/14087/14091) and type 3 reports (the spec says "Document ID or Report ID"; GET has no `type` param).
- The `id` in the caller's own `GET /api/library` items is a **shortcut** id; use `item.target.id`. Passing the shortcut id -> `500` "not an object of the expected type".
- Wrong project header on an existing id -> `404 ERR004`; unknown id -> `500 ERR001` (or 404). Check the ERR code, not just the HTTP status.
- Items a user added to their own Library ("Add to Library") appear as ordinary 8704 recipients.
- The `description` of a user recipient is free text (seen holding credential-like strings) — drop it from exports.
- Invert the per-object lists to get the per-user / per-group view. Run the scan as an administrator.
- Cost: ~75 ms per object, one call each (1,186 objects ~= 75 s sequential). Keep it sequential or lightly parallel; a tenant returned 502s for minutes after a 400-call burst (cause unconfirmed).

Enumerate objects with metadata search (`POST`+`GET /api/metadataSearches/results`, `type=55` / `type=3`, `domain=2` — includes hidden objects; paging total is `totalItems` on the POST) or quick search (`GET /api/searches/results?type=55`, misses hidden objects). Content groups are a **separate** path into Library (`/api/contentGroups`, `/api/contentGroups/{id}/contents`) and are not in the recipient list.

## Republishing (verified live 2026-09-28, self + empty-group test, cleaned up)

```
POST /api/library      header X-MSTR-ProjectID: <target project>
{"id": "<objectId>", "recipients": [{"id": "<userOrGroupId>"}, ...], "type": "report_definition"?}
-> 204, no body
```

- **Additive**: posting a new recipient keeps the existing ones.
- **Idempotent**: re-posting an existing recipient is `204` with no duplicate.
- **Group ids stay groups** (stored as one 8705 recipient, so future members get it too).
- `recipients` as bare id strings is also accepted (mstrio sends strings; the spec documents `[{id}]`).
- `type` is `document_definition` (default) or `report_definition` — a string enum, not 55/3.
- Bulk / cross-project: `POST /api/v2/library` (no project header) `{"publishList":[{"projectId", "objects":[{"id","type"(required),"recipients":[{id}]}]}]}` -> 204 or 207 per-object status. Verified with a group recipient.
- Delta edit: `PATCH /api/library/{id}` `{"operationList":[{"op":"add|remove","path":"/recipients","value":...}]}` exists (needs PublishDossier privilege); `value` shape is ambiguous in the spec — not exercised.
- Remove one recipient (user **or group**): `DELETE /api/library/{id}/recipients/{recipientId}` + project header -> 204.
- **Never** `DELETE /api/library/{id}` (or mstrio `Document.unpublish()` with no args): unpublishes for **every** recipient.
- Hidden `POST /api/dossierPersonalView` (`publishedToUsers` string list) defaults to **Everyone** when the list is omitted — avoid for replays.

## Project duplication and Library publications

- Duplicated projects keep **object GUIDs**; users/groups are configuration objects shared by every project in the same metadata, so the same object + recipient ids replay 1:1 — which also means the project header is the only thing separating source from copy on every Library call.
- Whether publications come across depends on how the copy was made. A same-environment REST/Workstation duplication with `schemaObjectsOnly=false` and profile folders included carried the recipients **and** the per-user Library shortcuts (same shortcut ids and `sharedTime`). Schema-only duplicates have no dashboards; package/object-migration and cross-environment copies start with none. `GET /api/projectDuplications` shows the settings a copy was made with. mstrio `Project.duplicate()` defaults to `schema_objects_only=True`.
- Cross-environment: object GUIDs are kept, but users/groups keep their ids only if they were copied, not matched (`matchUsersByLogin`, `typesMatchByName` in the import settings) — map by login otherwise.
- **Always diff the target first** (same GET with the target header) and post only missing recipients.
- Objects created in the source after the copy was made are simply absent in the target (`GET /api/objects/{id}?type=` -> 404 ERR004).

## Storage (why not to scan shortcuts)

Per-user Library entries are type 18 / subtype 4609 shortcuts in `<project>/Profiles/<user profile>/My Dashboards`, created lazily (an Everyone publication had shortcuts for ~10 of 100+ members) and sometimes orphaned (old shortcuts to objects whose recipient list is empty). Quick search on type 18 is incomplete, `usesObjectId` does not link shortcut -> target, and non-admins get 403 on Profiles. Use the per-object recipient list as the source of truth. Favorites live in `GET /api/library/shortcutGroups` (`FAVORITES.itemKeys` = `<objectId>_<projectId>`).

Republishing restores **access** only — not favorites, bookmarks, last-viewed, personal views or read state (those hang off the per-user shortcut).

## mstrio-py traps

- `< 11.5.7.101`: `Document.publish(UserGroup)` expands to the group's **current members**; `.recipients` goes through `list_users()` and drops groups.
- `>= 11.5.7.101`: groups are published as groups (`LibraryMixin.publish`), but `.recipients` returns groups as `User` objects (only `.subtype == 8705` tells), and `publish(recipients=[ids])` silently drops ids it cannot resolve (403 for non-admins, deleted users).
- `.recipients` / `publish()` use the connection's **selected** project — with identical ids in source and copy they silently hit the wrong one. Use `conn.get/post(endpoint=..., headers={"X-MSTR-ProjectID": pid})`.
- `list_agents` exists from 11.5.10.101 (earlier: `mstrio.project_objects.bots.list_bots`). `Report` has no publish method. The `Library` class only reflects the authenticated user's own Library.
- Current mstrio-py (11.6.x) needs Python >= 3.10. At DEBUG log level mstrio logs request bodies including the login password.

## Other gotchas seen on the way

- `GET /api/v2/library` returns an **object** `{documentContents, contentGroups, reportContents, aiBotContents}`, not the array the spec documents.
- Log out with `POST /api/auth/logout`; `DELETE` returns 404 and leaks the session.

## Helper

`skills/build-mosaic-model/scripts/strategy_library_publications.py` (requests only; env `MSTR_BASE`/`MSTR_USER`/`MSTR_PASSWORD`/`MSTR_LOGIN_MODE`):

```bash
python3 skills/build-mosaic-model/scripts/strategy_library_publications.py export --project "<source>" --out mapping.csv --by-recipient
python3 skills/build-mosaic-model/scripts/strategy_library_publications.py replicate --mapping mapping.csv --target-project "<copy>"          # dry run
python3 skills/build-mosaic-model/scripts/strategy_library_publications.py replicate --mapping mapping.csv --target-project "<copy>" --apply
```

`export` covers dashboards, documents, agents and reports (`--types` to narrow) and writes one CSV row per (object, recipient) plus JSON and an optional per-recipient rollup. `replicate` is a dry run by default, checks each object and user/group exists in the target, adds only missing recipients, keeps groups as groups, verifies by read-back, never unpublishes (`--match-by-name` for ids that differ). `strategy_library_publications_mstrio.py` is the compact mstrio-py equivalent (same CSV).

Verified 2026-09-28 on two Strategy ONE Cloud tenants (11.6.06, 11.6.09), including a real same-environment project duplicate.
