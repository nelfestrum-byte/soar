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
