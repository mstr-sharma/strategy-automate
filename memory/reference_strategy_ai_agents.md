---
name: Strategy AI agents, bots, chats, nuggets, and unstructured data
description: Clarify Auto Agent APIs, legacy/deprecated Bot APIs, chat/question flows, and AI-related indexing/nugget surfaces.
type: reference
originSessionId: local-codex-2026-04-21
---
Use this when the user asks for Strategy AI, Auto Agent, Agent, Bot, chat, question answering, suggestions, training sets, NER indexing, nuggets/learnings, auto narratives, or unstructured data.

## Naming and deprecation

Strategy documentation says legacy Bot APIs are deprecated because Auto Agent technology replaces the older Auto Bot system. However, many current REST paths still use `bot` in the URL or operation names while summaries say "agent".

Routing rule:

- Prefer **Auto Agent** paths exposed in live OpenAPI, especially `/api/questions...` and `/api/v2/bots...`.
- Treat older `/api/bots/...` and `/api/chats/...` instance/message APIs as legacy/deprecated unless the tenant or object only supports them.
- Always check `?visibility=all`; AI/agent paths move quickly and can be hidden or renamed across tenants.

## Question and answer flow

Current Auto Agent style endpoints observed in live OpenAPI:

- Ask a question: `POST /api/questions`
- Ask with image: `POST /api/questions/withImage`
- Ask multiple questions: `POST /api/questions/collections`
- Suggestions: `POST /api/questions/suggestions`
- Get/cancel/update question: `GET/DELETE/PATCH /api/questions/{questionId}`
- Stream: `GET /api/questions/{questionId}/stream`
- Full data export: `POST /api/questions/{questionId}/fulldata`, then `GET /api/questions/{questionId}/fulldata/{dataId}`
- Answer data/images/diagnostics: `/api/questions/{questionId}/answers/...`, `/diagnostics/...`

These are runtime conversational/data APIs; they do not create semantic model objects.

## Agent object/config flow

Agent management still appears under `/api/v2/bots` in current tenant OpenAPI:

- Create draft agent: `POST /api/v2/bots`
- Read/modify/copy agent: `GET/PATCH /api/v2/bots/{botId}`, `POST /api/v2/bots/{botId}/copy`
- Chats: `/api/v2/bots/{botId}/chats`, `/chats/{chatId}`, `/duplicate`
- Columns/completion data: `/api/v2/bots/{botId}/columns`
- Config: `/api/v2/bots/{botId}/config`
- Dataset/column descriptions: `/api/v2/bots/{botId}/datasetContainers/{datasetContainerId}/datasets/{datasetId}/descriptions`
- Training jobs/sets: `/api/v2/bots/{botId}/trainingjobs`, `/trainingsets`
- NER elements/indexing: `/api/v2/bots/{botId}/nerElements/searches`, `/nerIndexStatus/query`
- Question group cache/training: `/api/v2/bots/{botId}/caches/questionGroups...`

Agent writes are high-impact because they can affect user-facing AI behavior. Read config and related datasets first.

## Legacy bot/chat APIs

Older paths include:

- `/api/bots/{botId}/instances`
- `/api/bots/{botId}/instances/{instanceId}/questions`
- `/api/bots/{botId}/instances/{instanceId}/suggestions`
- `/api/bots/{botId}/configuration`
- `/api/bots/{botId}/questions`
- `/api/chats`, `/api/chats/{chatId}/messages`, `/api/chats/{chatId}/bot`

Use only when needed for backward compatibility. Document that the workflow used deprecated/legacy bot APIs if it does.

## Nuggets, learnings, auto narratives, and unstructured data

AI-adjacent surfaces:

- Nuggets: `/api/nuggets`, `/api/nuggets/{id}`, `/api/nuggets/{id}/categories`, `/api/nuggets/{id}/file`, `/api/nuggets/status/query`.
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
