import asyncio
import json
import os
import tempfile
from unittest.mock import AsyncMock, MagicMock

import pytest

from orchestrator.core.queue.memory import InMemoryQueue
from orchestrator.core.worker import Worker
from orchestrator.models.job import JobStatus, WorkflowJob
from orchestrator.store.job_store import JobStore


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


@pytest.mark.asyncio
async def test_execute_result_data_parsed(worker_deps, tmp_path):
    """B4: result_data should be populated from last JSON line of log file."""
    queue, job_store, runner = worker_deps
    worker = Worker(0, queue, runner, job_store, default_timeout=30)

    log_file = tmp_path / "job.log"
    log_file.write_text('some log line\n{"success": true, "data": {"foo": 1}, "error": null}\n')

    proc = AsyncMock()
    proc.pid = 42
    proc.communicate.return_value = (b"", b"")
    proc.returncode = 0
    runner.start.return_value = proc

    job = WorkflowJob(id="j_rd", workflow_name="test", context={}, log_path=str(log_file))
    await worker._execute(job)

    assert job.status == JobStatus.COMPLETED
    assert job.result_data == {"foo": 1}
    assert job.result_error is None


@pytest.mark.asyncio
async def test_execute_result_data_non_json_ignored(worker_deps, tmp_path):
    """B4: non-JSON last line must not crash — result_data stays None."""
    queue, job_store, runner = worker_deps
    worker = Worker(0, queue, runner, job_store, default_timeout=30)

    log_file = tmp_path / "job.log"
    log_file.write_text("Workflow finished successfully\n")

    proc = AsyncMock()
    proc.pid = 43
    proc.communicate.return_value = (b"", b"")
    proc.returncode = 0
    runner.start.return_value = proc

    job = WorkflowJob(id="j_rd2", workflow_name="test", context={}, log_path=str(log_file))
    await worker._execute(job)

    assert job.status == JobStatus.COMPLETED
    assert job.result_data is None


@pytest.mark.asyncio
async def test_execute_cancel_not_overwritten_by_failed(worker_deps):
    """B1: if job is cancelled while process runs, status must stay CANCELLED after communicate()."""
    queue, job_store, runner = worker_deps
    worker = Worker(0, queue, runner, job_store, default_timeout=30)

    proc = AsyncMock()
    proc.pid = 99

    async def communicate_side_effect():
        # Simulate cancel() being called while process runs
        job.status = JobStatus.CANCELLED
        await job_store.save(job)
        return (b"", b"")

    proc.communicate = communicate_side_effect
    proc.returncode = 1  # non-zero exit (as if killed)
    runner.start.return_value = proc

    job = WorkflowJob(id="j_cancel", workflow_name="test", context={})
    await job_store.save(job)
    await worker._execute(job)

    saved = await job_store.get("j_cancel")
    assert saved is not None
    assert saved.status == JobStatus.CANCELLED
