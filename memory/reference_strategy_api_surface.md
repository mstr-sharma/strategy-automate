---
name: Strategy REST API surface — every area, its owning skill, and coverage
description: Generated map of the tenant's REST API (operations per area, public vs internal), the skill that owns each area, and how much of it this repo's scripts and notes reference. Regenerate with `strategy_api.py coverage --write`.
type: reference
---

Generated 2026-10-05 from the tenant's OpenAPI spec (version 2026) by `skills/strategy-platform/scripts/strategy_api.py coverage --write`. Do not hand-edit the table; change `SKILL_TAGS` in `strategy_api.py` to move an area.

**Every operation is callable** with `strategy_api.py call <operationId>` — validated against the spec, with project, changeset and `Prefer` headers filled in and writes gated behind `--yes`. The columns below measure the *extra* layers: typed helpers (operations whose path a script calls), skill workflows (operations a SKILL.md runs with `strategy_api.py call`), and field notes (paths mentioned in memory/skills). A reference is a pointer, not proof of a live-tested workflow — each skill's Status section says what has run live.

Totals: 1682 operations (1146 public); 174 called by scripts, 248 run by skill workflows, 680 mentioned in notes.

| Owning skill | API area (spec tag) | Operations | Public | In scripts | In skill workflows | In notes |
|---|---|---|---|---|---|---|
| `build-mosaic-model` | Datasource Management | 73 | 54 | 5 | 0 | 28 |
| `build-mosaic-model` | Data Models | 68 | 68 | 37 | 1 | 51 |
| `build-mosaic-model` | Workspaces | 13 | 13 | 0 | 0 | 2 |
| `build-mosaic-model` | Attributes | 9 | 8 | 4 | 0 | 4 |
| `build-mosaic-model` | Model Server | 9 | 0 | 5 | 0 | 9 |
| `build-mosaic-model` | Tables | 7 | 7 | 4 | 0 | 4 |
| `build-mosaic-model` | Open Semantic Layer | 6 | 0 | 0 | 0 | 0 |
| `build-mosaic-model` | Security Filters | 6 | 6 | 6 | 0 | 6 |
| `build-mosaic-model` | Prompts | 5 | 5 | 2 | 0 | 3 |
| `build-mosaic-model` | Schema | 5 | 5 | 0 | 0 | 4 |
| `build-mosaic-model` | Drivers | 4 | 3 | 0 | 0 | 2 |
| `build-mosaic-model` | Mosaic | 4 | 4 | 0 | 0 | 2 |
| `build-mosaic-model` | Custom Groups | 4 | 4 | 0 | 0 | 1 |
| `build-mosaic-model` | User Hierarchies | 4 | 4 | 4 | 0 | 4 |
| `build-mosaic-model` | Metrics | 4 | 4 | 3 | 0 | 4 |
| `build-mosaic-model` | Calendars | 4 | 4 | 0 | 0 | 0 |
| `build-mosaic-model` | Gateways | 3 | 2 | 0 | 0 | 1 |
| `build-mosaic-model` | Changesets | 3 | 3 | 3 | 0 | 3 |
| `build-mosaic-model` | System Hierarchy | 3 | 3 | 1 | 0 | 3 |
| `build-mosaic-model` | Facts | 3 | 3 | 3 | 0 | 3 |
| `build-mosaic-model` | Filters | 3 | 3 | 2 | 0 | 3 |
| `build-mosaic-model` | Drill Maps | 3 | 3 | 0 | 0 | 0 |
| `build-mosaic-model` | Derived Elements | 3 | 3 | 0 | 0 | 0 |
| `build-mosaic-model` | Consolidations | 3 | 3 | 0 | 0 | 1 |
| `build-mosaic-model` | Subtotals | 3 | 3 | 0 | 0 | 0 |
| `build-mosaic-model` | Base Formulas | 3 | 3 | 0 | 0 | 0 |
| `build-mosaic-model` | Transformations | 3 | 3 | 1 | 0 | 1 |
| `build-mosaic-model` | Hierarchies | 2 | 2 | 0 | 0 | 2 |
| `build-mosaic-model` | Data Server | 1 | 0 | 0 | 0 | 0 |
| `strategy-admin` | System Administration | 176 | 86 | 0 | 7 | 16 |
| `strategy-admin` | User Management | 55 | 48 | 12 | 17 | 25 |
| `strategy-admin` | Projects | 40 | 33 | 2 | 8 | 17 |
| `strategy-admin` | Preferences | 26 | 22 | 0 | 0 | 12 |
| `strategy-admin` | SCIM | 20 | 17 | 0 | 3 | 3 |
| `strategy-admin` | Configuration | 16 | 1 | 2 | 0 | 2 |
| `strategy-admin` | License | 14 | 13 | 0 | 8 | 0 |
| `strategy-admin` | Configurations | 13 | 3 | 0 | 0 | 5 |
| `strategy-admin` | Vault Connection Management | 11 | 10 | 0 | 5 | 0 |
| `strategy-admin` | Security Roles | 10 | 10 | 2 | 7 | 5 |
| `strategy-admin` | Languages | 9 | 9 | 0 | 0 | 2 |
| `strategy-admin` | Multi Tenant | 9 | 9 | 0 | 6 | 2 |
| `strategy-admin` | Applications | 7 | 7 | 0 | 0 | 0 |
| `strategy-admin` | Client Configurations | 6 | 0 | 0 | 0 | 0 |
| `strategy-admin` | Scope Filters | 6 | 6 | 0 | 0 | 0 |
| `strategy-admin` | Microsoft Teams App | 6 | 0 | 0 | 0 | 0 |
| `strategy-admin` | IAM | 5 | 0 | 0 | 0 | 2 |
| `strategy-admin` | URL Scan | 5 | 0 | 0 | 0 | 0 |
| `strategy-admin` | Desktops | 4 | 0 | 0 | 0 | 0 |
| `strategy-admin` | Timezones | 4 | 4 | 0 | 0 | 0 |
| `strategy-admin` | Emails | 2 | 2 | 0 | 0 | 0 |
| `strategy-admin` | Notifications | 1 | 0 | 0 | 0 | 0 |
| `strategy-admin` | Privilege Management | 1 | 1 | 0 | 1 | 1 |
| `strategy-ai` | Agent | 91 | 21 | 2 | 15 | 44 |
| `strategy-ai` | Explorer | 34 | 16 | 0 | 7 | 18 |
| `strategy-ai` | Auto Bots | 30 | 9 | 2 | 1 | 18 |
| `strategy-ai` | Ontology | 12 | 4 | 0 | 4 | 4 |
| `strategy-ai` | Recommendations | 11 | 0 | 0 | 0 | 0 |
| `strategy-ai` | QuestionSet | 4 | 0 | 0 | 1 | 0 |
| `strategy-ai` | AI Storage | 2 | 0 | 0 | 0 | 0 |
| `strategy-ai` | AutoExpert | 1 | 1 | 0 | 0 | 1 |
| `strategy-content` | Dashboards(Dossiers) and Documents | 67 | 41 | 4 | 15 | 28 |
| `strategy-content` | Reports | 44 | 39 | 4 | 9 | 27 |
| `strategy-content` | Cubes | 39 | 33 | 7 | 8 | 22 |
| `strategy-content` | Object Management | 33 | 13 | 4 | 5 | 18 |
| `strategy-content` | Library | 31 | 15 | 5 | 3 | 15 |
| `strategy-content` | Browsing | 31 | 26 | 7 | 7 | 13 |
| `strategy-content` | Datasets | 21 | 11 | 0 | 3 | 11 |
| `strategy-content` | Datamarts | 15 | 11 | 0 | 0 | 1 |
| `strategy-content` | Maps | 15 | 0 | 0 | 0 | 0 |
| `strategy-content` | Dashboard(Dossier)_ToBeDeprecated_Use_Dashboards(Dossiers) | 13 | 13 | 0 | 0 | 0 |
| `strategy-content` | Hyper | 11 | 0 | 0 | 0 | 11 |
| `strategy-content` | MDX Cube Catalog | 11 | 2 | 0 | 0 | 2 |
| `strategy-content` | Dashboards | 10 | 4 | 0 | 0 | 4 |
| `strategy-content` | Runtimes | 7 | 6 | 0 | 0 | 0 |
| `strategy-content` | Content Bundles | 6 | 6 | 0 | 0 | 0 |
| `strategy-content` | Content Groups | 6 | 6 | 2 | 2 | 4 |
| `strategy-content` | Shared File Store | 5 | 5 | 0 | 0 | 0 |
| `strategy-content` | Dashboard(Dossier) Personal View | 4 | 4 | 0 | 0 | 3 |
| `strategy-content` | Palettes | 4 | 4 | 0 | 0 | 0 |
| `strategy-content` | Themes | 3 | 3 | 0 | 0 | 0 |
| `strategy-content` | Transaction Reports | 3 | 3 | 0 | 0 | 0 |
| `strategy-content` | Elements | 2 | 0 | 0 | 0 | 0 |
| `strategy-content` | Cards | 1 | 0 | 0 | 0 | 1 |
| `strategy-content` | Dashboard(Dossier) | 1 | 1 | 0 | 0 | 0 |
| `strategy-distribution` | Subscriptions | 35 | 35 | 6 | 18 | 18 |
| `strategy-distribution` | Devices | 12 | 6 | 0 | 1 | 2 |
| `strategy-distribution` | History List | 10 | 7 | 0 | 5 | 0 |
| `strategy-distribution` | Schedules | 7 | 7 | 2 | 3 | 6 |
| `strategy-distribution` | Contact Groups | 6 | 6 | 0 | 1 | 6 |
| `strategy-distribution` | Contacts | 6 | 6 | 0 | 2 | 6 |
| `strategy-distribution` | Events | 6 | 6 | 0 | 3 | 3 |
| `strategy-distribution` | Transmitters | 5 | 5 | 0 | 1 | 5 |
| `strategy-migration` | Migrations | 13 | 12 | 0 | 3 | 10 |
| `strategy-migration` | Packages | 11 | 11 | 4 | 0 | 11 |
| `strategy-migration` | Project Duplications | 10 | 10 | 0 | 5 | 7 |
| `strategy-migration` | Migration Groups | 8 | 7 | 0 | 2 | 3 |
| `strategy-migration` | Git Service | 3 | 3 | 0 | 3 | 1 |
| `strategy-ops` | Telemetry | 58 | 58 | 0 | 12 | 33 |
| `strategy-ops` | Monitors | 42 | 38 | 6 | 26 | 28 |
| `strategy-ops` | Scripts | 21 | 20 | 0 | 8 | 13 |
| `strategy-ops` | Tasks | 8 | 8 | 0 | 2 | 2 |
| `strategy-ops` | Flows | 7 | 3 | 0 | 1 | 3 |
| `strategy-ops` | Change Journal | 5 | 5 | 0 | 3 | 0 |
| `strategy-ops` | Insight Engine | 5 | 0 | 0 | 0 | 5 |
| `strategy-ops` | Workflows | 5 | 0 | 0 | 0 | 0 |
| `strategy-ops` | HangDetector | 2 | 0 | 0 | 1 | 0 |
| `strategy-ops` | Insight Engine - Insight Engine - Insight Engine - Insight Engine - Insights | 2 | 0 | 0 | 0 | 0 |
| `strategy-ops` | Performance Statistics | 1 | 0 | 0 | 0 | 1 |
| `strategy-ops` | Insight Engine - Insight Engine - Insight Engine - Insight Engine - KPIs | 1 | 0 | 0 | 0 | 0 |
| `strategy-platform` | Authentication | 25 | 19 | 16 | 5 | 18 |
| `strategy-platform` | Misc | 9 | 2 | 0 | 0 | 0 |
| `strategy-platform` | Documentation | 8 | 8 | 0 | 0 | 0 |
| `strategy-platform` | Documentation Definition | 6 | 6 | 0 | 0 | 3 |
| `strategy-platform` | (untagged) | 6 | 0 | 5 | 0 | 6 |
| `strategy-platform` | Debug | 1 | 0 | 0 | 0 | 0 |
| `strategy-validation` | Baseline Test (Test Center) | 27 | 27 | 0 | 0 | 6 |
| `strategy-validation` | Comparison Test (Test Center) | 26 | 26 | 0 | 0 | 3 |
| `strategy-validation` | Test Center - File Store | 6 | 0 | 0 | 0 | 0 |
| `strategy-validation` | Test Center Settings | 2 | 2 | 0 | 0 | 2 |
| `strategy-validation` | Storage Sync File (Test Center) | 1 | 1 | 0 | 0 | 0 |
| `strategy-validation` | internal-baseline-result-file-controller | 1 | 1 | 0 | 0 | 1 |
