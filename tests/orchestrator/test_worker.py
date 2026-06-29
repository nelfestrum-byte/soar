import pytest
from orchestrator.core.worker import Worker
from orchestrator.core.queue.memory import InMemoryQueue
from orchestrator.core.subprocess_runner import SubprocessRunner
from orchestrator.store.job_store import JobStore
from orchestrator.models.job import WorkflowJob, JobStatus


@pytest.mark.asyncio
async def test_worker_is_busy_default():
    queue = InMemoryQueue()
    runner = SubprocessRunner()
    store = JobStore()
    worker = Worker(0, queue, runner, store, default_timeout=300)
    assert worker.is_busy is False


@pytest.mark.asyncio
async def test_worker_stop():
    queue = InMemoryQueue()
    runner = SubprocessRunner()
    store = JobStore()
    worker = Worker(0, queue, runner, store, default_timeout=300)
    worker._running = True
    await worker.stop()
    assert worker._running is False
