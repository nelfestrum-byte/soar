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
