from unittest.mock import AsyncMock, MagicMock

import pytest

from orchestrator.core.queue.memory import InMemoryQueue
from orchestrator.core.worker import Worker
from orchestrator.models.job import WorkflowJob
from orchestrator.store.job_store import JobStore


@pytest.fixture
def worker_deps():
    queue = InMemoryQueue()
    job_store = JobStore()
    runner = MagicMock()
    runner.start = AsyncMock()
    return queue, job_store, runner


def _proc(pid=1, out=b"", rc=0):
    proc = AsyncMock()
    proc.pid = pid
    proc.communicate.return_value = (out, b"")
    proc.returncode = rc
    return proc


@pytest.mark.asyncio
async def test_worker_records_audit_events_from_job_log(worker_deps, tmp_path):
    queue, job_store, runner = worker_deps

    session = AsyncMock()
    session.__aenter__.return_value = session
    session.__aexit__.return_value = False
    db_session_factory = MagicMock(return_value=session)

    worker = Worker(0, queue, runner, job_store, default_timeout=30, db_session_factory=db_session_factory)

    log_file = tmp_path / "job.log"
    log_file.write_text(
        "\n".join(
            [
                "SOAR_AUDIT_EVENT connector.call target=a.b.c args=() kwargs={} duration_ms=1 outcome=ok job_id=j1",
                "SOAR_AUDIT_EVENT connector.call target=d.e.f args=() kwargs={} duration_ms=2 outcome=ok job_id=j1",
                '{"success": true, "data": {}, "error": null}',
            ]
        )
    )

    runner.start.return_value = _proc()
    job = WorkflowJob(id="j1", workflow_name="test_wf", context={}, log_path=str(log_file))

    from unittest.mock import patch

    with patch("orchestrator.core.worker.audit_service.record_job_event", new=AsyncMock()) as mock_record:
        await worker._execute(job)

    assert mock_record.call_count == 2
    call_targets = [c.kwargs.get("resource_id") for c in mock_record.call_args_list]
    assert call_targets == ["a.b.c", "d.e.f"]


@pytest.mark.asyncio
async def test_worker_no_audit_events_no_record_calls(worker_deps, tmp_path):
    queue, job_store, runner = worker_deps

    session = AsyncMock()
    session.__aenter__.return_value = session
    session.__aexit__.return_value = False
    db_session_factory = MagicMock(return_value=session)

    worker = Worker(0, queue, runner, job_store, default_timeout=30, db_session_factory=db_session_factory)

    log_file = tmp_path / "job.log"
    log_file.write_text('{"success": true, "data": {}, "error": null}\n')

    runner.start.return_value = _proc()
    job = WorkflowJob(id="j2", workflow_name="test_wf", context={}, log_path=str(log_file))

    from unittest.mock import patch

    with patch("orchestrator.core.worker.audit_service.record_job_event", new=AsyncMock()) as mock_record:
        await worker._execute(job)

    mock_record.assert_not_called()


@pytest.mark.asyncio
async def test_worker_without_db_session_factory_skips_audit_parsing(worker_deps, tmp_path):
    queue, job_store, runner = worker_deps
    worker = Worker(0, queue, runner, job_store, default_timeout=30)  # db_session_factory defaults to None

    log_file = tmp_path / "job.log"
    log_file.write_text(
        "SOAR_AUDIT_EVENT connector.call target=a.b.c args=() kwargs={} duration_ms=1 outcome=ok job_id=j3\n"
        '{"success": true, "data": {}, "error": null}\n'
    )

    runner.start.return_value = _proc()
    job = WorkflowJob(id="j3", workflow_name="test_wf", context={}, log_path=str(log_file))

    await worker._execute(job)  # must not raise

    assert job.status.value == "completed"
