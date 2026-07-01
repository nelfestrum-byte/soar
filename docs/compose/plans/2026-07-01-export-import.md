# Export/Import сущностей Implementation Plan

> [!NOTE]
> This document may not reflect the current implementation.
> See the final report for up-to-date state:
> [Final Report](../reports/export-import.md)

> **For agentic workers:** REQUIRED SUB-SKILL: Use compose:subagent (recommended) or compose:execute to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Реализовать экспорт/импорт сущностей SOAR (connectors, actions, workflows) и их конфигов в zip-архив

**Architecture:** Новые API эндпоинты `/export` и `/import` в отдельном роутере `orchestrator/api/transfer.py`. UI — отдельная страница Settings с кнопками Export/Import.

**Tech Stack:** Python zipfile, FastAPI, Vue 3

---

## File Structure

**Создать:**
- `orchestrator/api/transfer.py` — API роутер для export/import
- `ui/src/views/Settings.vue` — страница настроек

**Модифицировать:**
- `orchestrator/main.py` — подключить роутер transfer
- `ui/src/App.vue` — добавить навигацию на Settings
- `ui/src/api.js` — добавить методы export/import

---

### Task 1: Transfer API — Export endpoint

**Covers:** Export functionality

**Files:**
- Create: `orchestrator/api/transfer.py`
- Modify: `orchestrator/main.py:1-20` (добавить импорт и подключение роутера)

- [ ] **Step 1: Создать файл transfer.py с export endpoint**

```python
import io
import json
import os
import zipfile
from datetime import datetime

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

router = APIRouter(prefix="/transfer", tags=["transfer"])


@router.post("/export")
async def export_entities(request: Request):
    config = request.app.state.config
    job_manager = request.app.state.job_manager

    buffer = io.BytesIO()
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")

    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        # Collect connectors
        connectors = []
        connectors_dir = config.soar.connectors_dir
        if os.path.exists(connectors_dir):
            for entry in os.scandir(connectors_dir):
                if entry.is_dir() and not entry.name.startswith(("_", ".")):
                    py_file = os.path.join(entry.path, f"{entry.name}.py")
                    yml_file = os.path.join(entry.path, f"{entry.name}.yml")
                    if os.path.exists(py_file):
                        zf.write(py_file, f"connectors/{entry.name}/code.py")
                        connectors.append(entry.name)
                    if os.path.exists(yml_file):
                        zf.write(yml_file, f"connectors/{entry.name}/config.yml")

        # Collect actions
        actions = []
        actions_dir = config.soar.actions_dir
        if os.path.exists(actions_dir):
            for entry in os.scandir(actions_dir):
                if entry.is_file() and entry.name.endswith(".py") and entry.name != "__init__.py":
                    zf.write(entry.path, f"actions/{entry.name}")
                    actions.append(entry.name[:-3])

        # Collect workflows
        workflows = []
        workflows_dir = config.soar.workflows_dir
        if os.path.exists(workflows_dir):
            for entry in os.scandir(workflows_dir):
                if entry.is_file() and entry.name.endswith(".py") and entry.name != "__init__.py":
                    zf.write(entry.path, f"workflows/{entry.name}")
                    workflows.append(entry.name[:-3])

        # Collect state
        state = {"workflows": {}}
        for name, meta in job_manager._metas.items():
            state["workflows"][name] = "enabled" if meta.enabled else "disabled"

        zf.writestr("state.yaml", json.dumps(state, indent=2))

        # Manifest
        manifest = {
            "version": "1.0",
            "created_at": timestamp,
            "connectors": connectors,
            "actions": actions,
            "workflows": workflows,
        }
        zf.writestr("manifest.json", json.dumps(manifest, indent=2))

    buffer.seek(0)
    filename = f"soar-export-{timestamp}.zip"
    return StreamingResponse(
        buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
```

- [ ] **Step 2: Подключить роутер в main.py**

Добавить импорт и подключение в `orchestrator/main.py`:

```python
from orchestrator.api.transfer import router as transfer_router
app.include_router(transfer_router)
```

- [ ] **Step 3: Проверить что export работает**

Запустить сервер и выполнить:
```bash
curl -X POST http://localhost:8000/api/transfer/export -o export.zip
unzip -l export.zip
```

Ожидаемый результат: архив содержит `manifest.json`, `connectors/`, `actions/`, `workflows/`, `state.yaml`

- [ ] **Step 4: Commit**

```bash
git add orchestrator/api/transfer.py orchestrator/main.py
git commit -m "feat: add export endpoint for SOAR entities"
```

---

### Task 2: Transfer API — Import endpoint

**Covers:** Import functionality

**Files:**
- Modify: `orchestrator/api/transfer.py`

- [ ] **Step 1: Добавить import endpoint в transfer.py**

Добавить в `orchestrator/api/transfer.py`:

```python
import shutil
from pathlib import Path

from fastapi import HTTPException, UploadFile


@router.post("/import")
async def import_entities(request: Request, file: UploadFile):
    if not file.filename.endswith(".zip"):
        raise HTTPException(status_code=400, detail="File must be a .zip archive")

    config = request.app.state.config

    content = await file.read()
    buffer = io.BytesIO(content)

    conflicts = []
    imported = {"connectors": [], "actions": [], "workflows": []}

    with zipfile.ZipFile(buffer, "r") as zf:
        # Parse manifest
        if "manifest.json" not in zf.namelist():
            raise HTTPException(status_code=400, detail="Invalid archive: missing manifest.json")

        manifest = json.loads(zf.read("manifest.json"))

        # Check conflicts
        connectors_dir = config.soar.connectors_dir
        actions_dir = config.soar.actions_dir
        workflows_dir = config.soar.workflows_dir

        for name in manifest.get("connectors", []):
            connector_dir = os.path.join(connectors_dir, name)
            if os.path.exists(connector_dir):
                conflicts.append({"type": "connector", "name": name})

        for name in manifest.get("actions", []):
            action_file = os.path.join(actions_dir, f"{name}.py")
            if os.path.exists(action_file):
                conflicts.append({"type": "action", "name": name})

        for name in manifest.get("workflows", []):
            workflow_file = os.path.join(workflows_dir, f"{name}.py")
            if os.path.exists(workflow_file):
                conflicts.append({"type": "workflow", "name": name})

        # If conflicts and not confirmed, return them
        force = request.query_params.get("force", "false").lower() == "true"

        if conflicts and not force:
            return {
                "status": "conflicts",
                "conflicts": conflicts,
                "message": f"Found {len(conflicts)} conflicts. Send force=true to overwrite.",
            }

        # Import connectors
        for name in manifest.get("connectors", []):
            connector_dir = os.path.join(connectors_dir, name)
            os.makedirs(connector_dir, exist_ok=True)

            code_path = f"connectors/{name}/code.py"
            if code_path in zf.namelist():
                zf.extract(code_path, config.soar.workflows_dir.parent)
                extracted = os.path.join(config.soar.workflows_dir.parent, code_path)
                target = os.path.join(connector_dir, f"{name}.py")
                shutil.move(extracted, target)

            config_path = f"connectors/{name}/config.yml"
            if config_path in zf.namelist():
                zf.extract(config_path, config.soar.workflows_dir.parent)
                extracted = os.path.join(config.soar.workflows_dir.parent, config_path)
                target = os.path.join(connector_dir, f"{name}.yml")
                shutil.move(extracted, target)

            imported["connectors"].append(name)

        # Import actions
        for name in manifest.get("actions", []):
            action_path = f"actions/{name}.py"
            if action_path in zf.namelist():
                zf.extract(action_path, config.soar.workflows_dir.parent)
                extracted = os.path.join(config.soar.workflows_dir.parent, action_path)
                target = os.path.join(actions_dir, f"{name}.py")
                os.makedirs(os.path.dirname(target), exist_ok=True)
                shutil.move(extracted, target)
                imported["actions"].append(name)

        # Import workflows
        for name in manifest.get("workflows", []):
            workflow_path = f"workflows/{name}.py"
            if workflow_path in zf.namelist():
                zf.extract(workflow_path, config.soar.workflows_dir.parent)
                extracted = os.path.join(config.soar.workflows_dir.parent, workflow_path)
                target = os.path.join(workflows_dir, f"{name}.py")
                os.makedirs(os.path.dirname(target), exist_ok=True)
                shutil.move(extracted, target)
                imported["workflows"].append(name)

    # Reload workflows
    from orchestrator.main import load_workflow_metas
    job_manager = request.app.state.job_manager
    scheduler = request.app.state.scheduler
    workflows = load_workflow_metas(config)
    job_manager.set_metas(workflows)
    await scheduler.reload(workflows)

    return {
        "status": "imported",
        "imported": imported,
        "conflicts_overwritten": len(conflicts) if force else 0,
    }
```

- [ ] **Step 2: Добавить UploadFile импорт**

Добавить в начало файла:
```python
from fastapi import HTTPException, UploadFile
```

- [ ] **Step 3: Проверить import работает**

```bash
# Export сначала
curl -X POST http://localhost:8000/api/transfer/export -o export.zip

# Импортировать
curl -X POST http://localhost:8000/api/transfer/import -F "file=@export.zip"

# С force
curl -X POST "http://localhost:8000/api/transfer/import?force=true" -F "file=@export.zip"
```

- [ ] **Step 4: Commit**

```bash
git add orchestrator/api/transfer.py
git commit -m "feat: add import endpoint for SOAR entities"
```

---

### Task 3: UI — Settings page

**Covers:** UI для export/import

**Files:**
- Create: `ui/src/views/Settings.vue`
- Modify: `ui/src/App.vue:4-9` (добавить навигацию)
- Modify: `ui/src/api.js` (добавить методы)

- [ ] **Step 1: Создать Settings.vue**

```vue
<template>
  <div>
    <h1>Settings</h1>

    <div class="card">
      <h2>Export</h2>
      <p>Download all entities (connectors, actions, workflows) and configs as a zip archive.</p>
      <button class="btn btn-primary" @click="doExport" :disabled="exporting">
        {{ exporting ? 'Exporting...' : 'Download Archive' }}
      </button>
      <span v-if="exportError" class="error">{{ exportError }}</span>
    </div>

    <div class="card">
      <h2>Import</h2>
      <p>Upload a previously exported archive to restore entities.</p>
      <input type="file" ref="fileInput" accept=".zip" @change="handleFile" style="display:none" />
      <button class="btn btn-primary" @click="$refs.fileInput.click()" :disabled="importing">
        {{ importing ? 'Importing...' : 'Select Archive' }}
      </button>

      <div v-if="conflicts.length" class="conflicts">
        <h3>Conflicts Found</h3>
        <ul>
          <li v-for="c in conflicts" :key="c.type + c.name">
            {{ c.type }}: <strong>{{ c.name }}</strong> (already exists)
          </li>
        </ul>
        <button class="btn btn-danger" @click="doImport(true)" :disabled="importing">
          Overwrite All
        </button>
        <button class="btn" @click="conflicts = []">Cancel</button>
      </div>

      <div v-if="importResult" class="result">
        <h3>Import Complete</h3>
        <p>Connectors: {{ importResult.imported.connectors.length }}</p>
        <p>Actions: {{ importResult.imported.actions.length }}</p>
        <p>Workflows: {{ importResult.imported.workflows.length }}</p>
      </div>

      <span v-if="importError" class="error">{{ importError }}</span>
    </div>
  </div>
</template>

<script>
import { api } from '../api'

export default {
  data() {
    return {
      exporting: false,
      exportError: '',
      importing: false,
      importError: '',
      importFile: null,
      conflicts: [],
      importResult: null,
    }
  },
  methods: {
    async doExport() {
      this.exporting = true
      this.exportError = ''
      try {
        const blob = await api.exportEntities()
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        a.download = `soar-export-${new Date().toISOString().slice(0,10)}.zip`
        a.click()
        URL.revokeObjectURL(url)
      } catch (e) {
        this.exportError = e.message
      } finally {
        this.exporting = false
      }
    },
    handleFile(e) {
      this.importFile = e.target.files[0]
      if (this.importFile) {
        this.doImport(false)
      }
    },
    async doImport(force) {
      if (!this.importFile) return
      this.importing = true
      this.importError = ''
      this.importResult = null
      try {
        const result = await api.importEntities(this.importFile, force)
        if (result.status === 'conflicts') {
          this.conflicts = result.conflicts
        } else {
          this.importResult = result
          this.conflicts = []
          this.importFile = null
          this.$refs.fileInput.value = ''
        }
      } catch (e) {
        this.importError = e.message
      } finally {
        this.importing = false
      }
    },
  },
}
</script>

<style scoped>
.conflicts { margin-top: 12px; padding: 12px; background: #fff3e0; border-radius: 4px; }
.conflicts ul { margin: 8px 0; padding-left: 20px; }
.result { margin-top: 12px; padding: 12px; background: #e8f5e9; border-radius: 4px; }
</style>
```

- [ ] **Step 2: Добавить методы в api.js**

Добавить в `ui/src/api.js`:

```javascript
exportEntities: async () => {
  const res = await fetch(`${BASE}/transfer/export`, { method: 'POST' })
  if (!res.ok) throw new Error('Export failed')
  return res.blob()
},
importEntities: async (file, force = false) => {
  const formData = new FormData()
  formData.append('file', file)
  const res = await fetch(`${BASE}/transfer/import?force=${force}`, {
    method: 'POST',
    body: formData,
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || 'Import failed')
  }
  return res.json()
},
```

- [ ] **Step 3: Добавить навигацию в App.vue**

Добавить в навигацию (после Connectors):
```html
<router-link to="/settings">Settings</router-link>
```

- [ ] **Step 4: Добавить маршрут в main.js**

Добавить импорт и маршрут:
```javascript
import Settings from './views/Settings.vue'

const routes = [
  // ... existing routes
  { path: '/settings', component: Settings },
]
```

- [ ] **Step 5: Проверить UI работает**

Запустить UI dev server:
```bash
cd ui && npm run dev
```

Открыть http://localhost:3000/settings — проверить Export и Import кнопки.

- [ ] **Step 6: Commit**

```bash
git add ui/src/views/Settings.vue ui/src/api.js ui/src/App.vue ui/src/main.js
git commit -m "feat: add Settings page for export/import"
```

---

### Task 4: Тесты

**Covers:** Тестирование export/import API

**Files:**
- Create: `tests/orchestrator/api/test_transfer_api.py`

- [ ] **Step 1: Создать тесты для transfer API**

```python
import io
import json
import zipfile

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture
def sample_archive():
    """Create a sample export archive for testing."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        manifest = {
            "version": "1.0",
            "created_at": "20260701-120000",
            "connectors": ["test_connector"],
            "actions": ["test_action"],
            "workflows": ["test_workflow"],
        }
        zf.writestr("manifest.json", json.dumps(manifest))
        zf.writestr("connectors/test_connector/code.py", "class TestConnector: pass")
        zf.writestr("connectors/test_connector/config.yml", "instances:\n  test: {}")
        zf.writestr("actions/test_action.py", "def test_action(): pass")
        zf.writestr("workflows/test_workflow.py", "class TestWorkflow: pass")
        zf.writestr("state.yaml", json.dumps({"workflows": {"test_workflow": "enabled"}}))
    buffer.seek(0)
    return buffer


def test_export_returns_zip(client):
    response = client.post("/api/transfer/export")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"

    content = io.BytesIO(response.content)
    with zipfile.ZipFile(content) as zf:
        assert "manifest.json" in zf.namelist()
        manifest = json.loads(zf.read("manifest.json"))
        assert "version" in manifest


def test_import_returns_conflicts(client, sample_archive):
    # Create connector first
    client.post("/api/connectors/test_connector")

    response = client.post(
        "/api/transfer/import",
        files={"file": ("export.zip", sample_archive, "application/zip")},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "conflicts"
    assert len(data["conflicts"]) > 0


def test_import_with_force(client, sample_archive):
    response = client.post(
        "/api/transfer/import?force=true",
        files={"file": ("export.zip", sample_archive, "application/zip")},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "imported"


def test_import_invalid_file(client):
    response = client.post(
        "/api/transfer/import",
        files={"file": ("test.txt", b"not a zip", "text/plain")},
    )
    assert response.status_code == 400
```

- [ ] **Step 2: Запустить тесты**

```bash
python -m pytest tests/orchestrator/api/test_transfer_api.py -v
```

Ожидаемый результат: все тесты проходят

- [ ] **Step 3: Commit**

```bash
git add tests/orchestrator/api/test_transfer_api.py
git commit -m "test: add tests for export/import API"
```
