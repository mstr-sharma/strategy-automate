---
name: Strategy AI agents, bots, chats, nuggets, and unstructured data
description: Clarify Auto Agent APIs, legacy/deprecated Bot APIs, chat/question flows, and AI-related indexing/nugget surfaces.
type: reference
originSessionId: codex-session
---
Use this when the user asks for Strategy AI, Auto Agent, Agent, Bot, chat, question answering, suggestions, training sets, NER indexing, nuggets/learnings, auto narratives, or unstructured data.

## Naming and deprecation

Strategy documentation says legacy Bot APIs are deprecated because Auto Agent technology replaces the older Auto Bot system. However, many current REST paths still use `bot` in the URL or operation names while summaries say "agent".

Routing rule (corrected 2026-10-05 against the tenant spec and the REST docs "Auto Agent APIs" / "Bot APIs"):

- The **documented Agent APIs are `/api/questions`** (ask, get by id, chat history `GET /api/questions?botId=`, suggestions, images) plus `GET /api/v2/bots/{botId}/columns` (attributes/metrics for auto-complete). Prefer these.
- **v2 bot management is internal**: create / copy / read / patch, chats, config, dataset descriptions, training, NER and question-group cache under `/api/v2/bots/...` are all `visibility: internal`. The only public v2 paths are `GET /api/v2/bots/{botId}/columns`, `POST /api/v2/bots/cubes/status` (Enable-for-AI status) and `POST /api/v2/bots/{botId}/caches/temp/check|promote`.
- **Deprecated** (spec flag + docs): `POST /api/bots/{botId}/instances`, `…/instances/{id}/questions`, `…/instances/{id}/suggestions`, `…/instances/{id}/topics` (the docs also list deleting a bot instance). **Not deprecated and public:** `GET /api/bots/{botId}/configuration`, `GET /api/bots/{botId}/questions`, `GET /api/bots/{botId}/questions/{questionId}`. `/api/chats/...` is internal.
- mstrio-py manages agents with `Agent` / `list_agents` (`mstrio.project_objects.agents`, which superseded `bots` in 11.5.10.101).
- Always check `?visibility=all`; AI/agent paths move quickly and can be hidden or renamed across tenants.

## Question and answer flow

Current Auto Agent style endpoints observed in live OpenAPI:

- Ask a question: `POST /api/questions`
- Ask with image: `POST /api/questions/withImage`
- Ask multiple questions: `POST /api/questions/collections`
- Suggestions: `POST /api/questions/suggestions`
- Get question: `GET /api/questions/{questionId}` (public); cancel/update `DELETE/PATCH /api/questions/{questionId}` are internal
- Stream: `GET /api/questions/{questionId}/stream`
- Full data export: `POST /api/questions/{questionId}/fulldata` (internal), then `GET /api/questions/{questionId}/fulldata/{dataId}` (public)
- Answer data/images/diagnostics: `/api/questions/{questionId}/answers/...`, `/diagnostics/...`

These are runtime conversational/data APIs; they do not create semantic model objects.

## Agent object/config flow

Agent management appears under `/api/v2/bots` in the tenant OpenAPI, but **every path in this list is `visibility: internal`** (corrected 2026-10-05) — reachable, not a contract. The public exceptions are `GET /api/v2/bots/{botId}/columns`, `POST /api/v2/bots/cubes/status` and `POST /api/v2/bots/{botId}/caches/temp/check|promote`. For scripted agent management prefer mstrio-py's `Agent` class.

- Create draft agent: `POST /api/v2/bots`
- Read/modify/copy agent: `GET/PATCH /api/v2/bots/{botId}`, `POST /api/v2/bots/{botId}/copy`
- Chats: `/api/v2/bots/{botId}/chats`, `/chats/{chatId}`, `/duplicate`
- Columns/completion data: `GET /api/v2/bots/{botId}/columns` (public — documented as "Get attributes and metrics from the agent")
- Config: `/api/v2/bots/{botId}/config`
- Dataset/column descriptions: `/api/v2/bots/{botId}/datasetContainers/{datasetContainerId}/datasets/{datasetId}/descriptions`
- Training jobs/sets: `/api/v2/bots/{botId}/trainingjobs`, `/trainingsets`
- NER elements/indexing: `/api/v2/bots/{botId}/nerElements/searches`, `/nerIndexStatus/query`
- Question group cache/training: `/api/v2/bots/{botId}/caches/questionGroups...`

Agent writes are high-impact because they can affect user-facing AI behavior. Read config and related datasets first.

## Legacy bot/chat APIs

Older paths include (status per the 2026 spec + "Bot APIs" docs page; corrected 2026-10-05):

- `POST /api/bots/{botId}/instances` — **deprecated**
- `POST /api/bots/{botId}/instances/{instanceId}/questions` — **deprecated**
- `POST /api/bots/{botId}/instances/{instanceId}/suggestions` (and `/topics`) — **deprecated**
- `DELETE /api/bots/{botId}/instances/{instanceId}` — public in the spec, listed as deprecated in the docs
- `GET /api/bots/{botId}/configuration` — public, **not deprecated**
- `GET /api/bots/{botId}/questions`, `GET /api/bots/{botId}/questions/{questionId}` — public, **not deprecated**
- `/api/chats`, `/api/chats/{chatId}/messages`, `/api/chats/{chatId}/bot` — internal

Use the deprecated instance/question POSTs only for backward compatibility, and say so when a workflow does. The configuration and question-list reads are fine to use.

## Nuggets, learnings, auto narratives, and unstructured data

AI-adjacent surfaces:

- Nuggets: `/api/nuggets`, `/api/nuggets/{id}`, `/api/nuggets/{id}/categories`, `/api/nuggets/{id}/file`, `/api/nuggets/status/query`. Most are `visibility: internal` — only visible in `openapi.yaml?visibility=all`. **Wrapped workflow (verified 2026-07-22):** `skills/create-unstructured-data/` creates unstructured-data nuggets end-to-end (PPTX→Markdown conversion + multipart `POST /api/nuggets?type=unstructuredData` + status poll); see its SKILL.md gotchas for the 200-vs-202, string `status` (`indexing`→`ready`), Accept-header, and delete-path (`DELETE /api/objects/{id}?type=90`, nugget = type 90/subtype 23042) findings. Generic multipart uploads: `build_mosaic.py api-call --file FIELD=PATH --form k=v`.
- Learnings: `/api/learnings`, `/api/learnings/delete`, `/api/telemetry/bots/{id}/learnings`.
- Dashboard auto narratives: `/api/dashboards/{dashboardId}/instances/{instanceId}/chapters/{chapterKey}/autoNarratives/{visualizationKey}`.
- Dataset AI indexing: `/api/dashboards/{dashboardId}/instances/{instanceId}/datasets/{datasetId}/instances/{datasetInstanceId}/index`.
- AI visualization type revision: `/api/aiservice/chats/dossier/reviseVisualizationType`.
- Data Gateway agents: `/api/iserver/dataGateway/agents` are gateway/connection agents, not Auto Agent chat objects.

## Verification checklist

- Confirm whether the user means Auto Agent, legacy Bot, dashboard auto narrative, or Data Gateway agent.
- Resolve project/application/agent IDs and related dataset/model IDs before writes.
- Prefer read-only config/columns/description calls before training or NER updates.
- For questions, capture question IDs and stream/status/result data IDs.
- Do not persist conversation contents, prompts, answer text, or uploaded images into memory unless the user explicitly asks and the content is non-sensitive.

## Asking agents: MCP connector vs bare /api/questions (verified 2026-08-24, studio)

- The **MCP agent connector** (`ask_agent` with id + projectId from `list_agents`) reliably scopes to the bot's
  bound AI-dataset collection and honors its customInstructions. Answers validated against cube totals.
- **Bare `POST /api/questions` with `botId`** (Prefer: respond-async, poll `GET /api/questions/{id}` until 200,
  answers[].text) SOMETIMES answers from a different "certified" dataset entirely (<hospitality-customer>-dining-flavored Net
  Sales/Snack/Guest answers with guardrail boilerplate) while the first question scoped correctly — do NOT trust
  it for bot-scoped Q&A; prefer the connector or bot-scoped chats. Also: one question at a time per user
  (ERR001 "another question being processed"), ~40-60 s per answer.
- Agent-instruction gotcha: a values line like "Plan Type: EReaderCo Plus Read 7.99, ..." gets parsed as literal
  element names -> zero-row filters. Write "Plan Type values: 'EReaderCo Plus Read' ($7.99/mo)" instead.
- Two-fact questions ("total revenue" = sales + MRR) grouped by a shared dim can fan ~15x (single-pass SQL);
  the same pair grouped by the conformed date was correct. Pre-seed single-process phrasings.
