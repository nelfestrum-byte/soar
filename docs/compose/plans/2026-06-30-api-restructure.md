# API Restructure: Entity-First Design — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use compose:subagent (recommended) or compose:execute to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restructure API endpoints so each entity (workflow, action, connector) owns its own code/config endpoints. Remove redundant `/files` and `/workflow-files` routers.

**Architecture:** Add code CRUD endpoints to existing `workflows.py` router. Delete `workflow_files.py` and `files.py`. Update UI client and docs to match.

**Tech Stack:** FastAPI, Python 3.11+, Vue.js

## Global Constraints

- Python 3.11+
- FastAPI router conventions (prefix, tags)
- No new abstractions — just move endpoints
- Follow existing code style (no comments, no defensive error handling)

---

### Task 1: Add code CRUD to workflows router

**Covers:** [S2, S3]

**Files:**
- Modify: `orchestrator/api/workflows.py`

**Interfaces:**
- Consumes: existing `validate_name`, `validate_path_within` from `orchestrator.api.validation`
- Produces: `GET /workflows/{name}/code`, `PUT /workflows/{name}/code`, `DELETE /workflows/{name}/code`, `GET /workflows/code/template`

- [ ] **Step 1: Add code endpoints to workflows.py**

Add these imports at the top of `orchestrator/api/workflows.py`:
```python
import os

from orchestrator.api.validation import validate_name, validate_path_within
```

Add template constants after the router definition:
```python
SCHEDULED_TEMPLATE = '''from soar.workflows.base import ScheduledWorkflow
from soar.connectors import connectors


class {name}(ScheduledWorkflow):
    schedule = "*/10 * * * *"  # every 10 minutes

    def run(self, context):
        # TODO: implement
        return {{"status": "ok"}}
'''

WEBHOOK_TEMPLATE = '''from soar.workflows.base import WebhookWorkflow
from soar.connectors import connectors
from soar.logger import get_logger
import secrets

_log = get_logger("workflow.{name}")


class {name}(WebhookWorkflow):
    path = "/webhook/{path}"
    token = secrets.token_urlsafe(32)

    def run(self, context):
        payload = context.get("payload", {{}})
        _log.info(f"Received webhook: {{payload}}")
        # TODO: implement
        return {{"status": "ok", "payload": payload}}
'''

MANUAL_TEMPLATE = '''from soar.workflows.base import ManualWorkflow
from soar.connectors import connectors
from soar.logger import get_logger

_log = get_logger("workflow.{name}")


class {name}(ManualWorkflow):
    def run(self, context):
        _log.info(f"Running with context: {{context}}")
        # TODO: implement
        return {{"status": "ok"}}
'''

TEMPLATES = {
    "scheduled": SCHEDULED_TEMPLATE,
    "webhook": WEBHOOK_TEMPLATE,
    "manual": MANUAL_TEMPLATE,
}
```

Add the code endpoints before `_save_state`:
```python
@router.get("/code/template")
async def get_workflow_template(name: str = "MyWorkflow", wf_type: str = "scheduled", path: str = "my-endpoint"):
    template = TEMPLATES.get(wf_type, SCHEDULED_TEMPLATE)
    return {"content": template.format(name=name, path=path)}


@router.get("/{name}/code")
async def get_workflow_code(name: str, request: Request):
    validate_name(name)
    config = request.app.state.config
    filepath = os.path.join(config.soar.workflows_dir, f"{name}.py")
    validate_path_within(config.soar.workflows_dir, filepath)
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="Workflow not found")
    with open(filepath) as f:
        content = f.read()
    return {"name": name, "content": content}


@router.put("/{name}/code")
async def save_workflow_code(name: str, request: Request):
    validate_name(name)
    config = request.app.state.config
    filepath = os.path.join(config.soar.workflows_dir, f"{name}.py")
    validate_path_within(config.soar.workflows_dir, filepath)
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    body = await request.body()
    with open(filepath, "wb") as f:
        f.write(body)
    git = request.app.state.git
    try:
        commit_hash = await git.commit(f"workflows/{name}.py", f"Update workflow {name}")
    except RuntimeError as e:
        return {"status": "saved", "commit": "", "warning": str(e)}
    return {"status": "saved", "commit": commit_hash}


@router.delete("/{name}/code")
async def delete_workflow_code(name: str, request: Request):
    validate_name(name)
    config = request.app.state.config
    filepath = os.path.join(config.soar.workflows_dir, f"{name}.py")
    validate_path_within(config.soar.workflows_dir, filepath)
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="Workflow not found")
    os.remove(filepath)
    git = request.app.state.git
    try:
        commit_hash = await git.commit(f"workflows/{name}.py", f"Delete workflow {name}")
    except RuntimeError as e:
        return {"status": "deleted", "commit": "", "warning": str(e)}
    return {"status": "deleted", "commit": commit_hash}
```

- [ ] **Step 2: Verify lint passes**

Run: `ruff check orchestrator/api/workflows.py`
Expected: PASS (no errors)

---

### Task 2: Delete workflow_files.py and files.py

**Covers:** [S2, S3]

**Files:**
- Delete: `orchestrator/api/workflow_files.py`
- Delete: `orchestrator/api/files.py`

- [ ] **Step 1: Delete workflow_files.py**

Run: `del orchestrator\api\workflow_files.py`

- [ ] **Step 2: Delete files.py**

Run: `del orchestrator\api\files.py`

---

### Task 3: Update __init__.py and main.py

**Covers:** [S2]

**Files:**
- Modify: `orchestrator/api/__init__.py`
- Modify: `orchestrator/main.py`

- [ ] **Step 1: Update __init__.py**

Replace `orchestrator/api/__init__.py` with:
```python
from orchestrator.api.actions import router as actions_router
from orchestrator.api.connectors import router as connectors_router
from orchestrator.api.jobs import router as jobs_router
from orchestrator.api.logs import router as logs_router
from orchestrator.api.status import router as status_router
from orchestrator.api.webhooks import router as webhooks_router
from orchestrator.api.workflows import router as workflows_router

__all__ = [
    "workflows_router",
    "actions_router",
    "connectors_router",
    "jobs_router",
    "webhooks_router",
    "logs_router",
    "status_router",
]
```

- [ ] **Step 2: Update main.py imports and includes**

In `orchestrator/main.py`, change the import block (lines 10-20) from:
```python
from orchestrator.api import (
    actions_router,
    connectors_router,
    files_router,
    jobs_router,
    logs_router,
    status_router,
    webhooks_router,
    workflow_files_router,
    workflows_router,
)
```
to:
```python
from orchestrator.api import (
    actions_router,
    connectors_router,
    jobs_router,
    logs_router,
    status_router,
    webhooks_router,
    workflows_router,
)
```

Change the router includes (lines 160-168) from:
```python
app.include_router(workflows_router)
app.include_router(workflow_files_router)
app.include_router(files_router)
app.include_router(actions_router)
app.include_router(connectors_router)
app.include_router(jobs_router)
app.include_router(webhooks_router)
app.include_router(logs_router)
app.include_router(status_router)
```
to:
```python
app.include_router(workflows_router)
app.include_router(actions_router)
app.include_router(connectors_router)
app.include_router(jobs_router)
app.include_router(webhooks_router)
app.include_router(logs_router)
app.include_router(status_router)
```

- [ ] **Step 3: Verify lint passes**

Run: `ruff check orchestrator/`
Expected: PASS (no errors referencing deleted modules)

---

### Task 4: Update UI api.js

**Covers:** [S3]

**Files:**
- Modify: `ui/src/api.js`

- [ ] **Step 1: Replace api.js with updated endpoints**

Replace `ui/src/api.js` with:
```javascript
const BASE = '/api'

async function request(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...options.headers },
    ...options,
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || 'Request failed')
  }
  return res.json()
}

export const api = {
  getStatus: () => request('/status'),
  getWorkflows: () => request('/workflows'),
  reloadWorkflows: () => request('/workflows/reload', { method: 'POST' }),
  enableWorkflow: (name) => request(`/workflows/${name}/enable`, { method: 'POST' }),
  disableWorkflow: (name) => request(`/workflows/${name}/disable`, { method: 'POST' }),
  getWorkflowCode: (name) => request(`/workflows/${name}/code`),
  saveWorkflowCode: (name, content) =>
    request(`/workflows/${name}/code`, { method: 'PUT', body: content }),
  deleteWorkflowCode: (name) => request(`/workflows/${name}/code`, { method: 'DELETE' }),
  getWorkflowTemplate: (name, type = 'scheduled') =>
    request(`/workflows/code/template?name=${name}&wf_type=${type}`),
  getJobs: (params = {}) => {
    const qs = new URLSearchParams(params).toString()
    return request(`/jobs${qs ? '?' + qs : ''}`)
  },
  createJob: (workflow_name, context = {}) =>
    request('/jobs', { method: 'POST', body: JSON.stringify({ workflow_name, context }) }),
  getJob: (id) => request(`/jobs/${id}`),
  cancelJob: (id) => request(`/jobs/${id}/cancel`, { method: 'POST' }),
  getActions: () => request('/actions'),
  getAction: (name) => request(`/actions/${name}`),
  saveAction: (name, content) =>
    request(`/actions/${name}`, { method: 'PUT', body: content }),
  deleteAction: (name) => request(`/actions/${name}`, { method: 'DELETE' }),
  getActionTemplate: (name) => request(`/actions/template?name=${name}`),
  getConnectors: () => request('/connectors'),
  getConnectorCode: (name) => request(`/connectors/${name}/code`),
  saveConnectorCode: (name, content) =>
    request(`/connectors/${name}/code`, { method: 'PUT', body: content }),
  getConnectorConfig: (name) => request(`/connectors/${name}/config`),
  saveConnectorConfig: (name, content) =>
    request(`/connectors/${name}/config`, { method: 'PUT', body: content }),
  createConnector: (name, className = '') =>
    request(`/connectors/${name}?class_name=${className}`, { method: 'POST' }),
  deleteConnector: (name) => request(`/connectors/${name}`, { method: 'DELETE' }),
}
```

- [ ] **Step 2: Update UI views that use old API methods**

Check all Vue views for references to old API methods (`getWorkflowFiles`, `getWorkflowFile`, `saveWorkflowFile`, `deleteWorkflowFile`, `getWorkflowTemplate`, `getFiles`, `getFile`, `saveFile`).

Update each view to use the new method names:
- `getWorkflowFiles` → `getWorkflows` (for listing runtime state)
- `getWorkflowFile(name)` → `getWorkflowCode(name)`
- `saveWorkflowFile(name, content)` → `saveWorkflowCode(name, content)`
- `deleteWorkflowFile(name)` → `deleteWorkflowCode(name)`
- `getWorkflowTemplate(name, type)` → `getWorkflowTemplate(name, type)` (same name, new endpoint)

- [ ] **Step 3: Verify lint passes**

Run: `ruff check ui/` (if ruff configured for JS, otherwise skip)

---

### Task 5: Update AGENTS.md

**Covers:** [S2]

**Files:**
- Modify: `AGENTS.md`

- [ ] **Step 1: Update API Endpoints section in AGENTS.md**

Replace the Workflow Files table with the updated Workflow endpoints table. Remove the Files section entirely.

Updated Workflows table:
```markdown
### Workflows
| Method | Path | Description |
|--------|------|-------------|
| GET | /workflows | Список registered workflows (runtime meta) |
| GET | /workflows/{name} | Получить meta workflow |
| POST | /workflows/{name}/enable | Включить workflow |
| POST | /workflows/{name}/disable | Выключить workflow |
| POST | /workflows/reload | Перечитать файлы и обновить job_manager |
| GET | /workflows/{name}/code | Получить код workflow |
| PUT | /workflows/{name}/code | Сохранить код workflow |
| DELETE | /workflows/{name}/code | Удалить файл workflow |
| GET | /workflows/code/template | Шаблон workflow |
```

Remove the Workflow Files and Files sections entirely.

- [ ] **Step 2: Update File map table**

Replace:
```
| Добавить API эндпоинт | `orchestrator/api/*.py` |
| Шаблон workflow | `orchestrator/api/workflow_files.py` — TEMPLATES dict |
```
with:
```
| Добавить API эндпоинт | `orchestrator/api/*.py` |
| Шаблон workflow | `orchestrator/api/workflows.py` — TEMPLATES dict |
```

---

### Task 6: Run verification

**Covers:** [S5]

**Files:** None (verification only)

- [ ] **Step 1: Run lint**

Run: `ruff check orchestrator/`
Expected: PASS

- [ ] **Step 2: Run type check**

Run: `mypy orchestrator/ --ignore-missing-imports`
Expected: PASS

- [ ] **Step 3: Run tests**

Run: `python -m pytest tests/ -v`
Expected: All tests pass (some may need updating if they reference deleted endpoints)

- [ ] **Step 4: Verify no broken imports**

Run: `python -c "from orchestrator.main import app; print('OK')"`
Expected: OK
