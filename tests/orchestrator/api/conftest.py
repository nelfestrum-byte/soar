import os

import pytest
from unittest.mock import AsyncMock

from orchestrator.auth.dependencies import CurrentUser, get_current_user
from orchestrator.config import OrchestratorConfig
from orchestrator.core.job_manager import JobManager
from orchestrator.core.queue.memory import InMemoryQueue
from orchestrator.core.scheduler import OrchestratorScheduler
from orchestrator.core.subprocess_runner import SubprocessRunner
from orchestrator.core.worker_pool import WorkerPool
from orchestrator.main import app
from orchestrator.store.job_store import JobStore


def _mock_admin() -> CurrentUser:
    return CurrentUser(id=1, role="admin", type="user", username="test_admin")


@pytest.fixture(autouse=True)
def setup_app_state(tmp_path):
    # Bypass auth for existing tests: every request is treated as admin
    app.dependency_overrides[get_current_user] = _mock_admin

    queue = InMemoryQueue()
    job_store = JobStore()
    runner = SubprocessRunner()
    git = AsyncMock()
    git.commit.return_value = "abc1234"
    config = OrchestratorConfig()
    config.soar.workflows_dir = str(tmp_path / "workflows")
    config.soar.actions_dir = str(tmp_path / "actions")
    config.soar.connectors_dir = str(tmp_path / "connectors")

    os.makedirs(config.soar.workflows_dir, exist_ok=True)
    os.makedirs(config.soar.actions_dir, exist_ok=True)
    os.makedirs(config.soar.connectors_dir, exist_ok=True)

    job_manager = JobManager(
        queue=queue,
        job_store=job_store,
        runner=runner,
        log_dir=str(tmp_path / "logs"),
    )
    job_manager.set_metas([])

    pool = WorkerPool(
        count=2, queue=queue, runner=runner,
        job_store=job_store, default_timeout=300,
    )
    scheduler = OrchestratorScheduler(job_manager)

    app.state.job_manager = job_manager
    app.state.pool = pool
    app.state.scheduler = scheduler
    app.state.git = git
    app.state.config = config
    app.state.job_store = job_store
    app.state.queue = queue

    yield

    app.dependency_overrides.pop(get_current_user, None)
