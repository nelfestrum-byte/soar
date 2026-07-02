# OpenAPI Connector Generator UI — Design Spec

> [!NOTE]
> This document may not reflect the current implementation.
> See the final report for up-to-date state:
> [Final Report](../reports/openapi-generator-ui.md)

## [S1] Problem

The OpenAPI connector generator has a working backend (`POST /connectors/generate`) but no UI. Users must call the API directly via curl or scripts. We need a web interface for non-technical users to generate connectors from OpenAPI specs.

## [S2] Solution Overview

New Vue.js page at `/generate` with:
- Spec input (textarea, file upload, URL fetch)
- Connector name field
- Preview endpoint (parse spec, show endpoints list)
- Generate button (create connector files)
- Result display (created files + link to connector)

## [S3] UI Components

### Page Layout

```
┌─────────────────────────────────────────────────────┐
│ Generate Connector from OpenAPI Spec                │
├─────────────────────────────────────────────────────┤
│                                                     │
│ Connector Name: [my_api________]                    │
│                                                     │
│ ┌─ Spec Input ─────────────────────────────────┐   │
│ │ [Paste JSON/YAML here...]                    │   │
│ │                                              │   │
│ │ Or: [Choose File]  [Load from URL: ________] │   │
│ └──────────────────────────────────────────────┘   │
│                                                     │
│ [Preview] [Generate]                                │
│                                                     │
│ ┌─ Preview ────────────────────────────────────┐   │
│ │ Endpoints found:                             │   │
│ │   GET /pets — listPets                       │   │
│ │   POST /pets — createPet                     │   │
│ │   GET /pets/{petId} — getPet                 │   │
│ │                                              │   │
│ │ Auth: API Key (X-API-Key)                    │   │
│ │ Server: https://api.petstore.com/v1          │   │
│ └──────────────────────────────────────────────┘   │
│                                                     │
│ ┌─ Result ─────────────────────────────────────┐   │
│ │ ✓ Connector "petstore" generated!            │   │
│ │                                               │   │
│ │ Files created:                                │   │
│ │   • petstore/petstore.py                     │   │
│ │   • petstore/__init__.py                     │   │
│ │   • petstore/petstore.example.yml            │   │
│ │                                               │   │
│ │ [View Connector →]                            │   │
│ └──────────────────────────────────────────────┘   │
│                                                     │
└─────────────────────────────────────────────────────┘
```

### State

```javascript
const spec = ref('')           // Raw spec text
const connectorName = ref('')  // snake_case name
const specUrl = ref('')        // URL to fetch spec from
const preview = ref(null)      // Parsed spec preview {endpoints, auth, server}
const generating = ref(false)  // Generation in progress
const result = ref(null)       // Generation result {name, files, warnings}
const error = ref(null)        // Error message
const loadingUrl = ref(false)  // URL fetch in progress
```

### Interactions

1. **File upload**: `<input type="file" accept=".json,.yaml,.yml">` → reads file → sets `spec`
2. **URL fetch**: Button → `GET /connectors/preview?url=...` → sets `spec` and `preview`
3. **Preview**: Button → `POST /connectors/preview` with spec → sets `preview`
4. **Generate**: Button → `POST /connectors/generate` with spec + name → sets `result`

## [S4] Backend Changes

### New endpoint: `POST /connectors/preview`

Parses OpenAPI spec and returns summary without writing files.

**Request:**
```json
{"spec": "<raw spec string>"}
```

**Response:**
```json
{
  "title": "Petstore",
  "version": "1.0.0",
  "endpoints": [
    {"method": "GET", "path": "/pets", "operationId": "listPets"},
    {"method": "POST", "path": "/pets", "operationId": "createPet"}
  ],
  "auth": [{"type": "apiKey", "name": "X-API-Key"}],
  "servers": ["https://api.petstore.com/v1"]
}
```

### New endpoint: `GET /connectors/preview`

Fetches spec from URL and returns parsed preview.

**Request:** `GET /connectors/preview?url=https://example.com/api.yaml`

**Response:** Same as POST preview.

## [S5] File Changes

```
ui/src/
├── main.js                    # Add /generate route
├── App.vue                    # Add nav link
├── api.js                     # Add preview() and generateConnector() methods
└── views/
    └── Generate.vue           # NEW — generation page

orchestrator/api/
└── connectors.py              # Add preview endpoints
```

## [S6] API Client Methods

```javascript
// api.js additions
preview: (spec) => request('/connectors/preview', { method: 'POST', body: JSON.stringify({ spec }) }),
previewUrl: (url) => request(`/connectors/preview?url=${encodeURIComponent(url)}`),
generateConnector: (spec, name) => request('/connectors/generate', { method: 'POST', body: JSON.stringify({ spec, name }) }),
```

## [S7] Error Handling

| Error | Display |
|---|---|
| Invalid spec format | "Invalid JSON or YAML" |
| Missing openapi field | "Not an OpenAPI 3.x spec" |
| Missing paths | "No endpoints defined" |
| Name already exists | "Connector already exists" |
| URL fetch failed | "Failed to fetch spec from URL" |
| Generation failed | Backend error message |

## [S8] Testing

- Unit: API client methods
- Integration: Page renders, form submits, preview displays, generate creates connector
- Manual: Upload file, paste spec, load from URL, preview, generate
