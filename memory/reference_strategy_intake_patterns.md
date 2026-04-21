---
name: Strategy intake patterns
description: Convert user-supplied ERDs, data dictionaries, user/email lists, and legacy object update requests into safe Strategy automation workflows.
type: reference
originSessionId: local-codex-2026-04-21
---
Goal: the user should be able to drop artifacts into the workspace and ask for work in natural language. The agent turns those artifacts into a deterministic plan, resolves IDs, performs read-first preflight, writes only after targets are clear, and verifies afterward.

## Drop-in artifact map
- ERD: JSON/YAML relationship list, DBML `Ref:` lines, Mermaid `erDiagram`, SQL DDL with `REFERENCES`, or an image/PDF that the agent must read visually and convert to one of those text formats first.
- Data dictionary: JSON/YAML/CSV with table/column-level names, descriptions, metric aggregation hints, relationship overrides, and optional table descriptions.
- User/security roster: CSV/JSON/YAML rows with `id`, `username`, `email`, `name`/`fullName`, optional `groups`/`memberships`, role names, and access intent.
- Legacy object update brief: object name or ID, target environment/project, desired change, acceptance check, rollback expectation.

## Build model from ERD + dictionary
1. Inspect datasource/schema/tables with `list-datasources`, `list-namespaces`, `list-tables`, `describe-table`.
2. Convert ERD images or PDFs to a structured relationship file:
   ```json
   {"relationships":[{"parent":"CUSTOMERS.CUSTOMER_ID","child":"ORDERS.CUSTOMER_ID","relationship_table":"ORDERS","type":"one_to_many"}]}
   ```
3. Convert the data dictionary to:
   ```json
   {
     "attributes": {"CUSTOMERS.CUSTOMER_NAME": {"name": "Customer", "description": "Customer account display name."}},
     "metrics": {"ORDERS.REVENUE": {"name": "Revenue", "description": "Booked order revenue.", "function": "sum"}},
     "relationships": [],
     "tables": {"ORDERS": {"description": "Order header grain."}}
   }
   ```
4. Prefer `build-from-config` when the request is a bundle; it accepts top-level `dictionary`, `data_dictionary`, `erd`, and `erds`.
5. If the user supplies no dictionary, synthesize useful descriptions from column/table semantics before building; do not leave mechanical descriptions unless the source names are opaque.

## Users, emails, and security
- Resolve people before ACL/security writes:
  ```bash
  python3 skill/scripts/build_mosaic.py resolve-users --file users.csv
  ```
- Dry-run new user creation by default:
  ```bash
  python3 skill/scripts/build_mosaic.py create-users --file users.csv
  ```
- Execute only after review:
  ```bash
  MSTR_NEW_USER_PASSWORD='...' python3 skill/scripts/build_mosaic.py create-users --file users.csv --yes
  ```
- Expected roster columns: `username`, `fullName` or `name`, `email`, optional `groups`/`memberships`, `enabled`, `standardAuth`, `requireNewPassword`, `languageId`.
- For row-level security and ACLs, resolve users/groups to IDs first; prefer exact IDs in final write commands.

## Existing and legacy object updates
Use the read-first loop for any update to existing attributes, metrics, tables, filters, users, projects, or governance settings.
1. Find candidates:
   ```bash
   python3 skill/scripts/build_mosaic.py search-objects --name "Customer" --limit 20
   ```
2. Read the exact object definition with parseable expressions:
   ```bash
   python3 skill/scripts/build_mosaic.py get-model-object --kind legacy_attribute --object-id ATTR_ID --show-expression-as tokens --show-advanced-properties --out /tmp/customer.attr.before.json
   ```
   For Mosaic-contained objects, pass `--model-id MODEL_ID --kind attribute|fact_metric|table|filter|security_filter`.
3. Create a minimal patch JSON from the current object. Modeling Service `PATCH` replaces top-level fields, so include every top-level field you need to preserve.
4. Apply through a changeset and save the before image:
   ```bash
   python3 skill/scripts/build_mosaic.py patch-model-object --kind legacy_attribute --object-id ATTR_ID --json-file /tmp/customer.attr.patch.json --before-out /tmp/customer.attr.before.json --yes
   ```
5. Verify with a second `GET`, summarize changed fields, and record tenant-specific payload lessons in `feedback_mosaic_gotchas.md`.

## Safety defaults
- Never create/delete users, revoke access, overwrite legacy schema objects, publish packages, or change server/project settings without explicit user intent.
- For destructive changes, enumerate object IDs and ask if deletion/removal was not explicit.
- For writes driven by names, resolve names to IDs and include unresolved/ambiguous rows in the response.
- Keep passwords and temporary onboarding secrets out of memory, skills, and committed config.
