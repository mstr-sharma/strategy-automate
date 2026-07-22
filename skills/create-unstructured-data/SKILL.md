---
name: create-unstructured-data
description: Create Strategy (MicroStrategy) unstructured-data sources (nuggets) from local files — including PowerPoint decks, which are auto-converted to Markdown first. Use when the user says "create unstructured data", "upload a document/deck/PDF to Strategy", "make this file available to the Auto Agent / AI", or drops a pptx/pdf/docx/md/txt file destined for a Strategy project. Wraps POST /api/nuggets?type=unstructuredData plus status polling via scripts/create_unstructured.py and the stdlib PPTX text extractor scripts/pptx_to_md.py.
---

# Create Unstructured Data (Nuggets)

Turn a local document into a Strategy **unstructured-data nugget** so AI surfaces
(Auto Agent, chat, question answering) can ground on it. Doc reference:
`rest-api-docs → common-workflows → analytics → unstructured-data-api`.

## Accepted inputs

| Input | Handling | API `fileType` |
|---|---|---|
| `.pdf` | direct upload | 0 |
| `.docx` | direct upload | 1 |
| `.md` / `.markdown` | direct upload | 3 |
| `.txt` | direct upload | 4 |
| `.eml` | direct upload | 5 |
| `.pptx` / `.potx` | **auto-converted to Markdown** (`pptx_to_md.py`, stdlib-only), then uploaded as fileType 3 | — |

PowerPoint is NOT accepted by the API — conversion is mandatory, not optional.
`.ppt` (legacy binary) is not convertible by the stdlib extractor; ask the user to
re-save as `.pptx` or export text another way.

## Environment / prerequisites

- Standard env vars: `MSTR_BASE`, `MSTR_USER`, `MSTR_PASSWORD`, `MSTR_PROJECT_ID`
  (or `MSTR_PROJECT_NAME`), `MSTR_DEST_FOLDER_ID` (destination folder for the nugget).
- The nuggets API family ships in recent Strategy ONE releases (docs say April 2026+).
  **Verify before promising:** `build_mosaic.py openapi-search "nugget"` must show
  `/api/nuggets`. Most nugget endpoints are `visibility: internal` — fetch
  `{Library}/api/openapi.yaml?visibility=all` to see the full set
  (`/{id}`, `/{id}/file`, `/{id}/categories`, `/status/query`, `/{id}/deleteRequest`, `/orphans`).

## One-shot workflow

```bash
cd "$REPO"
python3 skills/create-unstructured-data/scripts/create_unstructured.py DECK.pptx \
    [--notes] [--title "Doc Title"] [--name "display-name.md"] \
    [--folder-id <ID>] [--no-poll] [--poll-timeout 120]
```

What it does: (pptx only) convert to Markdown alongside the source → login →
resolve project → multipart POST `/api/nuggets?type=unstructuredData` with
`file`, `fileName`, `fileType`, `fileSize`, `folderId` → parse `{"id": ...}` →
poll `POST /api/nuggets/status/query` with `{"nuggets":[{"id","projectId"}]}`
until the status record is stable → print JSON (`nuggetId`, `uploadedFile`,
raw `status` observations).

Conversion only (no upload): `python3 skills/create-unstructured-data/scripts/pptx_to_md.py DECK.pptx [-o OUT.md] [--notes]`.

## Raw REST fallback (generic hook)

`build_mosaic.py api-call` supports multipart via `--file` / `--form`:

```bash
python3 skills/build-mosaic-model/scripts/build_mosaic.py api-call \
  --method POST --path /api/nuggets --param type=unstructuredData \
  --form fileName=doc.md --form fileType=3 --form folderId=$MSTR_DEST_FOLDER_ID \
  --file file=/path/to/doc.md
```

Related maintenance endpoints (same family, use `api-call`):
`GET /api/nuggets/{id}` (name/file/status/uploadedTime — the quick existence check),
`PUT /api/nuggets/{id}` (re-upload/replace file), `GET /api/nuggets/{id}/file`
(download), `GET /api/nuggets/{id}/categories`, `POST /api/nuggets/orphans`.

## Gotchas (tenant-verified 2026-07-22, Strategy ONE Cloud)

- The create call returns **HTTP 200 with `{"id": "<32-hex>"}`** on the observed
  tenant even though the spec declares 202. Treat any 2xx + id as accepted.
- The session default `Content-Type: application/json` **must be dropped** for the
  multipart POST or the server rejects the body — the scripts handle this; if
  hand-rolling with requests, pass `headers={"Content-Type": None}`.
- `X-MSTR-ProjectID` is required — the nugget lives in a project folder.
- `status` is a **string**, not the spec's `nuggetStatus` integer. Observed
  lifecycle: `"indexing"` → `"ready"` (~5 s for a small Markdown file). Poll
  `status/query` (or `GET /api/nuggets/{id}`) until `ready`.
- `GET /api/nuggets/{id}/file` returns **406** against a JSON-only Accept header —
  pass `--header "Accept=*/*"` (comes back as `text/markdown` etc.).
- **Deleting a standalone nugget:** `POST /api/nuggets/{id}/deleteRequest` does NOT
  take the nugget id — it operates on an Agent's nugget *collection* (returns
  ERR006 "Content Ids are empty" / 404 on a nugget id). Use the objects API
  instead: `DELETE /api/objects/{nuggetId}?type=90` (nuggets are metadata
  **type 90, subtype 23042**; verified 204 → gone).
- Uploads are **content writes to the tenant** — get user confirmation on
  destination project + folder before uploading anything sensitive, and delete
  test artifacts via the objects API as above.

## Verification checklist

- Echo back: source file, converted file (if pptx), destination project + folder, nugget ID.
- Confirm the nugget shows in `status/query` (and optionally `GET /api/nuggets/{id}/file` round-trips).
- If conversion ran, spot-check the Markdown for lost content (tables, SmartArt,
  and images do not survive text extraction — SmartArt/diagram text is NOT extracted;
  charts lose their data; warn the user when a deck is visual-heavy).
