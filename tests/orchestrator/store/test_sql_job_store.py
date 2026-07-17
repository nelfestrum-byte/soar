"""Mirrors tests/orchestrator/test_job_store.py, one-for-one, against SQLJobStore
backed by an in-memory SQLite DB (same fixture pattern as test_auth_api.py)."""

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from orchestrator.db.base import Base
from orchestrator.models.job import JobStatus, WorkflowJob
from orchestrator.store.sql_job_store import SQLJobStore

_DB_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture
async def store():
    engine = create_async_engine(_DB_URL, connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield SQLJobStore(factory)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


async def test_sql_job_store_save_and_get(store):
    job = WorkflowJob(workflow_name="test")
    await store.save(job)

    retrieved = await store.get(job.id)
    assert retrieved is not None
    assert retrieved.workflow_name == "test"


async def test_sql_job_store_get_not_found(store):
    result = await store.get("nonexistent")
    assert result is None


async def test_sql_job_store_list(store):
    for i in range(5):
        await store.save(WorkflowJob(workflow_name=f"wf_{i}"))

    jobs = await store.list()
    assert len(jobs) == 5


async def test_sql_job_store_list_filter_workflow_name(store):
    await store.save(WorkflowJob(workflow_name="wf_a"))
    await store.save(WorkflowJob(workflow_name="wf_b"))
    await store.save(WorkflowJob(workflow_name="wf_a"))

    jobs = await store.list(workflow_name="wf_a")
    assert len(jobs) == 2


async def test_sql_job_store_list_filter_status(store):
    job1 = WorkflowJob(workflow_name="test")
    job1.status = JobStatus.RUNNING
    await store.save(job1)

    job2 = WorkflowJob(workflow_name="test")
    job2.status = JobStatus.COMPLETED
    await store.save(job2)

    running = await store.list(status=JobStatus.RUNNING)
    assert len(running) == 1


async def test_sql_job_store_count_by_status(store):
    await store.save(WorkflowJob(workflow_name="test", status=JobStatus.RUNNING))
    await store.save(WorkflowJob(workflow_name="test", status=JobStatus.RUNNING))
    await store.save(WorkflowJob(workflow_name="test", status=JobStatus.PENDING))

    count = await store.count_by_status("test", [JobStatus.RUNNING])
    assert count == 2

    count = await store.count_by_status("test", [JobStatus.RUNNING, JobStatus.PENDING])
    assert count == 3


async def test_sql_job_store_stats(store):
    job1 = WorkflowJob(workflow_name="test", status=JobStatus.RUNNING)
    job2 = WorkflowJob(workflow_name="test", status=JobStatus.COMPLETED)
    job2.finished_at = datetime.now(UTC)
    await store.save(job1)
    await store.save(job2)

    stats = await store.stats()
    assert stats["running"] == 1
    assert stats["completed_today"] >= 1


async def test_sql_recover_on_startup_marks_running_as_failed(store):
    running_job = WorkflowJob(workflow_name="wf1", status=JobStatus.RUNNING)
    pending_job = WorkflowJob(workflow_name="wf1", status=JobStatus.PENDING)
    completed_job = WorkflowJob(workflow_name="wf1", status=JobStatus.COMPLETED)
    await store.save(running_job)
    await store.save(pending_job)
    await store.save(completed_job)

    count = await store.recover_on_startup()
    assert count == 1

    r = await store.get(running_job.id)
    assert r.status == JobStatus.FAILED
    assert r.result_error == "Process died before startup recovery"
    assert r.finished_at is not None

    p = await store.get(pending_job.id)
    assert p.status == JobStatus.PENDING

    c = await store.get(completed_job.id)
    assert c.status == JobStatus.COMPLETED


async def test_sql_recover_on_startup_returns_zero_when_no_running(store):
    await store.save(WorkflowJob(workflow_name="wf1", status=JobStatus.COMPLETED))
    count = await store.recover_on_startup()
    assert count == 0


async def test_sql_job_store_save_upserts_by_id(store):
    job = WorkflowJob(workflow_name="test", status=JobStatus.PENDING)
    await store.save(job)

    job.status = JobStatus.RUNNING
    job.pid = 1234
    await store.save(job)

    retrieved = await store.get(job.id)
    assert retrieved.status == JobStatus.RUNNING
    assert retrieved.pid == 1234
    assert len(await store.list()) == 1


async def test_sql_job_store_roundtrips_context_and_result_data(store):
    job = WorkflowJob(workflow_name="test", context={"alert_id": "abc", "n": 3})
    job.result_data = {"matched": True, "count": 2}
    await store.save(job)

    retrieved = await store.get(job.id)
    assert retrieved.context == {"alert_id": "abc", "n": 3}
    assert retrieved.result_data == {"matched": True, "count": 2}
