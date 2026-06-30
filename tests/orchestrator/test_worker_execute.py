import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch
from orchestrator.core.worker import Worker
from orchestrator.core.queue.memory import InMemoryQueue
from orchestrator.store.job_store import JobStore
from orchestrator.models.job import WorkflowJob, JobStatus


@pytest.fixture
def worker_deps():
    queue = InMemoryQueue()
    job_store = JobStore()
    runner = MagicMock()
    runner.start = AsyncMock()
    return queue, job_store, runner


@pytest.mark.asyncio
async def test_execute_success(worker_deps):
    queue, job_store, runner = worker_deps
    worker = Worker(0, queue, runner, job_store, default_timeout=30)

    proc = AsyncMock()
    proc.pid = 12345
    proc.communicate.return_value = (b"ok", b"")
    proc.returncode = 0
    runner.start.return_value = proc

    job = WorkflowJob(id="j1", workflow_name="test", context={})
    await worker._execute(job)

    assert job.status == JobStatus.COMPLETED
    assert job.result_success is True
    assert job.pid == 12345
    assert job.finished_at is not None


@pytest.mark.asyncio
async def test_execute_failure(worker_deps):
    queue, job_store, runner = worker_deps
    worker = Worker(0, queue, runner, job_store, default_timeout=30)

    proc = AsyncMock()
    proc.pid = 12345
    proc.communicate.return_value = (b"error output", b"")
    proc.returncode = 1
    runner.start.return_value = proc

    job = WorkflowJob(id="j2", workflow_name="test", context={})
    await worker._execute(job)

    assert job.status == JobStatus.FAILED
    assert job.result_success is False
    assert "error output" in job.result_error


@pytest.mark.asyncio
async def test_execute_timeout(worker_deps):
    queue, job_store, runner = worker_deps
    worker = Worker(0, queue, runner, job_store, default_timeout=1)

    proc = AsyncMock()
    proc.pid = 12345
    proc.communicate.side_effect = asyncio.TimeoutError
    proc.kill = MagicMock()
    proc.wait = AsyncMock()
    runner.start.return_value = proc

    job = WorkflowJob(id="j3", workflow_name="test", context={}, timeout=1)
    await worker._execute(job)

    assert job.status == JobStatus.TIMEOUT
    proc.kill.assert_called_once()


@pytest.mark.asyncio
async def test_execute_exception(worker_deps):
    queue, job_store, runner = worker_deps
    worker = Worker(0, queue, runner, job_store, default_timeout=30)

    runner.start.side_effect = RuntimeError("subprocess failed")

    job = WorkflowJob(id="j4", workflow_name="test", context={})
    await worker._execute(job)

    assert job.status == JobStatus.FAILED
    assert "subprocess failed" in job.result_error


@pytest.mark.asyncio
async def test_is_busy(worker_deps):
    queue, job_store, runner = worker_deps
    worker = Worker(0, queue, runner, job_store, default_timeout=30)
    assert worker.is_busy is False

    proc = AsyncMock()
    proc.pid = 1
    proc.communicate.return_value = (b"", b"")
    proc.returncode = 0
    runner.start.return_value = proc

    job = WorkflowJob(id="j5", workflow_name="test", context={})
    await worker._execute(job)
    assert worker.is_busy is False
