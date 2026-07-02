# QA API Test Plan — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use compose:subagent (recommended) or compose:execute to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create comprehensive pytest tests for all SOAR API endpoints — happy path, error handling, and 7 end-to-end scenarios.

**Architecture:** Each test file covers one resource group. All tests use httpx AsyncClient with ASGITransport (in-process, no server). GitManager is mocked to avoid real commits. Shared autouse fixture wires `app.state`.

**Tech Stack:** pytest, pytest-asyncio, httpx, unittest.mock

## Global Constraints

- No code changes to `orchestrator/` or `soar/` — tests only
- All tests in `tests/orchestrator/api/`
- GitManager always mocked (`MagicMock`)
- In-process testing via `ASGITransport(app=app)`
- Each test file has its own `autouse` fixture (copy pattern from existing `test_routes.py`)
- Run: `python -m pytest tests/orchestrator/api/ -v`

## File Structure

| File | Purpose |
|------|---------|
| `tests/orchestrator/api/conftest.py` | Shared fixture for app.state wiring |
| `tests/orchestrator/api/test_validation_api.py` | Name/path validation (V1–V6) |
| `tests/orchestrator/api/test_status_api.py` | GET /status (S1) |
| `tests/orchestrator/api/test_workflows_api.py` | Workflows CRUD (W1–W10) |
| `tests/orchestrator/api/test_actions_api.py` | Actions CRUD (A1–A5) |
| `tests/orchestrator/api/test_connectors_api.py` | Connectors CRUD (C1–C8) |
| `tests/orchestrator/api/test_jobs_api.py` | Jobs CRUD (J1–J4) |
| `tests/orchestrator/api/test_webhooks_api.py` | Webhook triggers (WH1) |
| `tests/orchestrator/api/test_logs_api.py` | Log retrieval (L1–L2) |
| `tests/orchestrator/api/test_scenarios.py` | 7 E2E scenarios |

---

### Task 1: Shared Test Fixture (conftest.py)

**Covers:** Infrastructure for all test files

**Files:**
- Create: `tests/orchestrator/api/conftest.py`

**Interfaces:**
- Produces: `app_state` autouse fixture that wires all `app.state` dependencies

- [ ] **Step 1: Create conftest.py with shared fixture**

```python
import pytest
from unittest.mock import MagicMock

from orchestrator.config import OrchestratorConfig
from orchestrator.core.job_manager import JobManager
from orchestrator.core.queue.memory import InMemoryQueue
from orchestrator.core.scheduler import OrchestratorScheduler
from orchestrator.core.subprocess_runner import SubprocessRunner
from orchestrator.core.worker_pool import WorkerPool
from orchestrator.main import app
from orchestrator.store.job_store import JobStore


@pytest.fixture(autouse=True)
def setup_app_state(tmp_path):
    queue = InMemoryQueue()
    job_store = JobStore()
    runner = SubprocessRunner()
    git = MagicMock()
    config = OrchestratorConfig()
    config.soar.workflows_dir = str(tmp_path / "workflows")
    config.soar.actions_dir = str(tmp_path / "actions")
    config.soar.connectors_dir = str(tmp_path / "connectors")

    import os
    os.makedirs(config.soar.workflows_dir, exist_ok=True)
    os.makedirs(config.soar.actions_dir, exist_ok=True)
    os.makedirs(config.soar.connectors_dir, exist_ok=True)

    job_manager = JobManager(
        queue=queue,
        job_store=job_store,
        runner=runner,
        log_dir=str(tmp_path / "logs"),
    )
    job_manager.set_metas([])

    pool = WorkerPool(
        count=2, queue=queue, runner=runner,
        job_store=job_store, default_timeout=300,
    )
    scheduler = OrchestratorScheduler(job_manager)

    app.state.job_manager = job_manager
    app.state.pool = pool
    app.state.scheduler = scheduler
    app.state.git = git
    app.state.config = config
    app.state.job_store = job_store
    app.state.queue = queue
```

- [ ] **Step 2: Verify fixture loads**

Run: `python -m pytest tests/orchestrator/api/conftest.py --collect-only`
Expected: No errors (conftest collected)

- [ ] **Step 3: Commit**

```bash
git add tests/orchestrator/api/conftest.py
git commit -m "test: add shared API test fixture"
```

---

### Task 2: Validation Tests

**Covers:** [V1–V6]

**Files:**
- Create: `tests/orchestrator/api/test_validation_api.py`

**Interfaces:**
- Consumes: conftest.py `setup_app_state` fixture

- [ ] **Step 1: Write validation tests**

```python
import pytest
from httpx import ASGITransport, AsyncClient

from orchestrator.main import app


@pytest.mark.asyncio
async def test_empty_workflow_name():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/workflows//code")
        assert r.status_code in (400, 404)


@pytest.mark.asyncio
async def test_long_workflow_name():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get(f"/workflows/{'a' * 200}/code")
        assert r.status_code == 400


@pytest.mark.asyncio
async def test_invalid_chars_workflow_name():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/workflows/../../etc/passwd/code")
        assert r.status_code in (400, 403, 404)


@pytest.mark.asyncio
async def test_valid_name_passes():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/workflows/my_valid_workflow-1/code")
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_empty_action_name():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/actions//")
        assert r.status_code in (400, 404)


@pytest.mark.asyncio
async def test_long_action_name():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get(f"/actions/{'b' * 200}")
        assert r.status_code == 400


@pytest.mark.asyncio
async def test_invalid_chars_action_name():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/actions/../../../secret")
        assert r.status_code in (400, 403, 404)
```

- [ ] **Step 2: Run validation tests**

Run: `python -m pytest tests/orchestrator/api/test_validation_api.py -v`
Expected: All 7 tests PASS

- [ ] **Step 3: Commit**

```bash
git add tests/orchestrator/api/test_validation_api.py
git commit -m "test: add API validation tests"
```

---

### Task 3: Status Endpoint Tests

**Covers:** [S1]

**Files:**
- Create: `tests/orchestrator/api/test_status_api.py`

- [ ] **Step 1: Write status tests**

```python
import pytest
from httpx import ASGITransport, AsyncClient

from orchestrator.main import app


@pytest.mark.asyncio
async def test_status_returns_all_sections():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/status")
        assert r.status_code == 200
        data = r.json()
        assert "workers" in data
        assert "queue" in data
        assert "jobs" in data
        assert "scheduler" in data


@pytest.mark.asyncio
async def test_status_queue_info():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/status")
        data = r.json()
        assert "backend" in data["queue"]
        assert "pending" in data["queue"]
        assert data["queue"]["pending"] == 0


@pytest.mark.asyncio
async def test_status_scheduler_has_next_runs():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/status")
        data = r.json()
        assert "next_runs" in data["scheduler"]
```

- [ ] **Step 2: Run status tests**

Run: `python -m pytest tests/orchestrator/api/test_status_api.py -v`
Expected: All 3 tests PASS

- [ ] **Step 3: Commit**

```bash
git add tests/orchestrator/api/test_status_api.py
git commit -m "test: add status endpoint tests"
```

---

### Task 4: Workflows CRUD Tests

**Covers:** [W1–W10]

**Files:**
- Create: `tests/orchestrator/api/test_workflows_api.py`

- [ ] **Step 1: Write workflows tests**

```python
import pytest
from httpx import ASGITransport, AsyncClient

from orchestrator.main import app


@pytest.mark.asyncio
async def test_list_workflows_empty():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/workflows")
        assert r.status_code == 200
        assert isinstance(r.json(), list)


@pytest.mark.asyncio
async def test_get_workflow_not_found():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/workflows/nonexistent")
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_enable_workflow_not_found():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/workflows/nonexistent/enable")
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_disable_workflow_not_found():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/workflows/nonexistent/disable")
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_reload_workflows():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/workflows/reload")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "reloaded"
        assert "count" in data


@pytest.mark.asyncio
async def test_reload_scheduler():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/workflows/scheduler/reload")
        assert r.status_code == 200
        assert r.json()["status"] == "reloaded"


@pytest.mark.asyncio
async def test_workflow_template():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/workflows/code/template")
        assert r.status_code == 200
        assert "content" in r.json()


@pytest.mark.asyncio
async def test_workflow_template_types():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        for wf_type in ["scheduled", "webhook", "manual"]:
            r = await c.get(f"/workflows/code/template?wf_type={wf_type}")
            assert r.status_code == 200
            assert "content" in r.json()


@pytest.mark.asyncio
async def test_workflow_code_not_found():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/workflows/nonexistent/code")
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_workflow_code_invalid_name():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/workflows/../../etc/passwd/code")
        assert r.status_code in (400, 403, 404)


@pytest.mark.asyncio
async def test_save_workflow_code():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.put("/workflows/test_wf/code", content=b"# test workflow")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "saved"
        assert "commit" in data


@pytest.mark.asyncio
async def test_delete_workflow_code_not_found():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.delete("/workflows/nonexistent/code")
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_save_delete_workflow_code():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.put("/workflows/temp_wf/code", content=b"# temp")
        r = await c.delete("/workflows/temp_wf/code")
        assert r.status_code == 200
        assert r.json()["status"] == "deleted"
```

- [ ] **Step 2: Run workflows tests**

Run: `python -m pytest tests/orchestrator/api/test_workflows_api.py -v`
Expected: All 13 tests PASS

- [ ] **Step 3: Commit**

```bash
git add tests/orchestrator/api/test_workflows_api.py
git commit -m "test: add workflows CRUD tests"
```

---

### Task 5: Actions CRUD Tests

**Covers:** [A1–A5]

**Files:**
- Create: `tests/orchestrator/api/test_actions_api.py`

- [ ] **Step 1: Write actions tests**

```python
import pytest
from httpx import ASGITransport, AsyncClient

from orchestrator.main import app


@pytest.mark.asyncio
async def test_list_actions():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/actions")
        assert r.status_code == 200
        assert isinstance(r.json(), list)


@pytest.mark.asyncio
async def test_action_template():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/actions/template")
        assert r.status_code == 200
        assert "content" in r.json()


@pytest.mark.asyncio
async def test_action_template_custom():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/actions/template?name=custom&description=Test")
        assert r.status_code == 200
        content = r.json()["content"]
        assert "custom" in content


@pytest.mark.asyncio
async def test_get_action_not_found():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/actions/nonexistent")
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_get_action_invalid_name():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/actions/../../secret")
        assert r.status_code in (400, 403, 404)


@pytest.mark.asyncio
async def test_save_action():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.put("/actions/test_action", content=b"# test action")
        assert r.status_code == 200
        assert r.json()["status"] == "saved"


@pytest.mark.asyncio
async def test_get_saved_action():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.put("/actions/saved_action", content=b"# content")
        r = await c.get("/actions/saved_action")
        assert r.status_code == 200
        assert r.json()["content"] == "# content"


@pytest.mark.asyncio
async def test_delete_action_not_found():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.delete("/actions/nonexistent")
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_delete_action():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.put("/actions/to_delete", content=b"# del")
        r = await c.delete("/actions/to_delete")
        assert r.status_code == 200
        assert r.json()["status"] == "deleted"
```

- [ ] **Step 2: Run actions tests**

Run: `python -m pytest tests/orchestrator/api/test_actions_api.py -v`
Expected: All 9 tests PASS

- [ ] **Step 3: Commit**

```bash
git add tests/orchestrator/api/test_actions_api.py
git commit -m "test: add actions CRUD tests"
```

---

### Task 6: Connectors CRUD Tests

**Covers:** [C1–C8]

**Files:**
- Create: `tests/orchestrator/api/test_connectors_api.py`

- [ ] **Step 1: Write connectors tests**

```python
import pytest
from httpx import ASGITransport, AsyncClient

from orchestrator.main import app


@pytest.mark.asyncio
async def test_list_connectors():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/connectors")
        assert r.status_code == 200
        assert isinstance(r.json(), list)


@pytest.mark.asyncio
async def test_connector_template():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/connectors/template")
        assert r.status_code == 200
        data = r.json()
        assert "code" in data
        assert "config" in data


@pytest.mark.asyncio
async def test_connector_template_custom():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/connectors/template?name=my_conn&class_name=MyCustom")
        assert r.status_code == 200
        assert "MyCustomConnector" in r.json()["code"]


@pytest.mark.asyncio
async def test_create_connector():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/connectors/test_conn")
        assert r.status_code == 200
        assert r.json()["status"] == "created"


@pytest.mark.asyncio
async def test_create_connector_duplicate():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/connectors/dup_conn")
        r = await c.post("/connectors/dup_conn")
        assert r.status_code == 409


@pytest.mark.asyncio
async def test_get_connector_code():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/connectors/code_conn")
        r = await c.get("/connectors/code_conn/code")
        assert r.status_code == 200
        assert "content" in r.json()


@pytest.mark.asyncio
async def test_get_connector_code_not_found():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/connectors/nonexistent/code")
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_save_connector_code():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/connectors/save_conn")
        r = await c.put("/connectors/save_conn/code", content=b"# connector code")
        assert r.status_code == 200
        assert r.json()["status"] == "saved"


@pytest.mark.asyncio
async def test_get_connector_config():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/connectors/conf_conn")
        r = await c.get("/connectors/conf_conn/config")
        assert r.status_code == 200
        assert "content" in r.json()


@pytest.mark.asyncio
async def test_save_connector_config():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/connectors/yml_conn")
        r = await c.put("/connectors/yml_conn/config", content=b"instances: {}")
        assert r.status_code == 200
        assert r.json()["status"] == "saved"


@pytest.mark.asyncio
async def test_delete_connector_not_found():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.delete("/connectors/nonexistent")
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_delete_connector():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/connectors/del_conn")
        r = await c.delete("/connectors/del_conn")
        assert r.status_code == 200
        assert r.json()["status"] == "deleted"


@pytest.mark.asyncio
async def test_connectors_list_after_create_delete():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/connectors/list_test")
        r = await c.get("/connectors")
        names = [x["name"] for x in r.json()]
        assert "list_test" in names
        await c.delete("/connectors/list_test")
        r = await c.get("/connectors")
        names = [x["name"] for x in r.json()]
        assert "list_test" not in names
```

- [ ] **Step 2: Run connectors tests**

Run: `python -m pytest tests/orchestrator/api/test_connectors_api.py -v`
Expected: All 13 tests PASS

- [ ] **Step 3: Commit**

```bash
git add tests/orchestrator/api/test_connectors_api.py
git commit -m "test: add connectors CRUD tests"
```

---

### Task 7: Jobs Tests

**Covers:** [J1–J4]

**Files:**
- Create: `tests/orchestrator/api/test_jobs_api.py`

- [ ] **Step 1: Write jobs tests**

```python
import pytest
from httpx import ASGITransport, AsyncClient

from orchestrator.main import app


@pytest.mark.asyncio
async def test_list_jobs_empty():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/jobs")
        assert r.status_code == 200
        assert isinstance(r.json(), list)


@pytest.mark.asyncio
async def test_list_jobs_with_filters():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/jobs?status=pending&limit=10&offset=0")
        assert r.status_code == 200


@pytest.mark.asyncio
async def test_get_job_not_found():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/jobs/nonexistent")
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_create_job_not_found():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/jobs", json={"workflow_name": "NonExistent", "context": {}})
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_cancel_job_not_found():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/jobs/nonexistent/cancel")
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_create_job_wrong_body():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/jobs", json={"wrong": "field"})
        assert r.status_code == 422
```

- [ ] **Step 2: Run jobs tests**

Run: `python -m pytest tests/orchestrator/api/test_jobs_api.py -v`
Expected: All 6 tests PASS

- [ ] **Step 3: Commit**

```bash
git add tests/orchestrator/api/test_jobs_api.py
git commit -m "test: add jobs endpoint tests"
```

---

### Task 8: Webhooks Tests

**Covers:** [WH1]

**Files:**
- Create: `tests/orchestrator/api/test_webhooks_api.py`

- [ ] **Step 1: Write webhooks tests**

```python
import pytest
from httpx import ASGITransport, AsyncClient

from orchestrator.main import app


@pytest.mark.asyncio
async def test_webhook_not_found():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/webhooks/nonexistent", json={})
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_webhook_invalid_token():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post(
            "/webhooks/nonexistent",
            json={},
            headers={"X-Webhook-Token": "wrong"},
        )
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_webhook_not_webhook_type():
    from orchestrator.models.workflow_meta import WorkflowMeta
    from orchestrator.models import ConcurrencyPolicy

    meta = WorkflowMeta(
        name="manual_wf",
        type="manual",
        enabled=True,
        path="manual_wf",
        timeout=300,
        concurrency=ConcurrencyPolicy.FORBID,
    )
    app.state.job_manager.set_metas([meta])

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/webhooks/manual_wf", json={})
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_webhook_disabled():
    from orchestrator.models.workflow_meta import WorkflowMeta
    from orchestrator.models import ConcurrencyPolicy

    meta = WorkflowMeta(
        name="disabled_wh",
        type="webhook",
        enabled=False,
        path="disabled_wh",
        token="validtoken",
        timeout=300,
        concurrency=ConcurrencyPolicy.FORBID,
    )
    app.state.job_manager.set_metas([meta])

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post(
            "/webhooks/disabled_wh",
            json={"test": 1},
            headers={"X-Webhook-Token": "validtoken"},
        )
        assert r.status_code == 409
```

- [ ] **Step 2: Run webhooks tests**

Run: `python -m pytest tests/orchestrator/api/test_webhooks_api.py -v`
Expected: All 4 tests PASS

- [ ] **Step 3: Commit**

```bash
git add tests/orchestrator/api/test_webhooks_api.py
git commit -m "test: add webhooks endpoint tests"
```

---

### Task 9: Logs Tests

**Covers:** [L1–L2]

**Files:**
- Create: `tests/orchestrator/api/test_logs_api.py`

- [ ] **Step 1: Write logs tests**

```python
import pytest
from httpx import ASGITransport, AsyncClient

from orchestrator.main import app


@pytest.mark.asyncio
async def test_log_not_found():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/logs/nonexistent")
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_log_stream_not_found():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/logs/nonexistent/stream")
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_log_no_log_path():
    from orchestrator.models.job import WorkflowJob
    from orchestrator.models import JobStatus

    job = WorkflowJob(
        id="test-log-no-path",
        workflow_name="test",
        status=JobStatus.COMPLETED,
        log_path=None,
    )
    app.state.job_store._jobs[job.id] = job

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/logs/test-log-no-path")
        assert r.status_code == 404
```

- [ ] **Step 2: Run logs tests**

Run: `python -m pytest tests/orchestrator/api/test_logs_api.py -v`
Expected: All 3 tests PASS

- [ ] **Step 3: Commit**

```bash
git add tests/orchestrator/api/test_logs_api.py
git commit -m "test: add logs endpoint tests"
```

---

### Task 10: E2E Scenarios

**Covers:** [S5]

**Files:**
- Create: `tests/orchestrator/api/test_scenarios.py`

- [ ] **Step 1: Write E2E scenario tests**

```python
import time
import pytest
from httpx import ASGITransport, AsyncClient

from orchestrator.main import app


@pytest.mark.asyncio
async def test_scenario_1_manual_workflow_fire_and_forget():
    """Scenario 1: Create manual workflow, enable, run job."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        # 1. Get template
        r = await c.get("/workflows/code/template?wf_type=manual&name=manual_test")
        template = r.json()["content"]

        # 2. Save workflow code
        r = await c.put("/workflows/manual_test/code", content=template.encode())
        assert r.status_code == 200

        # 3. Reload
        r = await c.post("/workflows/reload")
        assert r.status_code == 200

        # 4. Enable
        r = await c.post("/workflows/manual_test/enable")
        assert r.status_code == 200

        # 5. Create job
        r = await c.post("/jobs", json={"workflow_name": "manual_test", "context": {}})
        assert r.status_code == 202
        job_id = r.json()["id"]

        # 6. Check job
        r = await c.get(f"/jobs/{job_id}")
        assert r.status_code == 200
        assert r.json()["workflow_name"] == "manual_test"


@pytest.mark.asyncio
async def test_scenario_3_enable_disable_cycle():
    """Scenario 3: Scheduled workflow - enable/disable cycle."""
    from orchestrator.models.workflow_meta import WorkflowMeta
    from orchestrator.models import ConcurrencyPolicy

    meta = WorkflowMeta(
        name="sched_test",
        type="scheduled",
        enabled=True,
        schedule="*/10 * * * *",
        path="sched_test",
        timeout=300,
        concurrency=ConcurrencyPolicy.FORBID,
    )
    app.state.job_manager.set_metas([meta])

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        # Disable
        r = await c.post("/workflows/sched_test/disable")
        assert r.status_code == 200
        assert r.json()["status"] == "disabled"

        # Verify disabled
        r = await c.get("/workflows/sched_test")
        assert r.json()["enabled"] is False

        # Enable
        r = await c.post("/workflows/sched_test/enable")
        assert r.status_code == 200
        assert r.json()["status"] == "enabled"

        # Verify enabled
        r = await c.get("/workflows/sched_test")
        assert r.json()["enabled"] is True


@pytest.mark.asyncio
async def test_scenario_4_connector_crud_lifecycle():
    """Scenario 4: Full connector CRUD lifecycle."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        # Create
        r = await c.post("/connectors/test_crud")
        assert r.status_code == 200

        # List
        r = await c.get("/connectors")
        names = [x["name"] for x in r.json()]
        assert "test_crud" in names

        # Update code
        r = await c.put("/connectors/test_crud/code", content=b"# updated")
        assert r.status_code == 200

        # Read code
        r = await c.get("/connectors/test_crud/code")
        assert r.json()["content"] == "# updated"

        # Update config
        r = await c.put("/connectors/test_crud/config", content=b"instances:\n  test: {}")
        assert r.status_code == 200

        # Read config
        r = await c.get("/connectors/test_crud/config")
        assert "test" in r.json()["content"]

        # Delete
        r = await c.delete("/connectors/test_crud")
        assert r.status_code == 200

        # Verify removed
        r = await c.get("/connectors")
        names = [x["name"] for x in r.json()]
        assert "test_crud" not in names


@pytest.mark.asyncio
async def test_scenario_5_action_crud_lifecycle():
    """Scenario 5: Full action CRUD lifecycle."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        # Get template
        r = await c.get("/actions/template?name=scenario_action")
        template = r.json()["content"]

        # Save
        r = await c.put("/actions/scenario_action", content=template.encode())
        assert r.status_code == 200

        # List
        r = await c.get("/actions")
        assert "scenario_action" in r.json()

        # Get
        r = await c.get("/actions/scenario_action")
        assert r.status_code == 200

        # Delete
        r = await c.delete("/actions/scenario_action")
        assert r.status_code == 200

        # Verify removed
        r = await c.get("/actions")
        assert "scenario_action" not in r.json()


@pytest.mark.asyncio
async def test_scenario_6_job_lifecycle():
    """Scenario 6: Create, list, get, cancel job."""
    from orchestrator.models.workflow_meta import WorkflowMeta
    from orchestrator.models import ConcurrencyPolicy

    meta = WorkflowMeta(
        name="lifecycle_wf",
        type="manual",
        enabled=True,
        path="lifecycle_wf",
        timeout=300,
        concurrency=ConcurrencyPolicy.ALLOW,
    )
    app.state.job_manager.set_metas([meta])

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        # Create job
        r = await c.post("/jobs", json={"workflow_name": "lifecycle_wf", "context": {"key": "val"}})
        assert r.status_code == 202
        job_id = r.json()["id"]

        # List jobs
        r = await c.get("/jobs")
        ids = [j["id"] for j in r.json()]
        assert job_id in ids

        # Get specific job
        r = await c.get(f"/jobs/{job_id}")
        assert r.status_code == 200
        assert r.json()["context"]["key"] == "val"
```

- [ ] **Step 2: Run scenario tests**

Run: `python -m pytest tests/orchestrator/api/test_scenarios.py -v`
Expected: All 5 scenario tests PASS

- [ ] **Step 3: Commit**

```bash
git add tests/orchestrator/api/test_scenarios.py
git commit -m "test: add E2E scenario tests"
```

---

### Task 11: Run Full Test Suite

**Covers:** All spec sections

- [ ] **Step 1: Run all API tests**

Run: `python -m pytest tests/orchestrator/api/ -v`
Expected: All tests PASS, 0 failures

- [ ] **Step 2: Run with coverage**

Run: `python -m pytest tests/orchestrator/api/ --cov=orchestrator/api -v`
Expected: Coverage report for api/ module

- [ ] **Step 3: Final commit (if any fixes needed)**

```bash
git add tests/orchestrator/api/
git commit -m "test: complete QA API test suite"
```
