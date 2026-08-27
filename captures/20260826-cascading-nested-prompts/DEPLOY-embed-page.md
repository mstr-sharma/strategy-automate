# Cascading Prompts, Three Ways — deployment guide

A single-page, customer-facing educational site with live iframe embeds of the
cascading-prompt demo objects (MicroStrategy Tutorial project on
<tenant-env>). No server-side code — one static HTML page packaged as a WAR.

## Contents

| File | Purpose |
|---|---|
| `cascading-prompts.war` | Deployable web app (index.html + WEB-INF/web.xml) |
| `webapp/` | WAR source — edit `webapp/index.html`, then run `./build-war.sh` |
| `build-war.sh` | Rebuilds the WAR after edits |
| `start.sh` | Local preview at http://localhost:8811 (no Tomcat needed) |

## Deploy to Tomcat

1. Copy `cascading-prompts.war` into the Tomcat `webapps/` directory
   (`$CATALINA_BASE/webapps/`). Tomcat auto-deploys it.
2. Browse to `https://<tomcat-host>/cascading-prompts/`.

That's it — no configuration inside the WAR.

### Where to deploy it

- **Best: the same Tomcat / domain that serves MicroStrategyLibrary.**
  The page and Library then share an origin, the session cookie stays
  first-party, and every browser works — including Safari. (On a Strategy
  Cloud environment, ask cloud ops to place the WAR next to
  `MicroStrategyLibrary.war`.)
- **Any other https Tomcat also works in Chrome/Edge**, because the Library
  server is configured for cross-origin embedding (see below). Safari and
  browsers with third-party cookies blocked need the same-domain option or the
  Embedding SDK.

## Library server prerequisites (already configured on <tenant-env>, 2026-08-27)

Library Admin → Library Server → Security Settings:

- **Allow Library embedding in other sites**: All (or list the portal origins).
- **Cookies → SameSite Attribute: None** (+ Enable Secure) — without this no
  cross-origin frame can carry the Library session.
- Optional: **Enable Partitioned** future-proofs for cookie-partitioned browsers.

Verified after the change: `Set-Cookie: … HttpOnly; Secure; SameSite=None`.

## Auto sign-in (demo convenience)

The page authenticates itself so viewers see live reports and dashboards with
**no login prompt**:

- On load, a small script calls `POST /MicroStrategyLibrary/api/auth/login` with
  a **shared demo account hardcoded in `index.html`** (search for `DEMO =`).
- Because the page is served same-origin with Library, that login sets a
  **first-party** session cookie, so all three iframes — and any same-origin API
  call — are already authenticated. The status pill shows "Connected as demo user".
- The iframes stay blank until sign-in resolves, so viewers never see a login
  screen. If auto sign-in ever fails, the pill says so and the frames fall back
  to their own login.

This is deliberate for a **shared demo environment** and makes the page trivial to
showcase. The credentials are visible in page source — fine here, never do this
with real/production credentials. For a production embed use SSO/OIDC or the
Embedding SDK (`embeddinglib.js`) instead of a stored password. To change the demo
account, edit the `DEMO = { username, password, loginMode }` line in
`webapp/index.html` and run `./build-war.sh`.

## Redeploying after an edit

Editing `webapp/index.html` (e.g. the demo credentials) means rebuilding and
re-uploading:

1. `./build-war.sh`
2. Upload `cascading-prompts.war` to Tomcat `webapps/`, overwriting the old one.
   Tomcat auto-redeploys (undeploys the old exploded folder, unpacks the new WAR).

## Viewing

- The interactive walkthrough and filter-panel replica run on captured demo data
  and need no sign-in.
- The three live embeds authenticate automatically (above). If you deploy this
  build somewhere **not** same-origin with Library, the auto sign-in cookie is
  cross-site again — use a same-domain deployment or the Embedding SDK.

## Local preview without Tomcat

```bash
./start.sh
```

Serves the same page at http://localhost:8811 (frames require an http(s)
origin — opening index.html straight from disk will not carry the session).
