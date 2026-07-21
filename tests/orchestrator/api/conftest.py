import os
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from orchestrator.auth.dependencies import CurrentUser, get_current_user
from orchestrator.config import OrchestratorConfig
from orchestrator.core.job_manager import JobManager
from orchestrator.core.queue.memory import InMemoryQueue
from orchestrator.core.scheduler import OrchestratorScheduler
from orchestrator.core.subprocess_runner import SubprocessRunner
from orchestrator.core.worker_pool import WorkerPool
from orchestrator.db.base import Base
from orchestrator.db.session import get_db
from orchestrator.main import app
from orchestrator.store.job_store import JobStore

_DB_URL = "sqlite+aiosqlite:///:memory:"


def _mock_admin() -> CurrentUser:
    return CurrentUser(id=1, role="admin", type="user", username="test_admin")


@pytest.fixture(autouse=True)
async def setup_app_state(tmp_path):
    # Bypass auth for existing tests: every request is treated as admin
    app.dependency_overrides[get_current_user] = _mock_admin

    # In-memory DB so routes that write audit_log rows (Depends(get_db)) work
    # without needing a full auth setup — mirrors test_auth_api.py's db_engine.
    engine = create_async_engine(_DB_URL, connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    db_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def _get_db():
        async with db_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _get_db

    queue = InMemoryQueue()
    job_store = JobStore()
    runner = SubprocessRunner()
    git = AsyncMock()
    git.commit.return_value = "abc1234"
    config = OrchestratorConfig()
    config.soar.workflows_dir = str(tmp_path / "workflows")
    config.soar.actions_dir = str(tmp_path / "actions")
    config.soar.connectors_dir = str(tmp_path / "connectors")
    config.soar.tools_dir = str(tmp_path / "tools")

    os.makedirs(config.soar.workflows_dir, exist_ok=True)
    os.makedirs(config.soar.actions_dir, exist_ok=True)
    os.makedirs(config.soar.connectors_dir, exist_ok=True)
    os.makedirs(config.soar.tools_dir, exist_ok=True)

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
    app.state.db_session_factory = db_factory

    yield

    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(get_db, None)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()
