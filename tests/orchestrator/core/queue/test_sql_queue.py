"""SQLQueue polls the same workflow_jobs table SQLJobStore writes to (see
docs/compose/specs/2026-07-27-sql-job-queue-design.md [S4]). Fixture pattern
mirrors tests/orchestrator/store/test_sql_job_store.py."""

import asyncio

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from orchestrator.core.queue.sql_queue import SQLQueue
from orchestrator.db.base import Base
from orchestrator.models.job import JobStatus, WorkflowJob
from orchestrator.store.sql_job_store import SQLJobStore

_DB_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture
async def session_factory():
    engine = create_async_engine(_DB_URL, connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
def store(session_factory):
    return SQLJobStore(session_factory)


@pytest.fixture
def queue(session_factory):
    return SQLQueue(session_factory, poll_interval=0.05)


async def test_sql_queue_pop_claims_pending_job(store, queue):
    job = WorkflowJob(workflow_name="test")
    await store.save(job)

    popped = await queue.pop(timeout=1.0)

    assert popped is not None
    assert popped.id == job.id
    assert popped.workflow_name == "test"

    # claim must flip status to RUNNING in the underlying store
    persisted = await store.get(job.id)
    assert persisted.status == JobStatus.RUNNING


async def test_sql_queue_pop_returns_none_when_empty(queue):
    popped = await queue.pop(timeout=0.2)
    assert popped is None


async def test_sql_queue_pop_orders_by_triggered_at(store, queue):
    from datetime import UTC, datetime, timedelta

    now = datetime.now(UTC)
    older = WorkflowJob(workflow_name="older", triggered_at=now - timedelta(seconds=10))
    newer = WorkflowJob(workflow_name="newer", triggered_at=now)
    await store.save(newer)
    await store.save(older)

    popped = await queue.pop(timeout=1.0)

    assert popped.workflow_name == "older"


async def test_sql_queue_push_does_not_duplicate_row(store, queue, session_factory):
    from sqlalchemy import func, select

    from orchestrator.store.models import JobRecord

    job = WorkflowJob(workflow_name="test")
    await store.save(job)

    await queue.push(job)

    async with session_factory() as session:
        result = await session.execute(select(func.count()).select_from(JobRecord))
        assert result.scalar_one() == 1


async def test_sql_queue_concurrent_pop_claims_exactly_once(store, queue):
    job = WorkflowJob(workflow_name="test")
    await store.save(job)

    results = await asyncio.gather(
        queue.pop(timeout=0.5),
        queue.pop(timeout=0.5),
    )

    non_none = [r for r in results if r is not None]
    assert len(non_none) == 1
    assert non_none[0].id == job.id


async def test_sql_queue_size_counts_pending_only(store, queue):
    pending = WorkflowJob(workflow_name="a", status=JobStatus.PENDING)
    running = WorkflowJob(workflow_name="b", status=JobStatus.RUNNING)
    await store.save(pending)
    await store.save(running)

    assert await queue.size() == 1


async def test_sql_queue_health_reports_connected(queue):
    health = await queue.health()
    assert health["connected"] is True
    assert "size" in health
