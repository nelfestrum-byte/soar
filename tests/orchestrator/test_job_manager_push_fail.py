from unittest.mock import AsyncMock, MagicMock

import pytest

from orchestrator.core.job_manager import JobManager
from orchestrator.models.job import JobStatus


@pytest.mark.asyncio
async def test_enqueue_marks_job_failed_on_push_error():
    queue = AsyncMock()
    queue.push.side_effect = ConnectionError("Redis down")
    job_store = AsyncMock()
    runner = MagicMock()

    jm = JobManager(queue=queue, job_store=job_store, runner=runner, log_dir="/tmp/logs")
    jm._metas = {"test_wf": MagicMock(
        name="test_wf", type="manual", enabled=True,
        concurrency=MagicMock(value="allow"), timeout=None
    )}

    with pytest.raises(ConnectionError):
        await jm.enqueue("test_wf", {}, "test")

    # Job should be saved to store (at least twice: CREATED + FAILED)
    assert job_store.save.call_count >= 2
    # Last save should have status FAILED
    last_save_call = job_store.save.call_args_list[-1][0][0]
    assert last_save_call.status == JobStatus.FAILED
    assert last_save_call.result_error is not None
