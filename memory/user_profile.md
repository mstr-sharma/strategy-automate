---
name: User profile — Strategy Sales Engineer
description: The typical operator of this repo is a Strategy (formerly MicroStrategy) Sales Engineer running demos and PoCs against customer or internal tenants. Default Claude / Codex behavior should match that persona unless overridden.
type: user
---
- Operator persona: **Strategy Sales Engineer** (or equivalent — SA, TPM, field engineer) running demos, PoCs, workshops, and internal testing against Strategy Cloud tenants.
- Primary goals: stand up **Mosaic data models** end-to-end quickly, inspect / migrate classic semantic-layer content, validate data correctness, and run administrative tasks — all scriptable and repeatable.
- Expects end-to-end working code that runs live against the tenant in `MSTR_BASE` — not pseudocode. Concrete sample calls over "here's how it might work" prose.
- Comfortable when Claude iteratively probes `/api/openapi.yaml`, discovers endpoints, and updates the skill/memory files in place — does not want brittle hardcoded paths.
- Terse updates preferred. Long essays only when the task is exploratory.
- Expects deep fluency across the Mosaic metadata model (datasources, physical/logical tables, attributes with every form type, facts, every metric shape — simple / compound / conditional / level / transformation / smart — filters, consolidations, custom groups, prompts, hierarchies, security filters / ACLs, translations, VLDB) AND the classic / project semantic-layer counterparts.
- Expects consumer-grade output on every built model — see `feedback_consumer_grade_naming.md`. Validation is part of the ship bar — see `reference_strategy_data_validation.md`.
- Credentials and tenant identity come from environment variables (`MSTR_BASE`, `MSTR_USER`, `MSTR_PASSWORD`, `MSTR_PROJECT_ID` or `MSTR_PROJECT_NAME`, `MSTR_DEST_FOLDER_ID`). Never commit or log them.
