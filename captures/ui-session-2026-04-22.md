# UI capture session 2026-04-22

## Home-page load
- POST /api/searches/objects?includeAncestors=true&showNavigationPath=true
- GET  /api/library/dataModels/favorites                     **new**
- GET  /api/searches/results?pattern=4&type=14088            type 14088 = ?
- GET  /api/searches/results?pattern=4&type=779&type=776&type=23042   type 23042 = ? (779=data_model, 776=logical_table)
- POST /api/nuggets/status/query

## Opening new model editor (UI routes to /app/datamodel/{proj}/000...000)
- GET  /api/v2/configurations/featureFlags
- GET  /api/iams                                             AI/Agent mgmt
- GET  /api/gateways                                         **new**
- GET  /api/folders/preDefined/73                            **new predefined folder id**
- GET  /api/drivers                                          **new — datasource drivers**
- GET  /api/dataServer/usage/users/{userId}                  **new — usage stats**
- POST /api/model/changesets?enableOperationHistory=true     **new flag: enableOperationHistory**
- POST /api/dataServer/workspaces                            **new — workspace/sandbox**
- GET  /api/model/diagnostics/status                         **new — diagnostics health**
- POST /api/model/dataModels                                 201 (matches our memory)

## Second capture — AI-assisted model build ("Building your Mosaic Model...")

User added 5 tables to a new model via Sources picker; system ran automated modeling.

Sequence:
1. POST /api/dataServer/workspaces/{wsId}/pipelines                              (201)
2. POST /api/dataServer/workspaces/{wsId}/pipelines/{pid}/tables                 (202 async)
3. GET  .../pipelines/{pid}/tables/{tid}                                         (202→200 polling)
4. GET  .../pipelines/{pid}/tables/{tid}?showRawData=true                        (preview)
5. POST /api/model/batch?allowPartialSuccess=true&showChanges=true               (×2)
6. POST /api/aiservice/model/tables/primaryKeys                                  **AI — PK detection**
7. POST /api/aiservice/model/objects/linking                                     **AI — relationship inference**
8. POST /api/model/batch?allowPartialSuccess=false&showChanges=true              (×3 structural writes)
9. GET  .../pipelines/{pid}/distinctCount?columnIndices=0&columnIndices=2        (cardinality profiling)
10. POST /api/aiservice/model/objects/lookupTable                                **AI — lookup-table selection**
11. POST /api/aiservice/model/objects/multiFormAttributes                        **AI — multi-form attr detection** (×5, one per table)

## Takeaways
- Strategy has a full AI-automated modeling surface (`/api/aiservice/model/*`). Our `build_mosaic.py`
  duplicates this with heuristics; we should route to the AI service as primary and fall back.
- Two batch modes: allowPartialSuccess=true (metadata), =false (structural)
- Workspace/pipeline = async import sandbox; pipelines are per-table
- distinctCount endpoint = built-in cardinality profiling we didn't know existed
