from unittest.mock import MagicMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from orchestrator.audit import service as audit_service
from orchestrator.audit.models import AuditLog
from orchestrator.auth.dependencies import CurrentUser
from orchestrator.db.base import Base

_DB_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture
async def db_session():
    engine = create_async_engine(_DB_URL, connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


def _fake_request(request_id: str | None = "req-123", client_ip: str = "1.2.3.4"):
    request = MagicMock()
    request.state.request_id = request_id
    request.app.state.config = None
    request.client.host = client_ip
    request.headers = {}
    return request


async def test_record_writes_expected_fields(db_session):
    user = CurrentUser(id=7, role="admin", type="user", username="alice")
    request = _fake_request()

    await audit_service.record(
        db_session,
        user=user,
        action="workflow.update",
        resource_type="workflow",
        resource_id="my_wf",
        request=request,
        detail={"commit": "abc1234"},
    )

    rows = (await db_session.execute(select(AuditLog))).scalars().all()
    assert len(rows) == 1
    row = rows[0]
    assert row.actor_id == 7
    assert row.actor_type == "user"
    assert row.actor_name == "alice"
    assert row.action == "workflow.update"
    assert row.resource_type == "workflow"
    assert row.resource_id == "my_wf"
    assert row.client_ip == "1.2.3.4"
    assert row.request_id == "req-123"
    assert row.detail == {"commit": "abc1234"}
    assert row.created_at is not None


async def test_record_actor_name_falls_back_to_id_for_service_accounts(db_session):
    user = CurrentUser(id=42, role="service", type="service", username="")
    request = _fake_request(request_id=None)

    await audit_service.record(
        db_session,
        user=user,
        action="job.cancel",
        resource_type="job",
        resource_id="job-1",
        request=request,
    )

    row = (await db_session.execute(select(AuditLog))).scalars().one()
    assert row.actor_name == "42"
    assert row.request_id is None
    assert row.detail is None
