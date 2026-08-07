import asyncio
import json
import os
import sys
import tempfile
from unittest.mock import AsyncMock, MagicMock

import pytest

from orchestrator.core.queue.memory import InMemoryQueue
from orchestrator.core.worker import Worker
from orchestrator.models import ConcurrencyPolicy
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
async def test_execute_bootstrap_failure_gives_real_traceback_not_process_failed(
    worker_deps, tmp_path, monkeypatch
):
    """[S1] end-to-end: a job whose subprocess dies during soar.runner's
    bootstrap phase (connector constructor missing a required config param —
    the report's 'missing api_key' scenario) must surface the actual
    traceback in job.result_error through the real Worker._execute() +
    SubprocessRunner path, not the "Process failed" literal that
    orchestrator/core/worker.py falls back to when stdout is empty. Before
    the soar/runner.py [S1] fix, the bootstrap crash was an unhandled
    exception whose traceback only reached stderr, leaving both stdout and
    the log file's last line without valid JSON — exactly this fallback."""
    from orchestrator.core import subprocess_runner as sr_module
    from orchestrator.core.subprocess_runner import SubprocessRunner

    connectors_dir = tmp_path / "connectors"
    conn_type_dir = connectors_dir / "qa_broken_ctor"
    conn_type_dir.mkdir(parents=True)
    (conn_type_dir / "qa_broken_ctor.py").write_text(
        "from soar.connectors.base import BaseConnector\n"
        "\n\n"
        "class QaBrokenCtor(BaseConnector):\n"
        "    def __init__(self, instance_name, api_key):\n"
        "        super().__init__(instance_name)\n"
        "        self.api_key = api_key\n",
        encoding="utf-8",
    )
    (conn_type_dir / "qa_broken_ctor.yml").write_text(
        "instances:\n"
        "  x: {}\n",
        encoding="utf-8",
    )

    workflow_file = tmp_path / "wf_uses_broken.py"
    workflow_file.write_text(
        "from soar.connectors.qa_broken_ctor import x\n"
        "from soar.workflows.base import ManualWorkflow\n"
        "\n\n"
        "class WfUsesBroken(ManualWorkflow):\n"
        "    def run(self, context):\n"
        "        return {}\n",
        encoding="utf-8",
    )

    full_config = {
        "soar": {
            "connectors_dir": str(connectors_dir),
            "workflows_dir": str(tmp_path / "workflows"),
            "actions_dir": str(tmp_path / "actions"),
            "tools_dir": "",
            "state_dir": str(tmp_path / "state"),
        },
    }
    monkeypatch.setattr(sr_module, "_load_full_config", lambda: full_config)
    monkeypatch.setattr(sr_module, "_CONTENT_PYTHON", sys.executable)

    # SubprocessRunner.start()'s safe_env_keys allowlist doesn't include
    # SystemRoot — on Windows, spawning python without it makes Winsock
    # init fail (WinError 10106) the moment anything imports asyncio (loguru
    # does, transitively, via soar/logger.py), unrelated to the [S1] fix
    # under test. Not a subprocess_runner.py bug worth fixing here (Linux/
    # Docker deploys never hit this) — worked around only for this real,
    # unmocked subprocess spawn by injecting it at the asyncio boundary.
    _real_create_subprocess_exec = asyncio.create_subprocess_exec

    async def _create_subprocess_exec_with_system_root(*args, **kwargs):
        env = kwargs.get("env")
        if env is not None:
            for key in ("SystemRoot", "SYSTEMROOT", "windir"):
                if key in os.environ and key not in env:
                    env[key] = os.environ[key]
        return await _real_create_subprocess_exec(*args, **kwargs)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _create_subprocess_exec_with_system_root)

    queue, job_store, _unused_runner = worker_deps
    real_runner = SubprocessRunner()
    worker = Worker(0, queue, real_runner, job_store, default_timeout=30)

    log_file = tmp_path / "job.log"
    job = WorkflowJob(
        id="j_bootstrap_fail",
        workflow_name="wf_uses_broken",
        context={},
        workflow_file=str(workflow_file),
        log_path=str(log_file),
    )

    await worker._execute(job)

    assert job.status == JobStatus.FAILED
    assert job.result_success is False
    assert job.result_error is not None
    assert job.result_error != "Process failed", (
        f"log contents: {log_file.read_text() if log_file.exists() else '<missing>'!r}"
    )
    assert "TypeError" in job.result_error
    assert "api_key" in job.result_error


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


@pytest.mark.asyncio
async def test_queue_policy_does_not_deadlock_on_sql_queue_self_claim(worker_deps):
    """M7: SQLQueue.pop() claims a job by setting its own row to RUNNING
    *before* handing it to the worker (unlike InMemoryQueue, which claims
    later inside _execute). For ConcurrencyPolicy.QUEUE this used to make the
    busy-wait `count_by_status(workflow_name, [RUNNING]) > 0` count the job
    against itself forever. Reproduce that pre-claimed state directly and
    assert _execute completes instead of spinning."""
    queue, job_store, runner = worker_deps
    worker = Worker(0, queue, runner, job_store, default_timeout=30)

    proc = AsyncMock()
    proc.pid = 55
    proc.communicate.return_value = (b"", b"")
    proc.returncode = 0
    runner.start.return_value = proc

    job = WorkflowJob(
        id="j_queue_self",
        workflow_name="queue_wf",
        context={},
        concurrency=ConcurrencyPolicy.QUEUE,
        status=JobStatus.RUNNING,  # already claimed by SQLQueue.pop() before _execute runs
    )
    await job_store.save(job)

    await asyncio.wait_for(worker._execute(job), timeout=5.0)

    assert job.status == JobStatus.COMPLETED


@pytest.mark.asyncio
async def test_execute_cleans_up_scoped_config_dir_on_success(worker_deps, tmp_path):
    """Privilege narrowing (docs/compose/specs/2026-07-30-privilege-
    narrowing-design.md [S2] item 4): the per-job scoped config directory
    SubprocessRunner.start() creates must be removed once the job is done,
    symmetric to _log_file's close()."""
    queue, job_store, runner = worker_deps
    worker = Worker(0, queue, runner, job_store, default_timeout=30)

    scoped_dir = tmp_path / "scoped-job-dir"
    scoped_dir.mkdir()
    (scoped_dir / "config.yaml").write_text("soar: {}\n")

    async def fake_start(job):
        job.scoped_config_dir = str(scoped_dir)
        proc = AsyncMock()
        proc.pid = 1
        proc.communicate.return_value = (b"", b"")
        proc.returncode = 0
        return proc

    runner.start.side_effect = fake_start

    job = WorkflowJob(id="j_scoped_ok", workflow_name="test", context={})
    await worker._execute(job)

    assert job.status == JobStatus.COMPLETED
    assert not scoped_dir.exists()


@pytest.mark.asyncio
async def test_execute_cleans_up_scoped_config_dir_on_timeout(worker_deps, tmp_path):
    queue, job_store, runner = worker_deps
    worker = Worker(0, queue, runner, job_store, default_timeout=1)

    scoped_dir = tmp_path / "scoped-job-dir-timeout"
    scoped_dir.mkdir()

    async def fake_start(job):
        job.scoped_config_dir = str(scoped_dir)
        proc = AsyncMock()
        proc.pid = 2
        proc.communicate.side_effect = asyncio.TimeoutError
        proc.kill = MagicMock()
        proc.wait = AsyncMock()
        return proc

    runner.start.side_effect = fake_start

    job = WorkflowJob(id="j_scoped_timeout", workflow_name="test", context={}, timeout=1)
    await worker._execute(job)

    assert job.status == JobStatus.TIMEOUT
    assert not scoped_dir.exists()


@pytest.mark.asyncio
async def test_execute_cleans_up_scoped_config_dir_on_exception(worker_deps, tmp_path):
    """Covers the case where runner.start() itself sets scoped_config_dir
    on the job and then raises before returning a proc — cleanup must
    still happen via the outer finally, not just the one guarding
    _log_file (which never runs in this path)."""
    queue, job_store, runner = worker_deps
    worker = Worker(0, queue, runner, job_store, default_timeout=30)

    scoped_dir = tmp_path / "scoped-job-dir-exc"
    scoped_dir.mkdir()

    async def fake_start(job):
        job.scoped_config_dir = str(scoped_dir)
        raise RuntimeError("subprocess failed to start")

    runner.start.side_effect = fake_start

    job = WorkflowJob(id="j_scoped_exc", workflow_name="test", context={})
    await worker._execute(job)

    assert job.status == JobStatus.FAILED
    assert not scoped_dir.exists()


@pytest.mark.asyncio
async def test_execute_no_scoped_config_dir_is_a_noop(worker_deps):
    """Jobs whose scoped_config_dir was never set (default None) must not
    make cleanup raise."""
    queue, job_store, runner = worker_deps
    worker = Worker(0, queue, runner, job_store, default_timeout=30)

    proc = AsyncMock()
    proc.pid = 3
    proc.communicate.return_value = (b"", b"")
    proc.returncode = 0
    runner.start.return_value = proc

    job = WorkflowJob(id="j_no_scoped", workflow_name="test", context={})
    await worker._execute(job)

    assert job.status == JobStatus.COMPLETED
