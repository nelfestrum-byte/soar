from datetime import UTC, datetime

import pytest

from orchestrator.models.job import JobStatus, WorkflowJob
from orchestrator.store.job_store import JobStore


@pytest.mark.asyncio
async def test_job_store_save_and_get():
    store = JobStore()
    job = WorkflowJob(workflow_name="test")
    await store.save(job)

    retrieved = await store.get(job.id)
    assert retrieved is not None
    assert retrieved.workflow_name == "test"


@pytest.mark.asyncio
async def test_job_store_get_not_found():
    store = JobStore()
    result = await store.get("nonexistent")
    assert result is None


@pytest.mark.asyncio
async def test_job_store_list():
    store = JobStore()
    for i in range(5):
        await store.save(WorkflowJob(workflow_name=f"wf_{i}"))

    jobs = await store.list()
    assert len(jobs) == 5


@pytest.mark.asyncio
async def test_job_store_list_filter_workflow_name():
    store = JobStore()
    await store.save(WorkflowJob(workflow_name="wf_a"))
    await store.save(WorkflowJob(workflow_name="wf_b"))
    await store.save(WorkflowJob(workflow_name="wf_a"))

    jobs = await store.list(workflow_name="wf_a")
    assert len(jobs) == 2


@pytest.mark.asyncio
async def test_job_store_list_filter_status():
    store = JobStore()
    job1 = WorkflowJob(workflow_name="test")
    job1.status = JobStatus.RUNNING
    await store.save(job1)

    job2 = WorkflowJob(workflow_name="test")
    job2.status = JobStatus.COMPLETED
    await store.save(job2)

    running = await store.list(status=JobStatus.RUNNING)
    assert len(running) == 1


@pytest.mark.asyncio
async def test_job_store_count_by_status():
    store = JobStore()
    await store.save(WorkflowJob(workflow_name="test", status=JobStatus.RUNNING))
    await store.save(WorkflowJob(workflow_name="test", status=JobStatus.RUNNING))
    await store.save(WorkflowJob(workflow_name="test", status=JobStatus.PENDING))

    count = await store.count_by_status("test", [JobStatus.RUNNING])
    assert count == 2

    count = await store.count_by_status("test", [JobStatus.RUNNING, JobStatus.PENDING])
    assert count == 3


@pytest.mark.asyncio
async def test_job_store_stats():
    store = JobStore()
    job1 = WorkflowJob(workflow_name="test", status=JobStatus.RUNNING)
    job2 = WorkflowJob(workflow_name="test", status=JobStatus.COMPLETED)
    job2.finished_at = datetime.now(UTC)
    await store.save(job1)
    await store.save(job2)

    stats = await store.stats()
    assert stats["running"] == 1
    assert stats["completed_today"] >= 1


@pytest.mark.asyncio
async def test_recover_on_startup_marks_running_as_failed():
    store = JobStore()
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


@pytest.mark.asyncio
async def test_recover_on_startup_returns_zero_when_no_running():
    store = JobStore()
    await store.save(WorkflowJob(workflow_name="wf1", status=JobStatus.COMPLETED))
    count = await store.recover_on_startup()
    assert count == 0
