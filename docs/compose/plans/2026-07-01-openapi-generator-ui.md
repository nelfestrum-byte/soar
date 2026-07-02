# OpenAPI Connector Generator UI Implementation Plan

> [!NOTE]
> This document may not reflect the current implementation.
> See the final report for up-to-date state:
> [Final Report](../reports/openapi-generator-ui.md)

> **For agentic workers:** REQUIRED SUB-SKILL: Use compose:subagent (recommended) or compose:execute to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add web UI for generating connectors from OpenAPI specs

**Architecture:** New Vue.js page at `/generate` with spec input (textarea, file, URL), preview, and generate. Backend preview endpoint parses spec without writing files.

**Tech Stack:** Vue 3 + Composition API, FastAPI, PyYAML

## Global Constraints

- Vue 3 Composition API (`<script setup>`) — no Options API
- Inline styles (no scoped CSS) — follow existing patterns
- No external UI libraries — pure HTML/CSS
- All API calls via `ui/src/api.js` helper

---

## File Map

```
ui/src/
├── main.js                    # MODIFY — add /generate route
├── App.vue                    # MODIFY — add nav link
├── api.js                     # MODIFY — add preview + generate methods
└── views/
    └── Generate.vue           # NEW — generation page

orchestrator/api/
└── connectors.py              # MODIFY — add preview endpoints

tests/orchestrator/api/
└── test_connectors_api.py     # MODIFY — add preview tests
```

---

## Task 1: Add backend preview endpoints

**Covers:** [S4]

**Files:**
- Modify: `orchestrator/api/connectors.py`
- Modify: `tests/orchestrator/api/test_connectors_api.py`

**Interfaces:**
- Consumes: OpenAPI spec as string
- Produces: `POST /connectors/preview` and `GET /connectors/preview?url=...` endpoints

- [ ] **Step 1: Write failing tests for preview endpoint**

Add to `tests/orchestrator/api/test_connectors_api.py`:

```python
SAMPLE_SPEC_JSON = json.dumps({
    "openapi": "3.0.0",
    "info": {"title": "Test API", "version": "1.0.0"},
    "servers": [{"url": "https://api.test.com"}],
    "paths": {
        "/items": {
            "get": {
                "operationId": "listItems",
                "responses": {"200": {"description": "OK"}},
            }
        }
    },
})


@pytest.mark.asyncio
async def test_preview_connector():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post(
            "/connectors/preview",
            json={"spec": SAMPLE_SPEC_JSON},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["title"] == "Test API"
        assert len(data["endpoints"]) == 1
        assert data["endpoints"][0]["method"] == "GET"


@pytest.mark.asyncio
async def test_preview_invalid_spec():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post(
            "/connectors/preview",
            json={"spec": "not valid"},
        )
        assert r.status_code == 400
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/orchestrator/api/test_connectors_api.py::test_preview_connector -v`
Expected: FAIL — 404 or 405

- [ ] **Step 3: Add preview endpoint to connectors.py**

Add to `orchestrator/api/connectors.py` (before the `@router.post("/generate")` endpoint):

```python
@router.post("/preview")
async def preview_spec(request: Request, body: GenerateRequest):
    # Parse spec
    try:
        spec = json.loads(body.spec)
    except json.JSONDecodeError:
        try:
            spec = pyyaml.safe_load(body.spec)
        except Exception as exc:
            raise HTTPException(status_code=400, detail="Invalid spec format") from exc

    if not isinstance(spec, dict):
        raise HTTPException(status_code=400, detail="Invalid spec format: must be a mapping")

    if "openapi" not in spec:
        raise HTTPException(status_code=400, detail="Not an OpenAPI spec: missing 'openapi' version")
    if "paths" not in spec:
        raise HTTPException(status_code=400, detail="Not an OpenAPI spec: missing 'paths' section")

    # Extract endpoints
    endpoints = []
    for path, path_item in spec.get("paths", {}).items():
        for method in ["get", "post", "put", "delete", "patch"]:
            if method in path_item:
                op = path_item[method]
                endpoints.append({
                    "method": method.upper(),
                    "path": path,
                    "operationId": op.get("operationId", ""),
                })

    # Extract auth
    auth = []
    security_schemes = spec.get("components", {}).get("securitySchemes", {})
    for name, scheme in security_schemes.items():
        auth.append({"type": scheme.get("type", ""), "name": name})

    # Extract servers
    servers = [s.get("url", "") for s in spec.get("servers", [])]

    return {
        "title": spec.get("info", {}).get("title", ""),
        "version": spec.get("info", {}).get("version", ""),
        "endpoints": endpoints,
        "auth": auth,
        "servers": servers,
    }


@router.get("/preview")
async def preview_spec_url(url: str):
    import httpx
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            spec_text = resp.text
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Failed to fetch spec from URL: {exc}") from exc

    # Reuse POST preview logic
    body = GenerateRequest(spec=spec_text, name="")
    return await preview_spec(Request, body)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/orchestrator/api/test_connectors_api.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add orchestrator/api/connectors.py tests/orchestrator/api/test_connectors_api.py
git commit -m "feat: add OpenAPI spec preview endpoints"
```

---

## Task 2: Add API client methods

**Covers:** [S6]

**Files:**
- Modify: `ui/src/api.js`

**Interfaces:**
- Consumes: spec string, connector name
- Produces: `preview()`, `previewUrl()`, `generateConnector()` methods

- [ ] **Step 1: Add methods to api.js**

Add to `ui/src/api.js` (before the closing `}`):

```javascript
  preview: (spec) => request('/connectors/preview', { method: 'POST', body: JSON.stringify({ spec }) }),
  previewUrl: (url) => request(`/connectors/preview?url=${encodeURIComponent(url)}`),
  generateConnector: (spec, name) =>
    request('/connectors/generate', { method: 'POST', body: JSON.stringify({ spec, name }) }),
```

- [ ] **Step 2: Commit**

```bash
git add ui/src/api.js
git commit -m "feat: add preview and generate API client methods"
```

---

## Task 3: Create Generate.vue page

**Covers:** [S3, S5, S7]

**Files:**
- Create: `ui/src/views/Generate.vue`

**Interfaces:**
- Consumes: API client methods from Task 2
- Produces: Complete generation page

- [ ] **Step 1: Create Generate.vue**

Create `ui/src/views/Generate.vue`:

```vue
<template>
  <div>
    <h2 style="margin-bottom:12px;">Generate Connector from OpenAPI Spec</h2>

    <div class="card">
      <div style="margin-bottom:12px;">
        <label style="display:block; font-size:13px; font-weight:600; margin-bottom:4px;">Connector Name</label>
        <input v-model="connectorName" placeholder="my_api" style="width:300px;" />
      </div>

      <div style="margin-bottom:12px;">
        <label style="display:block; font-size:13px; font-weight:600; margin-bottom:4px;">OpenAPI Spec (JSON or YAML)</label>
        <textarea
          v-model="spec"
          placeholder="Paste your OpenAPI spec here..."
          style="width:100%; min-height:300px; font-family:monospace; font-size:12px; padding:8px; border:1px solid #ddd; border-radius:4px; resize:vertical; tab-size:2;"
        ></textarea>
      </div>

      <div style="display:flex; gap:12px; margin-bottom:12px; flex-wrap:wrap; align-items:center;">
        <div>
          <label style="font-size:13px; font-weight:600;">Or upload file:</label>
          <input type="file" accept=".json,.yaml,.yml" @change="handleFileUpload" style="margin-left:8px;" />
        </div>
        <div style="display:flex; gap:8px; align-items:center;">
          <label style="font-size:13px; font-weight:600;">Or load from URL:</label>
          <input v-model="specUrl" placeholder="https://example.com/api.yaml" style="width:300px;" />
          <button class="btn btn-primary" @click="loadFromUrl" :disabled="!specUrl || loadingUrl">
            {{ loadingUrl ? 'Loading...' : 'Load' }}
          </button>
        </div>
      </div>

      <div style="display:flex; gap:8px;">
        <button class="btn btn-primary" @click="doPreview" :disabled="!spec || previewing">
          {{ previewing ? 'Previewing...' : 'Preview' }}
        </button>
        <button class="btn btn-success" @click="doGenerate" :disabled="!spec || !connectorName || generating">
          {{ generating ? 'Generating...' : 'Generate' }}
        </button>
      </div>
    </div>

    <div v-if="error" class="error" style="margin-top:12px;">{{ error }}</div>

    <div v-if="preview" class="card" style="margin-top:12px;">
      <h2 style="margin-bottom:8px;">Preview</h2>
      <div style="font-size:13px; margin-bottom:8px;">
        <strong>{{ preview.title }}</strong> v{{ preview.version }}
      </div>
      <div v-if="preview.servers.length" style="font-size:13px; margin-bottom:8px; color:#666;">
        Server: {{ preview.servers[0] }}
      </div>
      <div v-if="preview.auth.length" style="font-size:13px; margin-bottom:8px; color:#666;">
        Auth: <span v-for="(a, i) in preview.auth" :key="i">{{ a.type }} ({{ a.name }})<span v-if="i < preview.auth.length - 1">, </span></span>
      </div>
      <table style="margin-top:8px;">
        <tr><th>Method</th><th>Path</th><th>Operation ID</th></tr>
        <tr v-for="(ep, i) in preview.endpoints" :key="i">
          <td><span class="badge" :class="methodBadge(ep.method)">{{ ep.method }}</span></td>
          <td style="font-family:monospace; font-size:12px;">{{ ep.path }}</td>
          <td style="font-size:12px; color:#666;">{{ ep.operationId || '—' }}</td>
        </tr>
      </table>
    </div>

    <div v-if="result" class="card" style="margin-top:12px;">
      <h2 style="margin-bottom:8px; color:#2e7d32;">✓ Connector "{{ result.name }}" generated!</h2>
      <div style="font-size:13px; margin-bottom:8px;">Files created:</div>
      <ul style="font-size:13px; margin:0; padding-left:20px;">
        <li v-for="f in result.files" :key="f" style="font-family:monospace;">{{ f }}</li>
      </ul>
      <div v-if="result.warnings.length" style="margin-top:8px;">
        <div v-for="w in result.warnings" :key="w" style="color:#e65100; font-size:12px;">⚠ {{ w }}</div>
      </div>
      <router-link :to="'/connectors'" class="btn btn-primary" style="display:inline-block; margin-top:12px; text-decoration:none;">
        View Connectors →
      </router-link>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { api } from '../api.js'

const spec = ref('')
const connectorName = ref('')
const specUrl = ref('')
const preview = ref(null)
const result = ref(null)
const error = ref(null)
const previewing = ref(false)
const generating = ref(false)
const loadingUrl = ref(false)

function methodBadge(method) {
  const map = { GET: 'badge-completed', POST: 'badge-running', PUT: 'badge-pending', DELETE: 'badge-failed', PATCH: 'badge-cancelled' }
  return map[method] || ''
}

function handleFileUpload(e) {
  const file = e.target.files[0]
  if (!file) return
  const reader = new FileReader()
  reader.onload = (ev) => { spec.value = ev.target.result }
  reader.readAsText(file)
}

async function loadFromUrl() {
  loadingUrl.value = true
  error.value = null
  try {
    const data = await api.previewUrl(specUrl.value)
    // Re-fetch the raw spec for later use
    const resp = await fetch(specUrl.value)
    spec.value = await resp.text()
    preview.value = data
  } catch (e) {
    error.value = e.message
  }
  loadingUrl.value = false
}

async function doPreview() {
  previewing.value = true
  error.value = null
  try {
    preview.value = await api.preview(spec.value)
  } catch (e) {
    error.value = e.message
  }
  previewing.value = false
}

async function doGenerate() {
  generating.value = true
  error.value = null
  result.value = null
  try {
    result.value = await api.generateConnector(spec.value, connectorName.value)
  } catch (e) {
    error.value = e.message
  }
  generating.value = false
}
</script>
```

- [ ] **Step 2: Commit**

```bash
git add ui/src/views/Generate.vue
git commit -m "feat: add OpenAPI connector generator UI page"
```

---

## Task 4: Register route and nav link

**Covers:** [S5]

**Files:**
- Modify: `ui/src/main.js`
- Modify: `ui/src/App.vue`

**Interfaces:**
- Consumes: Generate.vue component
- Produces: `/generate` route and nav link

- [ ] **Step 1: Add route to main.js**

Add to `ui/src/main.js` routes array:

```javascript
  { path: '/generate', component: () => import('./views/Generate.vue') },
```

- [ ] **Step 2: Add nav link to App.vue**

Add to `ui/src/App.vue` nav (after connectors link):

```html
<router-link to="/generate">Generate</router-link>
```

- [ ] **Step 3: Commit**

```bash
git add ui/src/main.js ui/src/App.vue
git commit -m "feat: register /generate route and nav link"
```

---

## Task 5: Run tests and verify

**Covers:** [S8]

**Files:**
- None (verification only)

- [ ] **Step 1: Run backend tests**

Run: `python -m pytest tests/orchestrator/api/test_connectors_api.py -v`
Expected: All tests PASS

- [ ] **Step 2: Run linter**

Run: `ruff check orchestrator/api/connectors.py`
Expected: No errors

- [ ] **Step 3: Verify UI builds**

Run: `cd ui && npm run build`
Expected: Build succeeds

- [ ] **Step 4: Final commit if needed**

If any fixes were needed:
```bash
git add -A
git commit -m "fix: lint and build fixes for OpenAPI generator UI"
```
