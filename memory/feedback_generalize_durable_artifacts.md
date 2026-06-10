---
name: Durable artifacts must be tenant- and use-case-agnostic
description: All skills, memories, scripts, helpers, and examples in this repo must be written so they apply regardless of the specific tenant, database engine, schema, domain, user, or source file. Concrete values belong in env vars, CLI flags, user-supplied inputs, or dated capture files under `captures/` — never hardcoded into durable artifacts.
type: feedback
---

**Rule.** Every durable artifact in this repo — skills (`*/SKILL.md`), memory files (`memory/*.md`), Python helpers (`skill/scripts/*.py`), runnable examples, dictionary/ERD templates, shell snippets — must read as a general-purpose procedure that works against *any* Strategy tenant, *any* DB engine, *any* schema, *any* domain, and *any* user identity. A reader who has never seen this repo should be able to apply the artifact to their own environment without editing its text.

**Why:** this repo's premise (see `AGENTS.md`) is a harness- and tenant-agnostic automation brain. Tenant-specific values in durable artifacts cause four concrete failures:

1. **Security / policy.** Tenant IDs, user IDs, email addresses, model IDs, and report IDs are non-public. Committing them violates the `AGENTS.md` rule ("never commit credentials, tenant IDs, raw tenant payloads") and leaks PII / customer identifiers into git history.
2. **Staleness.** Hardcoded IDs rot when the object is renamed, moved, or deleted. A memory claiming "schedule `FF7BB…` is Monday Morning" is wrong the moment the schedule is edited.
3. **Reader confusion.** A rule titled "Studio publish stall" reads as a Studio-only quirk; the same bug fires on any Strategy ONE Cloud tenant under the same load. Tenant-prefixed rules get dismissed on other tenants that actually have the same bug.
4. **Lock-in.** A build script that assumes Postgres + Snowflake cannot be reused on Oracle + BigQuery without a rewrite, even when the endpoint surface is identical.

**How to apply.** Before creating or editing any durable artifact, run this checklist:

1. **Scan for concrete identifiers.** Grep the draft for:
   - **Tenant / environment**: hostnames (`<tenant>.customer.cloud.microstrategy.com`, `<tenant>.strategy.com`, `env-*`, `tutorial.*`), project names (`<Project Name>`, `MicroStrategy Tutorial`, `<Folder Path>/…`).
   - **Warehouse**: DB instance names (any customer-branded proper noun — `<Team> Postgres`, `<Division> Snowflake`, `Snowflake Prod`), schema names (`<SCHEMA>`, `public`, `SALES`), table names (`<FACT_TABLE>`, `<DIM_TABLE>`, `<event_fact>`).
   - **User / PII**: usernames, real full names (first-last or last-first), email addresses (corporate or personal), user IDs.
   - **Object IDs**: 32-hex strings for models, reports, folders, schedules, addresses, facts, metrics, filters — anything minted per-tenant.
   - **Domain entities**: customer-specific business-entity names (`<customer-brand>`, `<product-brand>`), product names, internal project codenames, industry-specific jargon (`<industry-term>` — e.g., a compute-unit, a financial-instrument, a clinical-trial-phase, a SKU-class) that signals the artifact was written for one vertical.
   - **Developer identity / git infrastructure**: personal / work GitHub handles (`<user>/strategy-*`), SSH host aliases (`github-<org>-<user>`), SSH key filenames (`id_ed25519_<org>_<user>.pub`), remote URLs for personal mirrors, `git config user.name` / `user.email` values, any reference to "my fork" or "my mirror". These belong in the operator's local `~/.ssh/config` and `git config --local`, not in the repo.
2. **Replace with placeholders or parameters.** Options, in preference order:
   - Env var or CLI flag (`$MSTR_BASE`, `--instance`, `--dest-folder`)
   - User-supplied dictionary / ERD / config file
   - Angle-bracket placeholder in prose (`<tenant-base>`, `<project-id>`, `<postgres-instance>`, `<your-schema>.<your-fact-table>`)
   - Named variable in a code snippet (`ATTR_ID = "..."` with a comment to fill in)
3. **Keep examples generic.** If a concrete example makes the rule readable, use a public, well-known schema (TPC-H, TPC-DS, Northwind) or a clearly invented name (`SALES.ORDERS`, `<company>_<dataset>`). Never use your current customer, your personal project, or the last tenant you happened to run against.
4. **Present tenant observations as tenant-family observations.** Wrong: *"publish fails on `<tenant>.strategy.com`"*. Right: *"publish fails on Strategy ONE Cloud tenants in this iServer version family — first observed on `<tenant>` during `<capture-date>`"*. The rule should generalize; the dated observation lives in the tenant-observation section (or in `captures/`), not in the rule title.
5. **Route dated, tenant-specific state to `captures/`.** Raw REST payloads, session logs, reproduction transcripts, and field-study inventories are valuable but not durable rules. They go in `captures/<YYYY-MM-DD>-<topic>/`. Extract any durable lesson back into a memory with placeholders; link the memory to the capture file.
6. **Parameterize scripts end-to-end.** Helper scripts and code snippets must read all tenant values from env vars or CLI flags. No `MSTR_BASE=https://<tenant>.strategy.com/...` default in the source. Skill/SKILL.md snippets must show `$MSTR_BASE` rather than a concrete URL.
7. **Self-audit before commit.** Run `git diff | grep -Ei "(customer\\.cloud|\\.strategy\\.com|[A-F0-9]{32}|<your-full-name>|<your-email>)"` before staging. Hits = stop and rewrite.

**Scope — this rule applies to:**

- `memory/*.md`
- Every `SKILL.md` (top-level skills and future additions)
- Every `skill/scripts/*.py` and helper script
- Every example, template, dictionary, ERD, or config committed to the repo
- Every `README.md`, `AGENTS.md`, `CLAUDE.md`, and other harness entry points
- Every test fixture (fixtures must use synthetic or public-benchmark data)

**Scope — this rule does NOT apply to:**

- `.env` / `.env.local` / `.env.example` — those are templates and explicitly excluded from commits
- `captures/<date>/` — raw captures are inherently tenant-specific; that's their job. Captures must not be referenced as if they were rules.
- Strategy platform constants that are genuinely universal across all tenants (e.g., the universal ID form `45C11FA478E745FEA08D781CEA190FE5`, documented subtype codes, documented OpenAPI paths). Call these out explicitly as "platform constant, safe to use as-is" in the artifact.

**When the check catches something already committed.** Prefer a follow-up commit that replaces the leak with placeholders plus a pointer to a new capture file. Do not rewrite git history unless the leak is an actual credential — PII and tenant IDs are addressed going forward; historical commits are left alone.

**Related:**
- `AGENTS.md` "Operating rules" — the high-level "never hardcode" rule this memory elaborates (see the "Keep every durable artifact generalizable" bullet).
- `reference_strategy_env.md` — the env-var / CLI-flag convention every script already implements.
- `captures/2026-04-22-automation-audit/` — prior audit that found similar leaks (now under captures/, since it was a dated event log rather than a durable rule).
- `feedback_mosaic_ship_bar.md` — the related rule that forbids personal names in user-facing model content (see its Cleanliness rules); same spirit, user-facing scope.
