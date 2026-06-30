import pytest

from orchestrator.core.queue.memory import InMemoryQueue
from orchestrator.core.subprocess_runner import SubprocessRunner
from orchestrator.core.worker_pool import WorkerPool
from orchestrator.store.job_store import JobStore


def test_worker_pool_init():
    queue = InMemoryQueue()
    runner = SubprocessRunner()
    store = JobStore()
    pool = WorkerPool(count=4, queue=queue, runner=runner, job_store=store, default_timeout=300)
    assert len(pool._workers) == 4


def test_worker_pool_status():
    queue = InMemoryQueue()
    runner = SubprocessRunner()
    store = JobStore()
    pool = WorkerPool(count=4, queue=queue, runner=runner, job_store=store, default_timeout=300)
    status = pool.status
    assert status["total"] == 4
    assert status["busy"] == 0
    assert status["idle"] == 4


@pytest.mark.asyncio
async def test_worker_pool_start_stop():
    queue = InMemoryQueue()
    runner = SubprocessRunner()
    store = JobStore()
    pool = WorkerPool(count=2, queue=queue, runner=runner, job_store=store, default_timeout=300)
    await pool.start()
    assert len(pool._tasks) == 2
    await pool.stop()
