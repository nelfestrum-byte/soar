---
feature: openapi-generator-ui
status: delivered
specs:
  - docs/compose/specs/2026-07-01-openapi-generator-ui-design.md
plans:
  - docs/compose/plans/2026-07-01-openapi-generator-ui.md
branch: main
commits: b14ddcc..625265f
---

# OpenAPI Connector Generator UI — Final Report

## What Was Built

Web interface for generating SOAR connectors from OpenAPI specifications. Users can paste JSON/YAML specs, upload files, or load from URLs. The UI provides preview (showing endpoints, auth, servers) before generating, and displays created files with links to the connector.

## Architecture

Two components:

1. **Backend Preview Endpoints** (`orchestrator/api/connectors.py`):
   - `POST /connectors/preview` — parses spec, returns endpoints/auth/servers summary
   - `GET /connectors/preview?url=...` — fetches spec from URL, returns preview

2. **Frontend Page** (`ui/src/views/Generate.vue`):
   - Spec input: textarea, file upload, URL fetch
   - Connector name field
   - Preview button → shows endpoints table
   - Generate button → creates connector files
   - Result display with file list and link to connectors page

### API Client Methods (`ui/src/api.js`)

```javascript
preview(spec)           // POST /connectors/preview
previewUrl(url)         // GET /connectors/preview?url=...
generateConnector(spec, name)  // POST /connectors/generate
```

## Usage

1. Navigate to `/generate` in the UI
2. Enter connector name (snake_case)
3. Provide OpenAPI spec via:
   - Paste JSON/YAML in textarea
   - Upload .json/.yaml file
   - Enter URL and click Load
4. Click Preview to see endpoints
5. Click Generate to create connector
6. Click "View Connectors →" to see the new connector

## Verification

- **18 backend tests** pass (preview + generate endpoints)
- **Lint clean** — ruff passes
- **UI builds** — `npm run build` succeeds
- **Manual testing** — page renders, form submits, preview displays, generate works

## Journey Log

- [lesson] Preview endpoint needed separate `PreviewRequest` model (no `name` field) to avoid 422 validation errors from `GenerateRequest`.
