import pytest

from orchestrator.core.job_manager import JobAlreadyRunningError, JobManager, WorkflowDisabledError
from orchestrator.core.queue.memory import InMemoryQueue
from orchestrator.core.subprocess_runner import SubprocessRunner
from orchestrator.models import ConcurrencyPolicy, JobStatus
from orchestrator.models.workflow_meta import WorkflowMeta
from orchestrator.store.job_store import JobStore


@pytest.fixture
def job_manager():
    queue = InMemoryQueue()
    runner = SubprocessRunner()
    store = JobStore()
    jm = JobManager(queue=queue, job_store=store, runner=runner, log_dir="/tmp/test_logs")
    metas = [
        WorkflowMeta(
            name="test_wf",
            type="manual",
            enabled=True,
            concurrency=ConcurrencyPolicy.FORBID,
        ),
        WorkflowMeta(
            name="disabled_wf",
            type="manual",
            enabled=False,
        ),
        WorkflowMeta(
            name="scheduled_wf",
            type="scheduled",
            enabled=True,
            schedule="*/10 * * * *",
        ),
    ]
    jm.set_metas(metas)
    return jm


@pytest.mark.asyncio
async def test_job_manager_enqueue(job_manager):
    job = await job_manager.enqueue("test_wf", context={"key": "value"}, triggered_by="user")
    assert job.workflow_name == "test_wf"
    assert job.context == {"key": "value"}
    assert job.triggered_by == "user"
    assert job.status == JobStatus.PENDING


@pytest.mark.asyncio
async def test_job_manager_enqueue_disabled(job_manager):
    with pytest.raises(WorkflowDisabledError):
        await job_manager.enqueue("disabled_wf", context={}, triggered_by="user")


@pytest.mark.asyncio
async def test_job_manager_enqueue_not_found(job_manager):
    with pytest.raises(ValueError, match="not found"):
        await job_manager.enqueue("nonexistent", context={}, triggered_by="user")


@pytest.mark.asyncio
async def test_job_manager_cancel(job_manager):
    job = await job_manager.enqueue("test_wf", context={}, triggered_by="user")
    cancelled = await job_manager.cancel(job.id)
    assert cancelled.status == JobStatus.CANCELLED
    assert cancelled.finished_at is not None


@pytest.mark.asyncio
async def test_job_manager_cancel_not_found(job_manager):
    with pytest.raises(ValueError, match="not found"):
        await job_manager.cancel("nonexistent")


@pytest.mark.asyncio
async def test_job_manager_concurrency_forbid(job_manager):
    await job_manager.enqueue("test_wf", context={}, triggered_by="user")
    with pytest.raises(JobAlreadyRunningError):
        await job_manager.enqueue("test_wf", context={}, triggered_by="user")


def test_job_manager_list_metas(job_manager):
    """B7: list_metas() must return all workflow meta objects."""
    metas = job_manager.list_metas()
    names = {m.name for m in metas}
    assert "test_wf" in names
    assert "disabled_wf" in names
    assert "scheduled_wf" in names


def test_job_manager_get_meta_existing(job_manager):
    """B7: get_meta() returns the correct meta for known workflow."""
    meta = job_manager.get_meta("test_wf")
    assert meta is not None
    assert meta.name == "test_wf"
    assert meta.enabled is True


def test_job_manager_get_meta_missing(job_manager):
    """B7: get_meta() returns None for unknown workflow."""
    assert job_manager.get_meta("nonexistent") is None
