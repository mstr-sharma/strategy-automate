---
name: strategy-admin
description: Administer a Strategy (formerly MicroStrategy) environment over REST — users and user groups, security roles, privileges, SCIM provisioning, per-user API tokens, multi-tenant (tenant partitioning), license audit and compliance, vault connections, project settings and load status, and Intelligence Server / Library server settings (CORS and trusted origins, cookies, auth modes). Use it for "create users", "duplicate a user", "add user to group", "disable a user", "offboard", "assign security role", "grant privilege", "revoke privilege", "who has this role", "enable SCIM", "SCIM token", "API token for a service account", "tenant", "license audit", "compliance", "server settings", "project settings", "CORS", "allowed origins", "vault". Every call goes through the spec-validated strategy_api.py: reads first, writes are dry runs until --yes.
---

# Strategy administration

Identity, access and environment settings for a Strategy environment, driven through `strategy_api.py`. Sign-in and the generic find → describe → dry run → `--yes` loop are in `skills/strategy-platform/SKILL.md`; this skill adds the admin operations, their bodies and the guard rails. Most operations need an administrator: `describe` names the privilege an operation requires (`DssXmlPrivilegesUseUserManager`, `…UseSecurityRoleManager`, `…AdministerEnvironment`, `…ConfigureServerBasic`).

## Scope

Owned API areas (`strategy_api.py ops --tag strategy-admin`):
- **Identity:** User Management (users, groups, memberships, addresses, quotas, merge), Security Roles (with the privilege catalog), Privilege Management (`bulkUpdate`), SCIM, IAM (identity-provider configurations, internal), Multi Tenant.
- **Environment:** System Administration (I-Server and Library settings, auth modes, CORS, cookies, trust relationships, LDAP import, logging, fences, search engine, AI and collaboration server links), Configuration / Configurations / Client Configurations (mostly internal), License, Vault Connection Management, Emails, Notifications, Microsoft Teams App, Desktops, URL Scan.
- **Projects and locale:** Projects (settings, load-on-startup, locks, status message, quotas, warehouse execution settings), Preferences, Languages, Timezones, Applications, Scope Filters.

Route elsewhere: semantic models, security filters, datasources → `build-mosaic-model` (plan with `strategy-data-modeling`); reports, dashboards, Library publications, object ACLs, certification, cubes → `strategy-content`; subscriptions, schedules, contacts → `strategy-distribution`; monitors, caches, project load/unload, user connections, telemetry, change journal → `strategy-ops`; packages, migrations, project duplication → `strategy-migration`; agents and MCP readiness → `strategy-ai`; your own sign-in and API token → `strategy-platform`.

## How to work

```bash
API="python3 skills/strategy-platform/scripts/strategy_api.py"
$API ops --tag strategy-admin --search "security role"      # add --internal to include hidden operations
$API describe updateMembersSecurityRole                     # parameters, body skeleton, required privilege
```

1. Sign in as an administrator (`skills/strategy-platform/SKILL.md`; an `sso` sign-in waits for the human to click Allow). A 403 means a missing privilege — `describe` names it; `$API call getUserPrivilegeInfo` lists yours.
2. Resolve names to IDs with reads first; names are not unique, so write commands carry IDs only.
3. `describe` before every call. The operation IDs and parameter names below were copied from `describe` against the 2026 spec — re-check after an upgrade.
4. Dry-run every write (no `--yes`), show the user the printed request, then re-run with `--yes`. Keep body files in a scratch directory, never in the repo.
5. Read back after each write with the read listed in the workflow. `207` means partial success: read which keys failed.
6. Delete what you created for a test (user, group, role, tenant, vault) — test users only if this session created them.
7. A response that carries a secret (API token, SCIM bearer token) goes to a file: `--out <new file>` creates it `0600` and prints only the key names. Never print or paste the file.

## Workflows

Placeholders: `<P>` project, `<U>` user, `<G>` group, `<R>` security role, `<T>` tenant, `<V>` vault (all 32-hex IDs); `<node>` an I-Server node name (`getClusterNodes`, strategy-ops).

### 1. Users and groups: find, create, duplicate, membership
```bash
$API call getUsers -p nameBegins=<prefix> -p limit=50             # or -p abbreviationBegins=<login-prefix>
$API call getUser -p id=<U>
$API call getUserParents -p id=<U>                                 # direct groups
$API call getUserGroups -p nameBegins=<prefix>
$API call getUserGroupMembers_1 -p id=<G> -p flatMembers=true -p limit=-1
$API call createUser_1 -p sourceUserId=<template-U> --body '{"username":"<login>","fullName":"<Full Name>"}'
$API call createUserGroup --body '{"name":"<group>","description":"<purpose>","members":["<U>"]}'
$API call updatePartialUser -p id=<U> --body '{"operationList":[{"op":"add","path":"/memberships","value":["<G>"]}]}'
$API call updatePartialUser_1 -p id=<G> --body '{"operationList":[{"op":"remove","path":"/members","value":["<U>"]}]}'
```
- Rosters: `build_mosaic.py resolve-users --file users.csv`, then `create-users --file users.csv` (dry run; `--yes` creates, `--source-user-id` duplicates). Its default password comes from `MSTR_NEW_USER_PASSWORD`, which the human sets.
- `sourceUserId` copies an account: use a template account, never a real person's. SSO and LDAP users get no `password`.
- `searchTerm` does not filter users — use the `…Begins` parameters. Some tenants answer `getUsers` with `{}` even for admins: resolve through `resolve-users`, or the `owner` of objects the person owns (`doQuickSearch`).

### 2. Offboard: disable, force a password change, delete, merge
```bash
$API call updatePartialUser -p id=<U> --body '{"operationList":[{"op":"replace","path":"/enabled","value":false}]}'
$API call updatePartialUser -p id=<U> --body '{"operationList":[{"op":"replace","path":"/requireNewPassword","value":true}]}'
$API call doQuickSearch --project <P> -p owner.id=<U> -p limit=50  # what they own, before any delete
$API call deleteUser -p id=<U> -p userComments="<ticket>"          # only on explicit request
$API call mergeUsersAndGroups --body '{"sourceIds":["<U duplicate>"],"destinationId":"<U keep>","type":"user"}'
$API call getMergeStatus -p batch=<jobId>
```
- Disabling is the default offboarding step; delete only when asked, after the ownership check.
- Setting a password value is the human's step: the dry run echoes the body, so never build, print or send a body that holds a password.
- A merge folds the source accounts into the destination (`mergeOptions` picks roles, security filters, connection mappings, schedules) and cannot be undone.

### 3. Security roles: create, add privileges, assign per project
```bash
$API call getSecurityRoles -p includePrivileges=true
$API call getServerPrivilege                                       # privilege id <-> name catalog
$API call getSecurityRolesInProject -p projectId=<P>               # who holds which role in a project
$API call createSecurityRole --body '{"name":"<role>","description":"<purpose>","privileges":[{"id":"<privId>","name":"<privilege name>"}]}'
$API call updatePartialSecurityRole -p id=<R> --body '{"operationList":[{"op":"addElement","path":"/privileges","value":[{"id":"<privId>","name":"<privilege name>"}]}]}'
$API call updateMembersSecurityRole -p id=<R> --body '{"operationList":[{"op":"addElement","path":"/members","value":{"projectId":"<P>","memberIds":["<U or G>"]}}]}'
$API call getSecurityRoleMembers -p id=<R> -p projectId=<P>        # read back
$API call getUserSecurityRoles -p userId=<U> -p projectId=<P>      # groups: getUserSecurityRoles_1 -p id=<G>
```
- Roles are assigned per project; `removeElement` revokes. Send `/members` and `/privileges` changes in separate requests.
- There is no `POST /api/users/{id}/securityRoles`: membership changes go through the role.

### 4. Privileges: grant, revoke, replace in bulk
```bash
$API call bulkUpdatePrivileges --body '{"operation":"grant","targetPrivileges":[<privId>],"userGroups":["<G>"],"changeJournal":{"userComments":"<ticket>"}}'
$API call bulkUpdatePrivileges --body '{"operation":"revoke","sourcePrivileges":[<privId>],"users":["<U>"],"securityRoles":["<R>"]}'
$API call getUserPrivileges -p id=<U> -p privilege.level=server    # or -p projectId=<P>
$API call getUserGroupPrivileges -p id=<G> -p projectId=<P>
```
- `grant` adds `targetPrivileges`, `revoke` removes `sourcePrivileges`, `replace` does both. The response is per object and one failure does not stop the rest: read every row.
- Take privilege IDs from `getServerPrivilege`, matched by name — never from memory. Configuration-level privileges cannot go through a security role: grant those to users or groups.
- Prefer groups and roles over per-user grants. Grants that arrive through a project security role show as `isUserLevelAllowed: false` plus per-project `isAllowed` in the signed-in user's `getUserPrivilegeInfo`.

### 5. Projects: status, load, settings
```bash
$API call getProjects_1                                            # listed is not loaded (status: EnumDSSXMLProjectStatus)
$API call getProjectStatusOnAllNodes -p projectId=<P>              # per-node load state (Monitors; load/unload: strategy-ops)
$API call getProjectLoadSettings                                   # nodes each project loads on at startup
$API call patchProjectLoadSettings --body '{"operationList":[{"op":"replace","path":"/projects/<P>/nodes","value":["<node>"]}]}'
$API call getServerSettingProperties -p projectId=<P>              # setting keys, types, limits
$API call getServerSettings_3 -p projectId=<P>
$API call setServerSettings_2 -p projectId=<P> --body '{"<settingKey>":{"value":"<new value>"}}'
$API call updateProjectStatusMessage -p projectId=<P> --body '{"enabled":true,"showOnTop":true,"message":"<html>"}'
$API call queryProjectLock -p projectId=<P>
```
- `setServerSettings_2` (PATCH) changes only the keys sent; `setAllServerSettings` (PUT) replaces every setting — avoid it.
- A project that is listed but not loaded answers project calls with iServerCode `-2147209151`: surface it, do not retry.

### 6. Server and Library settings, CORS
```bash
$API call getIserverSettingsProperties
$API call getIserverSettings
$API call setIserverSettings --body '{"<settingKey>":{"value":"<new value>"}}'      # PATCH: only the keys sent
$API call getRestServerSettings                                  # Library: auth modes, collaboration, AI server, I-Server pool
$API call getCookieInfo
$API call getLibraryConfigurations                               # internal: configOverride entries with restartRequired
$API call updateSecuritySettings --body '{"allowAllOrigins":false,"allowedOrigins":["https://<app origin>"]}'
```
- CORS: `strategy_auth.py methods` warns when the Library echoes any `Origin` with `Access-Control-Allow-Credentials: true` (seen on a cloud tenant): any site a signed-in user visits can then read their session. Fix it only on request — `allowAllOrigins: false` plus an explicit allowlist of embedding hosts, and `http://127.0.0.1:8753` only if the team uses the repo's `sso` handoff. Never send `secretKey`. Verify by re-running `methods`. If `restartRequired`, a Library restart (`restartLibraryServer`, internal) interrupts every user — confirm first.
- `updateAuthSettings` (login modes) and `updateCookieSettings` can lock users out or break SSO and MCP (MCP needs `SameSite=None` + `Secure`): change them only when asked, keeping a working admin sign-in.

### 7. SCIM provisioning and API tokens
```bash
$API call getScimConfig                                                        # internal; bearer shown as prefix + expiry
$API call updateScimConfig --body '{"enabled":true}'                           # internal; PUT
$API call generateBearerToken --body '{"duration":<n>}' --yes --out <file>      # internal; the token is in the response
$API call getApiToken -p userId=<U>                                            # metadata only, no secret
$API call createApiToken --body '{"userId":"<U>","lifeTimeInMinutes":<n>}' --yes --out <file>
$API call revokeApiToken -p userId=<U>
```
- The identity provider calls `/api/scim/v2/Users|Groups` with the bearer token (spec security scheme `SCIM Bearer Token`). `strategy_api.py` sends a REST session, which those endpoints do not accept: verify provisioning with `getUsers` / `getUserGroups`. SCIM filtering supports `userName eq` / `groupName eq` only.
- A user has one API token: creating one replaces the old token and ends sessions that used it — check `getApiToken` first. API tokens are in the Authentication area (`strategy-platform`); for your own scripts use `strategy_auth.py login --save-api-token`.
- Hand token files to the human and delete them after the hand-off.

### 8. License audit and compliance
```bash
$API call checkLicenseAudit --yes                 # POST that starts an audit job; changes nothing
$API call checkLicenseAuditResult
$API call checkLicenseCompliance --yes
$API call checkLicenseComplianceStatus            # poll until done, then:
$API call checkComplianceResult
$API call getLicense -p nodeName=<node>
$API call getLicenseHistory -p nodeName=<node>
$API call getLicenseAuditPrivileges -p id=<U> -p licenseProduct=SERVER_INTELLIGENCE
```
- `updateLicense` and `updateLicenseActivation` change the license key or activation: never without an explicit request. `getLicenseEntitlements` takes the license key as a header — leave it to the human.

### 9. Multi-tenant (tenant partitioning)
Enabling it is a Workstation action ("Enable Tenant-based Object Isolation", global user with "Create and manage tenants"); the spec has no REST operation for it. It permanently changes the metadata, cannot be undone, needs a metadata backup first, and stops legacy tools (Developer, Object Manager, License Manager) from connecting. Stop, explain, and let the human do it. After that:
```bash
$API call createTenant --body '{"name":"<tenant>","tenantSuffix":"<suffix>"}'   # suffix: 1-8 of [A-Za-z0-9&-], unique
$API call addTenantMembers -p tenantId=<T> --body '{"members":[{"memberId":"<G>","memberTypeValue":34}]}'
$API call getTenantData -p tenantId=<T>
$API call updateTenantSettings -p tenantId=<T> --body '{"maxUsersPerTenant":{"value":<n>}}'
$API call toggleTenant -p tenantId=<T> -p enabled=false
$API call removeTenantMembers --body '{"members":[{"memberId":"<U>","memberTypeValue":34}]}'
```
- Users and groups are object type 34; adding a group assigns its users. Removed members are unassigned until added to another tenant. `deleteTenant` only on explicit request.

### 10. Vault connections
```bash
$API call getVaults
$API call getVault -p id=<V>
$API call getVaultConnectionStatus -p id=<V>
$API call validateVault --body @vault.json        # tests the connection; stores nothing
$API call createVault --body @vault.json          # {"name","type","authentication":{"mode"},"vaultUrl","extraConfigs"}
```
- Prefer identity-based modes (`managed-identity`, `default-iam-role`, `default-service-account`) so no secret passes through the agent; a body that holds keys is written by the human. Never call `getVaultSecrets` or `getVaultSecrets_1` — they return secret values.

## Safety rules

- Stop and get explicit confirmation, naming the target IDs, before anything irreversible or lockout-prone: enabling multi-tenancy, `deleteTenant`, `deleteUser`, `deleteUserGroup`, `mergeUsersAndGroups`, `deleteSecurityRole`, license key or activation changes, revoking privileges or roles from administrators or from yourself, `updateAuthSettings`, `updateSecuritySettings`, `updateCookieSettings`, `deleteProject`, `deleteUnusedManagedObjects`, a Library restart.
- Prefer disabling users to deleting them; prefer groups and roles to per-user grants.
- Never enter, generate, print or log a credential — passwords, API tokens, SCIM bearer tokens, vault secrets, license keys, `secretKey`, client secrets. They come from env vars, the OS keychain or a file the human writes, never from command-line flags.
- Auth, CORS, cookie, SCIM and identity-provider settings change only when the user asks for that change.
- Internal operations (`"internal": true` in `describe`; `call` prints a warning) are not part of the public contract: say so when a workflow depends on one, and re-check after upgrades.
- `sendEmails` and `sendPushNotification` message people: confirm recipients and text first.
- Fill `changeJournal.userComments` / `userComments` wherever an operation takes one.

## Field notes

- `memory/reference_strategy_admin_platform.md` — admin lanes and their endpoint families; read settings, patch only the keys you mean.
- `memory/reference_strategy_authentication.md` — login modes, API tokens (one per user), CORS hygiene, SCIM / JWT / trusted auth.
- `memory/reference_strategy_project_loading.md` — listed is not loaded (`-2147209151`), the load/unload calls, the session cap.
- `memory/reference_mosaic_acl.md` — object ACL rights bits (browse 1 … execute 128; view 197, modify 221, full 255); ACLs are not privileges.
- `memory/feedback_mosaic_identity_token_privilege_downgrade.md` — project-level vs user-level grants (`isUserLevelAllowed`) and the `8004cb09` 403.
- `memory/reference_strategy_task_catalog.md` — request-to-endpoint routing, incl. the governance rows.
- `memory/reference_strategy_automation_coverage.md` — coverage levels; this skill covers proposed skill 5 (identity admin) and the license part of 6.
- `memory/feedback_mosaic_gotchas.md` — `getUsers` returning `{}` on locked-down tenants.
- `memory/reference_strategy_error_codes.md` — grep any 4xx/5xx code first.
- Official: REST docs `common-workflows/administration/` (user management, security roles, server-level privileges, licensing); product help Workstation `config_lib_server_scim.htm`, `tenant_partitioning.htm`; mstrio-py `users_and_groups`, `access_and_security`, `server`.

## Status

- Exercised live, per notes: user duplication with `sourceUserId` (2026-04 admin run); the CORS echo detection in `strategy_auth.py methods`; the unloaded-project and session-cap symptoms; `getUsers` returning `{}`.
- Spec-verified only (`describe` plus an offline dry run against the 2026 spec, bodies cross-checked with mstrio-py and the REST docs): everything else here — roles, `bulkUpdatePrivileges`, project and server settings, the CORS fix, SCIM, API tokens for other users, license audit, multi-tenant, vaults. Record the first live run of each in the matching memory note.
