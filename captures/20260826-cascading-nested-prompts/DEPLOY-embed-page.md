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

## Viewing

- Viewers need credentials for the Tutorial project on the demo environment —
  they sign in once inside any frame and all frames share the session.
- The interactive walkthrough and filter-panel replica on the page run on
  captured demo data and need no sign-in.

## Local preview without Tomcat

```bash
./start.sh
```

Serves the same page at http://localhost:8811 (frames require an http(s)
origin — opening index.html straight from disk will not carry the session).
