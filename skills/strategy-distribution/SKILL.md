---
name: strategy-distribution
description: Automate Strategy (formerly MicroStrategy) Distribution Services over REST — subscriptions (list, inspect, create email, file, cloud, cache and History List deliveries, send now, run status, prompts, bursting, owner, pause, delete), schedules, events and event triggers, transmitters, devices, contacts, contact groups, dynamic recipient lists and the History List, plus refreshing a Mosaic model on a schedule (a data_model subscription). Use it for "subscription", "schedule", "email a dashboard", "send now", "history list", "contacts", "event trigger", "refresh a model on a schedule", "who receives this report", "why didn't the email arrive" or "unsubscribe". Every call goes through strategy_api.py, validated against the tenant's own OpenAPI spec; sends wait for an explicit recipient check.
---

# Strategy distribution

Subscriptions, schedules, events, recipients and the History List — the delivery side of Strategy. Every call goes through `strategy_api.py`; sign-in, `ops` / `describe` / `call`, dry runs and `--yes` are in `skills/strategy-platform/SKILL.md`. **A send lands in real inboxes and folders** — read the Safety rules before any `--yes` that sends.

## Scope

Owns the spec tags Subscriptions (with dynamic recipient lists, Excel templates, subscription images, dependent subscriptions), Schedules, Events, Transmitters, Devices, Contacts, Contact Groups and History List: `$API ops --tag strategy-distribution`.

Route elsewhere:
- Mosaic model build, publish, refresh **now**, table ids → `skills/build-mosaic-model/SKILL.md` (`build_mosaic.py publish` / `refresh`). This skill only puts a refresh on a schedule (workflow 9).
- Finding, running and exporting the content a subscription delivers, answering its prompts, cube publish → `skills/strategy-content/SKILL.md`.
- Users, user groups, user addresses (`createAddress` is User Management), send-now and schedule privileges → `strategy-admin`.
- Delivery jobs, caches, telemetry → `strategy-ops`. Subscriptions, schedules and events across environments → `strategy-migration`.

## How to work

1. Sign in once (`strategy_auth.py login`), export `MSTR_PROJECT_ID`, and from the repo root `API="python3 skills/strategy-platform/scripts/strategy_api.py"`.
2. `$API describe <operationId>` before every call. The body skeleton lists up to 40 values of an enum.
3. Reads first. GETs run directly; POST-based reads (`…/query`, `…/results`) change nothing but still need `--yes`.
4. Every write: run it without `--yes`, check the printed request (recipients, schedule, content, delivery target), then add `--yes`.
5. Read back after each write — the server rewrites some fields on save (workflow 3).
6. Remove the test subscriptions, schedules, events, contacts and History List messages you made; report anything left behind with its id.

`call` signs in and out per run unless the session is a cached browser one (`strategy_auth.py login --method sso`) or you pass `--reuse-session` (`MSTR_REUSE_SESSION=1`; end it with `strategy_auth.py logout`); otherwise an instance id made by one call is gone in the next. Prompted-content sends need one session — strategy-content, "One session".

## Workflows

### 1. List and inspect subscriptions

```bash
$API call getSubscriptions -p limit=100 -p lastRun=true      # this project; other users' need schedule monitor/admin privileges
$API call getSubscriptionsCrossProjects -p limit=100 --yes   # POST read across every project you can see
$API call getSubscriptionById -p id=<subId>
$API call getSubscriptionStatusById -p id=<subId>            # last run status
$API call getPromptsSubscription -p subscriptionId=<subId>   # stored prompt answers
$API call getDependentSubscriptions -p objectId=<id> -p type=report   # type: user|dashboard|report|schedule|event|contact
```

### 2. Gather the ingredients

```bash
$API call listSchedules_1 -p limit=200                       # v1 listSchedules has no paging
$API call listSchedulesByContents --body '{"contents": [{"id": "<contentId>", "type": "dossier"}]}' --yes
$API call getRecipientsSharedList -p deliveryType=EMAIL -p contactNamePattern=<text> --body '{"contents": [{"id": "<contentId>", "type": "report"}]}' --yes
$API call listPersonalAddresses -p deliveryType=EMAIL         # the caller's own addresses
$API call listAddresses -p userId=<userId>                    # a user's addresses; the default is flagged
$API call listTransmitters
$API call getDevices_1 -p deviceType=email
```

### 3. Create an email subscription

`sub.json`, abbreviated from `describe createSubscription` (keep body files outside the repo):

```json
{"name": "<name>", "sendNow": false,
 "schedules": [{"id": "<scheduleId>"}],
 "contents": [{"id": "<contentId>", "type": "dossier", "personalization": {"formatType": "PDF"}}],
 "recipients": [{"id": "<userId>", "type": "user", "includeType": "TO"}],
 "delivery": {"mode": "EMAIL", "email": {"subject": "<subject>", "message": "<text>", "sendContentAs": "data"}}}
```

```bash
$API call createSubscription --body @sub.json         # dry run: check recipients, schedule, content
$API call createSubscription --body @sub.json --yes   # 201 → id; then getSubscriptionById
```

- `delivery.mode`: `EMAIL HISTORY_LIST CACHE FTP FILE MOBILE ONEDRIVE SHAREPOINT S3 GOOGLEDRIVE GCS`, each with its own block (`email`, `historyList`, `cache`, `ftp`, `file`, `mobile`, `onedrive`, `sharepoint`, `s3`, `googledrive`, `gcs`).
- `contents[].type`: `report document cube data_model dossier` (a dashboard is `dossier`). `recipients[].type`: `user user_group contact contact_group personal_address dynamic_recipient_list all_consumers`; `includeType`: `TO CC BCC`.
- `personalization.formatType`: `PLAIN_TEXT EXCEL HTML PDF STREAMING SWF_MHT SWF_HTML CSV VIEW INTERACTIVE EDITABLE EXPORT_FLASH PHONE TABLET JSON MSTR IMAGE`; `email.sendContentAs`: `data data_and_history_list data_and_link_and_history_list link_and_history_list library_snapshot none`.
- `sendNow: true` sends during the create and needs the send-now privilege — keep it `false` and send in workflow 4.
- Read back: a `user` recipient sent with `addressId` returns as `personal_address`; `formatMode` / `viewMode` `DEFAULT` return as `CURRENT_PAGE` / `BOTH`.

### 4. Send now and check the result

```bash
$API call sendSubscription -p id=<subId> --yes                                 # 202 — a real send
$API call getSubscriptionStatusById -p id=<subId>
$API call getHistoryList_1 -p targetInfo.objectId=<contentId> -p limit=20     # HISTORY_LIST deliveries
```

Prompted content: answer the prompts on a report or document instance (strategy-content workflows 4–5), then put `"prompt": {"enabled": true, "instanceId": "<instanceId>"}` in the content's `personalization` at create, or send with `--body '{"contentId": "<contentId>", "instanceId": "<instanceId>"}'` (`sendSubscription_1` takes a `contents` list). For an existing subscription, `createInstance_1 -p subscriptionId=<subId> -p contentId=<contentId> --yes` returns the instance to answer. Instance, answers and create/send must share one session.

### 5. Pause, edit, re-own, remove

```bash
$API call patchSubscription -p id=<subId> --body '{"softDisabled": true}' --yes     # pause; or {"name": "<new name>"}
$API call updateSubscription -p id=<subId> --body @full.json --yes                 # full replace: edit the GET body
$API call changeSubscriptionOwner -p id=<subId> --body '{"id": "<userId>"}' --yes
$API call batchChangeSubscriptionOwner --body '{"subscriptionIds": ["<subId>"], "owner": {"id": "<userId>"}}' --yes
$API call removeSubscription -p id=<subId> --yes                                   # only after explicit confirmation
```

### 6. Schedules and events

```bash
$API call listEvents
$API call createEvent --body '{"name": "<event>"}' --yes
$API call createSchedule --body @schedule.json --yes
$API call getDependentSubscriptions -p objectId=<eventId> -p type=event      # what a trigger will run
$API call triggerEvent -p id=<eventId> --yes                                 # 202 — this is a send
```

`schedule.json` (daily at 07:00; an event schedule uses `"scheduleType": "event_based", "event": {"eventId": "<eventId>"}` instead of `time`):

```json
{"name": "<name>", "scheduleType": "time_based", "startDate": "2026-10-06",
 "time": {"recurrencePattern": "daily", "execution": {"executionPattern": "once", "executionTime": "07:00:00"},
          "daily": {"dailyPattern": "day", "repeatInterval": 1}}}
```

Dates are `yyyy-MM-dd`, times `HH:mm:ss`; `timezone` defaults to the server's; `executionPattern: repeat` takes `startTime`, `stopTime` and `repeatInterval` (minutes).

### 7. Contacts, contact groups, dynamic lists, bursting

```bash
$API call searchContacts -p name=<text> -p limit=50 --yes        # POST read; listContacts pages all of them
$API call createContact --body @contact.json --yes
$API call createContactGroup --body '{"name": "<group>", "linkedUser": {"id": "<userId>"}, "members": [{"id": "<contactId>", "name": "<contact>", "type": "contact"}]}' --yes
$API call listDynamicRecipientLists
$API call createDynamicRecipientList --body @drl.json --yes
$API call listBurstingAttributes -p contentId=<reportId> -p contentType=report
```

- `contact.json`: `{"name", "linkedUser": {"id"}, "contactAddresses": [{"name", "physicalAddress", "deliveryType": "email", "deviceId", "deviceName"}]}`, `deviceId` from `getDevices_1`. Content sent to a contact runs under its linked user's security; `delivery.contactSecurity` applies that per contact-group member.
- `drl.json`: `{"name", "sourceReportId", "physicalAddress", "linkedUser", "device"}`, the last three each `{"attributeId", "attributeFormId"}` on the source report. Use the list as recipient `{"id": "<listId>", "type": "dynamic_recipient_list"}`.
- Bursting: `personalization.bursting: {"slicingAttributes": ["<attrId>"], "addressAttributeId": "<attrId>", "deviceId": "<deviceId>", "formId": "<formId>"}`.

### 8. History List

```bash
$API call getHistoryList_1 -p limit=50 -p readStatus=false        # scope=all_users needs admin rights
$API call getHistoryListMessage -p messageId=<msgId> -p objectType=document_definition   # report_definition for reports
$API call sendToHistoryList --body '{"id": "<objectId>", "type": "document_definition"}' --yes
$API call bulkSendToHistoryList --body '{"requests": [{"projectId": "<projectId>", "objects": [{"id": "<id>", "type": "report_definition"}]}]}' --yes
$API call removeFromHistoryList -p messageId=<msgId> --yes        # confirm first
```

### 9. Refresh a Mosaic model on a schedule

Official workflow since Strategy August 2025: a subscription whose content is the model. Confirm the target is a Mosaic model (`$API call getObject -p id=<modelId> -p type=3` → subtype 779 + extType 448) and read its table ids with `$API call "GET /api/model/dataModels/{dataModelId}/tables" -p dataModelId=<modelId>`.

```json
{"name": "<model> nightly refresh", "sendNow": false,
 "schedules": [{"id": "<scheduleId>"}],
 "contents": [{"id": "<modelId>", "type": "data_model",
               "refreshCondition": {"tables": [{"id": "<tableId>", "refreshPolicy": "upsert"}]}}],
 "delivery": {"mode": "HISTORY_LIST"}}
```

- `refreshPolicy` per table: `add delete update upsert replace ignore`. Without `tables`, `refreshCondition.datasetRefreshPolicy` is required and covers every table.
- Narrow a refresh with `refreshCondition.filters: [{"type": "refresh", "qualification": {"tree": {"type": "predicate_form_qualification", …}}}]` — attribute-form qualifications only (Modeling filter grammar).
- Prove a scheduled run with `getSubscriptionStatusById`, its History List message and a scoped MCP / Trino query on fresh rows — never the 201. (`publishStatus` needs the instance id of a manual publish, which a scheduled run does not hand out.) A refresh now is `build_mosaic.py publish` / `refresh` (`memory/reference_mosaic_publish_path.md`).
- Classic (776) or data-import cubes on a schedule: no documented body. The subscriptions note routes them to a `CACHE`-mode subscription — read a UI-made one with `getSubscriptionById` and clone it.

## Safety rules

- **Sends reach real people.** `sendSubscription`, `sendSubscription_1`, `triggerEvent`, a create or update with `sendNow: true`, and a schedule that fires soon all deliver. Before any of them: expand the recipients — user groups with `getUserGroupMembers_1 -p id=<G> -p flatMembers=true -p limit=-1`, contact groups with `getContactGroupById -p id=<id>`, dynamic lists with `getDynamicRecipientListById -p id=<id>` plus a run of its `sourceReportId` (strategy-content workflow 4) — then show the list with the content and delivery target, and get an explicit yes for that send.
- First runs go to `HISTORY_LIST` or to one test recipient the user named (themselves or a test contact) — never a group.
- `triggerEvent` runs every subscription on every schedule bound to the event; list them first (workflow 6).
- Never delete subscriptions, schedules, events, contacts, contact groups, dynamic lists, transmitters, devices or History List messages without explicit confirmation of the listed ids. Schedules, events, transmitters and devices are shared: run `getDependentSubscriptions` before removing one. `removeFromHistoryList -p removeOthersMessage=true` deletes other users' messages.
- Deliveries are data exports: confirm FILE / FTP / S3 / SharePoint / OneDrive / Google targets and zip settings; zip passwords and body files stay out of the repo, shell history and logs.
- Prompts, filters and bursting must be explicit: record the answers, the slicing attributes and each contact's linked user — they decide what data every recipient gets.

## Field notes

- `memory/reference_strategy_subscriptions_and_schedules.md` — endpoint families, the verified 2026-04-23 report email subscription (`sendNow: true`) with its save-time rewrites, the scheduled-refresh body. Its `mode` list matches the spec (11 values on create and read; corrected 2026-10-05 — `PRINTER`, `SNAPSHOT`, `PERSONAL_VIEW`, `SHARED_LINK` belong to the recipient endpoints' `deliveryType`; the official docs' sample GET does show `SHARED_LINK`). Its "classic cube refresh = `CACHE` subscription" is unverified.
- `memory/reference_strategy_admin_platform.md` ("Distribution services") — endpoint families; matches the spec.
- `memory/reference_mosaic_publish_path.md`, `memory/reference_mosaic_vs_legacy_surfaces.md` — classify before a refresh; what proves a publish.
- `memory/reference_strategy_runtime_analytics.md` — prompt-answer grammar for prompted content.
- `memory/reference_strategy_validation_workflows.md` (workflow 10) — the read-only distribution probe.
- `memory/reference_strategy_surface_matrix.md` — subscription access is separate from ACLs and security filters.
- `memory/reference_strategy_automation_coverage.md` ("Proposed skills" #3 — this skill) and `memory/reference_strategy_task_catalog.md` — routing.
- Official: REST docs `common-workflows/administration/distribution-services/manage-subscriptions/` (create, multi-content, prompted content) and `common-workflows/mosaic/publish/schedule-refresh-a-data-model`; mstrio-py `mstrio.distribution_services` (a dashboard is content type `dossier`). The docs' address example (`deliveryMode`, `device`, `value`) differs from the spec's `createAddress` body (`deliveryType`, `deviceId`, `physicalAddress`) — follow the spec.

## Status

- **Spec-verified (2026-10-05):** every operationId, parameter, enum and body field above, against the tenant's 2026 spec; every `call` line passes the tool's request validation offline.
- **Live-exercised (recorded in notes):** `GET /api/subscriptions` and `GET /api/schedules` (2026-04-21 validation run); a report email subscription created with `sendNow: true` (2026-04-23).
- **Not yet live:** `/send`, run status, prompted sends, schedule and event writes, contacts and groups, dynamic lists, bursting, History List, `data_model` refresh subscriptions. Record the first live run's payload and read-back in the subscriptions note.
