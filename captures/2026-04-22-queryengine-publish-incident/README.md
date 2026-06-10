---
name: QueryEngineServer publish stall on Strategy ONE Shared Studio 2026-04-22
description: Dated incident record — tenant-level QueryEngineServer parallel-mode stall (iServerCode -2147212544) on every in-memory Mosaic publish on the Shared Studio tenant, including a pre-existing unrelated 6-table model. Moved here from reference_mosaic_vs_legacy_surfaces.md; durable publish rules live in memory/reference_mosaic_publish_path.md.
type: feedback
---

## Tenant-level failure mode observed on Strategy ONE Shared Studio (2026-04-22)

Publishing ANY Mosaic model in-memory on the Studio tenant — including a pre-existing, unrelated 6-table model (`OC Test`) — returned the same QueryEngineServer stall:

```
(QueryEngine encountered error: Parallel mode report execution has stalled before report is finished.
 Canceling report.. Error in Process method of Component: QueryEngineServer,
 Project Shared Studio, Job <N>, Error Code= -2147212544.)
```

Symptoms:
- `publish` returns 204 and tables briefly show `schema_comparison_completed`.
- Status then flips to top-level `-2147212544` with every table `status:"error"`.
- Reproducible across distinct models, user sessions, and clean server-side instance IDs.

Conclusion at the time: this looked like an Intelligence Server / QueryEngineServer health issue at the tenant level, NOT a per-model metric-shape bug. When this signature appears:
1. Confirm tenant-wide by publishing a known-good in-memory model.
2. Fall back to `connect_live` serve mode (PATCH `dataServeMode`) so Trino federation sees the model immediately — no cube materialization needed. Validation still works; you just lose the in-memory performance benefit.
3. Surface the tenant issue to the admin; do NOT keep retrying publish in a loop.

Do not silently retry the legacy `/api/cubes/...` path as a "works around the regression" — at the time it 2xx'd while the model appeared to stay unpublished, which is exactly the confusion that spawned the surface-delineation memory.

## 2026-04-23 correction

Follow-up the next day (see `captures/2026-04-23-studio-publish-stall/README.md`) showed the stall is triggered at least as much by warehouse-catalog dataType sentinels as by tenant health — a REF model built in the UI with clean dataTypes published fine on the same tenant, and `/api/cubes/{id}?cubeAction=publish` turned out to be the path the UI itself uses for Mosaic models. The durable rules (single publish trigger per run, clean dataTypes, always poll `publishStatus` or Trino-probe before declaring success) live in `memory/reference_mosaic_publish_path.md`.
