import pytest

from orchestrator.core.job_manager import JobManager
from orchestrator.core.queue.memory import InMemoryQueue
from orchestrator.core.scheduler import OrchestratorScheduler
from orchestrator.core.subprocess_runner import SubprocessRunner
from orchestrator.models.workflow_meta import WorkflowMeta
from orchestrator.store.job_store import JobStore


@pytest.fixture
def scheduler():
    queue = InMemoryQueue()
    runner = SubprocessRunner()
    store = JobStore()
    jm = JobManager(queue=queue, job_store=store, runner=runner, log_dir="/tmp/logs")
    return OrchestratorScheduler(jm)


@pytest.mark.asyncio
async def test_scheduler_start_empty(scheduler):
    await scheduler.start([])
    assert len(scheduler._jobs) == 0


@pytest.mark.asyncio
async def test_scheduler_start_with_scheduled(scheduler):
    metas = [
        WorkflowMeta(name="wf1", type="scheduled", enabled=True, schedule="*/10 * * * *"),
        WorkflowMeta(name="wf2", type="manual", enabled=True),
    ]
    await scheduler.start(metas)
    assert len(scheduler._jobs) == 1
    assert "wf1" in scheduler._jobs


@pytest.mark.asyncio
async def test_scheduler_reload(scheduler):
    metas = [
        WorkflowMeta(name="wf1", type="scheduled", enabled=True, schedule="*/10 * * * *"),
    ]
    await scheduler.start(metas)
    assert len(scheduler._jobs) == 1

    await scheduler.reload([])
    assert len(scheduler._jobs) == 0


def test_scheduler_next_runs_empty(scheduler):
    result = scheduler.next_runs()
    assert result == []


@pytest.mark.asyncio
async def test_scheduler_stop(scheduler):
    await scheduler.start([])
    await scheduler.stop()
