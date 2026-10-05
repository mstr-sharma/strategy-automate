---
name: strategy-ai
description: Automate Strategy (formerly MicroStrategy) AI — agents (REST paths still say "bot"), questions to agents and the SQL behind their answers, AI-ready content (certify models, cubes and agents; enable cubes for AI), the tenant's Mosaic and Agent MCP servers, Explorer's registry of external MCP servers, agent knowledge (unstructured-data nuggets), ontology vocabularies and agent evaluation. Use it for "agent", "bot", "Auto", "ask the agent", "agent config", "copy an agent", "activate an agent", "MCP readiness", "why is my model not in MCP", "certify for AI", "enable cube for AI", "Explorer MCP server", "agent knowledge", "ontology", "evaluate an agent". Calls go through the spec-validated strategy_api.py and strategy_mcp.py; most Agent management operations are internal (non-public) and are flagged as such.
---

# Strategy AI

Agents, questions, AI-ready content and the MCP surfaces of a Strategy environment, driven through `strategy_api.py` (REST) and `strategy_mcp.py` (the two MCP servers). Sign-in and the generic find → describe → dry run → `--yes` loop are in `skills/strategy-platform/SKILL.md`. The REST paths say `bot` where the product says agent; agents are object type 55, subtypes 14084 (bot), 14087 (agent), 14091 (universal agent).

## Scope

Owned API areas (`strategy_api.py ops --tag strategy-ai --internal`):
- **Agent** — questions (`/api/questions`: ask, poll, stream, suggestions, transformed SQL, full data; the documented Agent API), agent objects under `/api/v2/bots` (info, config, detail, copy, modify, chats, caches, training, tuning, evaluation, NER — internal except `columns`, `cubes/status` and `caches/temp`), nuggets, AI memories.
- **Auto Bots** — legacy `/api/bots`, `/api/chats`, `/api/learnings`: the instance/question POSTs are deprecated; `getConfiguration` and the question reads are still public.
- **Explorer** — Explorer chats, shared config, web-search config, the registry of external MCP servers.
- **Ontology** (vocabularies; concepts internal), **QuestionSet** (evaluation sets, internal), **Recommendations** (internal), **AI Storage** (internal), **AutoExpert** (support-case intake).

Cross-area calls used here: `certifyObject`, `updateObject`, `deleteObject`, `doQuickSearch`, `dumpCubes` (strategy-content); `getServerPrivilege`, `getUserPrivileges`, `bulkUpdatePrivileges`, `getMcpSettings`, `getCookieInfo`, `getIServerTrustStoreRelationship` (strategy-admin); `getFeedbackStatistics` (strategy-ops).

Route elsewhere: building or fixing the model an agent answers from → `build-mosaic-model`; checking answers against trusted numbers → `strategy-validation`; publishing an agent to users' Library and object ACLs → `strategy-content`; granting roles and privileges beyond the MCP checklist → `strategy-admin`; uploading documents → `create-unstructured-data`.

## How to work

```bash
API="python3 skills/strategy-platform/scripts/strategy_api.py"
MCP="python3 skills/strategy-platform/scripts/strategy_mcp.py"
$API ops --tag strategy-ai --internal --search "bots config"    # most Agent operations are internal
$API describe getBotConfig
$MCP --server agent tools                                       # Agent MCP server: tool names and arguments
```

1. Sign in: REST through `strategy_auth.py`; MCP through `$MCP login` (OAuth per server — `--server agent` is a separate login, and REST ignores MCP tokens).
2. Agents, cubes and nuggets live in a project: pass `--project <P>` (ID or name).
3. `describe` before every call; reads first. Writes are dry runs until `--yes`. Asking a question is a POST: it changes no metadata but runs the agent and uses AI capacity, so it still needs `--yes`.
4. Change agents on a copy, read back after every write, and delete copies and test nuggets at the end (`deleteObject`, type 55 or 90).
5. Say when a step uses an internal operation (`describe` shows `"internal": true`; `call` warns). For scripted agent management, mstrio-py's `Agent` / `list_agents` is the public alternative.
6. Never store question text, answers, instructions or uploaded content in memory or the repo unless the user asks and it is non-sensitive.

## Workflows

Placeholders: `<P>` project, `<A>` agent, `<C>` cube, `<N>` nugget, `<U>` user, `<G>` group (32-hex IDs); `<Q>` question ID.

### 1. Find and inspect agents
```bash
$API call doQuickSearch --project <P> -p type=55 -p name=<name> -p limit=100   # keep subtypes 14084/14087/14091
$API call getBotInfo --project <P> -p botId=<A>             # internal
$API call getBotConfig --project <P> -p botId=<A>           # internal: datasets, instructions, settings
$API call getBotColumns --project <P> -p botId=<A>          # public: attributes and metrics the agent can use
$API call getConfiguration --project <P> -p botId=<A>       # legacy bots
$MCP --server agent call list_agents                        # what an MCP user actually sees
```

### 2. Change an agent safely: copy, modify, activate
```bash
$API call copyBot --project <P> -p botId=<A> --body '{"name":"<name> - test","folderId":"<folder>","status":"draft"}'
$API call getBotConfig --project <P> -p botId=<copy> --out before.json
$API call modifyBot --project <P> -p botId=<copy> --body @patch.json   # {"operationList":[{"op":"replace","path":"<path from the config>","value":...}]}
$API call getBotConfig --project <P> -p botId=<copy>                   # read back, diff against before.json
$API call updateObject --project <P> -p id=<A> -p type=55 --body '{"status":"enabled"}'   # activate ("disabled" deactivates)
$API call deleteObject --project <P> -p id=<copy> -p type=55          # cleanup
```
- `copyBot` and `modifyBot` are internal; `modifyBot` paths are not enumerated in the spec — take them from the config you just read and change one at a time.
- Instructions carry context, vocabulary, metric definitions and rules — never data values (totals, rates, counts). Quote element values as names (`Plan Type values: 'Plus' ($7.99/mo)`); a line like `Plan Type: Plus 7.99` is parsed as literal element names and filters to zero rows.
- Test the copy with workflow 3 before touching the published agent; confirm before modifying an agent users rely on.

### 3. Ask a question and see its SQL
```bash
$MCP --server agent call ask_agent --args '<JSON: agent id + projectId from list_agents, and the question>'
$API call createQuestion_1 -p Prefer=respond-async --body '{"text":"<question>","bots":[{"id":"<A>","projectId":"<P>"}]}' --yes
$API call queryMessage_1 -p questionId=<Q>                       # poll: 202 while running, 200 with answers[].text
$API call getTransformedSql --project <P> -p questionId=<Q> --yes # POST read: the full SQL behind the answer
$API call getChats_1 --project <P> -p botId=<A>                   # this user's history with the agent
```
- Prefer the Agent MCP `ask_agent`: it stays inside the agent's datasets and honours its instructions. A bare `POST /api/questions` has answered from a different certified dataset than the agent's — check numbers with `strategy-validation`.
- Without `bots`, a question is routed to the most suitable agent (`-p botIds=` / `-p contentGroupIds=` narrow it). One question at a time per user (`ERR001` "another question being processed"); expect 40–60 s per answer.
- Answers run as the signed-in user, with that user's security filters.

### 4. Make content AI-ready: certify, enable cubes for AI
```bash
$API call certifyObject --project <P> -p id=<model> -p type=3 -p certify=true --yes        # published Mosaic model
$API call dumpCubes --project <P> --body '{"cubeObjects":[{"cubeId":"<C>","cubeType":"OLAP"}]}' --yes
$API call getCubeStatus_1 --project <P> --body '{"cubeIds":["<C>"],"useLatest":true}' --yes # POST read: poll to ready
$API call certifyObject --project <P> -p id=<C> -p type=3 -p certify=true --yes
$API call certifyObject --project <P> -p id=<A> -p type=55 -p certify=true --yes           # agent
$API call doQuickSearch --project <P> -p type=3 -p aiConsumable=true -p certifiedStatus=CERTIFIED_ONLY
```
- Enable-for-AI is `dumpCubes` — what mstrio-py's `enable_for_ai()` sends for cubes, reports and Mosaic models: `cubeType` `OLAP` for an Intelligent Cube (subtype 776), `MTDI` for subtype 779 (Super Cube, imported dataset, Mosaic model), `SUBSET_REPORT` for a report. Publish first. Status: `started`, `pending`, then `ready`, `failed` or `baseCubeDecertified` (terminal).
- The Mosaic MCP server lists a Mosaic model once it is published (`build-mosaic-model`) and certified; `build_mosaic.py certify --object-id <model>` wraps the certify call.
- Decertifying (`certify=false`) removes content from every MCP and agent user: confirm first.

### 5. MCP readiness: why is something missing from MCP?
1. **Servers up:** `curl -s -o /dev/null -w '%{http_code}\n' https://<tenant>.strategy.com/collaboration/mcp/mosaic` → `401` means up (same for `/mcp/agent`); `https://<tenant>.strategy.com/collaboration/status` → `"state":"running"` and `"isAiConfigured":true`.
2. **The user:** a named, non-administrator account (product help: administrators and Platform Support Administrator members cannot use MCP) holding "Use Mosaic MCP Server" (Mosaic) or "Use Agent MCP Server" + "Run AI Bots" (Agents):
   ```bash
   $API call getServerPrivilege                                     # find the three IDs by name
   $API call getUserPrivileges -p id=<U> -p privilege.level=server
   $API call bulkUpdatePrivileges --body '{"operation":"grant","targetPrivileges":[<privId>],"userGroups":["<G>"]}'   # confirm first
   ```
3. **The content:** Mosaic models published and certified; cubes enabled for AI and certified (workflow 4); agents active, certified and in the user's Library; the user has View on each object (ACL — `strategy-content`).
4. **The environment:** collaboration service enabled; Library-to-I-Server trust (`getIServerTrustStoreRelationship`); cookies `SameSite=None` + `Secure` (`getCookieInfo`); MCP OAuth client settings (`getMcpSettings`, internal: redirect URIs, scopes). Clients that keep re-authenticating need `offline_access` in their scope; their authorize/token URLs are under `/collaboration`, not `/oauth2`.
5. **Prove it as that user:** `$MCP login`, `$MCP call get_models --args '{"project":"<project name>"}'` (certified content only: `Mosaic Model` and classic `Other Model` rows), `$MCP --server agent call list_agents`.

### 6. Explorer: register an external MCP server
Explorer's registry holds EXTERNAL MCP servers whose tools Explorer may call. Strategy's own Mosaic and Agent MCP servers are not registered here.
```bash
$API call getServers
$API call createServer --body '{"name":"<name>","url":"https://<server>/mcp","transportType":"HTTP_JSON_RPC","auth":{"mode":"OAUTH"},"allowedTools":["<tool>"]}'
$API call connect -p name=<name> --yes                # per user; OAuth finishes in the browser (callback)
$API call getServerStatus -p id=<name>
$API call jsonRpc -p name=<name> --body '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' --yes   # smoke test through the proxy
$API call disconnect -p name=<name> --yes
$API call deleteServer -p name=<name> --yes           # cleanup
```
- Keep `allowedTools` to what is needed: Explorer calls those tools as the signed-in user.
- API keys and client secrets (`auth.apiKey.value`, `auth.oauth.clientSecret`) are written into a body file by the human, never typed by the agent.
- `getConfig` / `updateConfig` hold shared Explorer settings (`features.webSearchEnabled`, web-search allow and deny lists). `updateConfig` is a PUT: send back the whole object you read, changed in one place.

### 7. Agent knowledge: unstructured data
Upload with the `create-unstructured-data` skill (`create_unstructured.py`: PPTX → Markdown, multipart `POST /api/nuggets?type=unstructuredData`, status poll); `strategy_api.py call` does not send multipart bodies.
```bash
$API call bulkGetNuggetsStatus --body '{"nuggets":[{"id":"<N>","projectId":"<P>"}]}' --yes   # internal POST read: indexing -> ready
$API call getNuggets --project <P> -p id=<N>          # internal
$API call getCategories --project <P> -p id=<N>
$API call deleteObject --project <P> -p id=<N> -p type=90   # standalone nugget (type 90, subtype 23042)
```
- `POST /api/nuggets/{id}/deleteRequest` edits an agent's nugget collection; it does not delete a standalone nugget.

### 8. Ontology vocabularies
```bash
$API call getVocabularies
$API call addValue -p fieldName=domain --body '{"value":"<term>"}' --yes          # idempotent
$API call removeValue -p fieldName=domain -p value=<term> --yes
$API call updateFieldVocabulary -p fieldName=metric_family --body '{"values":["<a>","<b>"]}'   # replaces the whole list
```
- `fieldName` is one of `domain`, `metric_family`, `category_metric`, `category_report`, `category_concept`. Read before `updateFieldVocabulary`. Concepts and concept groups (`createConcept`, `getConcept`, …) are internal.

### 9. Evaluate an agent
```bash
$API call listQuestionSets --project <P>                                   # internal
$API call getEvaluationJob --project <P> -p botId=<A> -p jobId=<job>        # internal
$API call getAiAdminJobs --project <P> -p botId=<A>                         # internal: AI jobs in the project
$API call getFeedbackStatistics --project <P> -p id=<A> -p period=last30days # user feedback (strategy-ops)
```
- `createQuestionSet` and `createEvaluationJob` take multipart bodies (a question file or `questionSetId`): send them with `build_mosaic.py api-call --file/--form` (multipart only when a `--file` is given), and evaluate the test copy rather than the published agent.

## Safety rules

- Agent writes change what users get answered: work on a copy, and confirm before modifying, deactivating or decertifying anything users rely on.
- Confirm before deleting conversation data or knowledge: `deleteAllChat`, `deleteAiMemories`, `deleteAllChats`, `deleteLearnings`, `deleteNuggets`, `deleteServer`, and `deleteObject` on anything you did not create in this session.
- Granting MCP privileges, registering external MCP servers and enabling web search widen what AI can reach: only on explicit request.
- Never put credentials in questions, instructions, nuggets or MCP server configurations; never enter or print tokens or secrets.
- `createCase` (AutoExpert) opens a support case with diagnostics: confirm the content first.
- Internal operations are not part of the public contract: say so when a workflow depends on one, and re-check after upgrades.

## Field notes

- `memory/reference_strategy_ai_agents.md` — documented Agent APIs vs internal v2 bot management vs deprecated Bot APIs; MCP `ask_agent` vs bare `/api/questions` (2026-08-24); the instruction-value gotcha.
- `memory/reference_mcp_tools.md` — the two MCP servers, certified-only `get_models`, classic `Other Model` content, AI enablement.
- `memory/reference_strategy_authentication.md` — MCP OAuth (dynamic client registration, one token per server), REST ignoring bearer tokens.
- `memory/reference_mosaic_ai_service.md` — Studio's `/api/aiservice/model/*` calls are UI internals absent from the spec: optional hints, never the source of truth.
- `skills/create-unstructured-data/SKILL.md` — nugget upload, string status (`indexing` → `ready`), delete path.
- `memory/reference_mosaic_acl.md` — the View/Use rights MCP users need on each object (view = 197).
- `memory/feedback_mosaic_identity_token_privilege_downgrade.md` — privileges granted at project level only (`isUserLevelAllowed: false`) and the 403 they cause on user-level checks.
- `memory/reference_strategy_automation_coverage.md` — proposed skill 1 (`strategy-mcp-readiness`) is workflows 4–5 here.
- `memory/reference_strategy_task_catalog.md` — request routing; `memory/reference_strategy_project_loading.md` — agents in an unloaded project fail with `-2147209151`.
- Official: product help NextGenAI `agent_MCPServerIntegration.htm`, `agent_MCPServerTroubleshooting.htm`; REST docs `common-workflows/analytics/use-bot-api` (deprecated Bot APIs) and the Agent / unstructured-data pages; mstrio-py `project_objects.agents` and `utils.ai` (`enable_for_ai`).

## Status

- Exercised live, per notes: Agent MCP `list_agents` / `ask_agent` and bare `POST /api/questions` with polling (2026-08-24); MCP server 401 health check, OAuth sign-in and certified-only `get_models` including classic `Other Model` content (2026-10-05); nugget upload, status and delete through `create-unstructured-data` (2026-07-22).
- Spec-verified only (`describe` plus an offline dry run against the 2026 spec; enable-for-AI cross-checked with mstrio-py): agent inspect, copy, modify and activate; `getTransformedSql`; `dumpCubes` and cube status; `certifyObject` for models, cubes and agents; the Explorer MCP registry; ontology; evaluation. Record the first live run of each in `memory/reference_strategy_ai_agents.md`.
