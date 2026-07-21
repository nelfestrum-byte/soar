"""Covers spec [S4]: previously-silent auth/rate-limit/webhook failures must
now emit a logger.warning with useful bound fields (not asserting on message
wording — that's brittle, assert on the fact + fields instead)."""
import time

import pytest
from httpx import ASGITransport, AsyncClient
from loguru import logger
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from orchestrator.auth.dependencies import get_current_user
from orchestrator.auth.models import ApiKey, RefreshToken, User  # noqa: F401 — registers tables
from orchestrator.auth.service import create_access_token
from orchestrator.config import AuthConfig, OrchestratorConfig
from orchestrator.core.job_manager import JobManager
from orchestrator.core.queue.memory import InMemoryQueue
from orchestrator.core.scheduler import OrchestratorScheduler
from orchestrator.core.subprocess_runner import SubprocessRunner
from orchestrator.core.worker_pool import WorkerPool
from orchestrator.db.base import Base
from orchestrator.db.session import get_db
from orchestrator.main import app, login_rate_limiter, rate_limiter
from orchestrator.models import ConcurrencyPolicy
from orchestrator.models.workflow_meta import WorkflowMeta
from orchestrator.store.job_store import JobStore

_DB_URL = "sqlite+aiosqlite:///:memory:"
_SECRET = "test-secret-key-exactly-32chars!!"


@pytest.fixture
def log_records():
    records = []

    def sink(message):
        records.append(message.record)

    handler_id = logger.add(sink, level="DEBUG")
    yield records
    logger.remove(handler_id)


@pytest.fixture
async def db_factory():
    engine = create_async_engine(_DB_URL, connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
async def client(db_factory, tmp_path):
    app.dependency_overrides.pop(get_current_user, None)

    async def _get_db():
        async with db_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _get_db

    config = OrchestratorConfig()
    config.auth = AuthConfig(secret_key=_SECRET)

    queue = InMemoryQueue()
    job_store = JobStore()
    runner = SubprocessRunner()
    job_manager = JobManager(queue=queue, job_store=job_store, runner=runner, log_dir=str(tmp_path))
    job_manager.set_metas([WorkflowMeta(
        name="TestWebhook", type="webhook", enabled=True,
        path="/webhook/test", token="secret-token-abc",
        concurrency=ConcurrencyPolicy.ALLOW,
    )])
    pool = WorkerPool(count=1, queue=queue, runner=runner, job_store=job_store, default_timeout=30)
    scheduler = OrchestratorScheduler(job_manager)

    app.state.job_manager = job_manager
    app.state.pool = pool
    app.state.scheduler = scheduler
    app.state.git = None
    app.state.config = config
    app.state.job_store = job_store
    app.state.queue = queue
    app.state.db_session_factory = db_factory

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

    app.dependency_overrides.pop(get_db, None)


def _warnings(records: list, message: str) -> list:
    return [r for r in records if r["message"] == message]


async def test_missing_authorization_header_logs_warning(client, log_records):
    resp = await client.get("/status")
    assert resp.status_code == 401
    assert len(_warnings(log_records, "auth.unauthenticated")) == 1


async def test_garbage_bearer_token_logs_warning(client, log_records):
    resp = await client.get("/status", headers={"Authorization": "Bearer not-a-real-token"})
    assert resp.status_code == 401
    assert len(_warnings(log_records, "auth.invalid_credentials")) == 1


async def test_wrong_role_logs_forbidden_warning(client, log_records):
    token = create_access_token(1, "viewer", _SECRET, 1800, "HS256")
    resp = await client.post(
        "/workflows/reload", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 403
    warnings = _warnings(log_records, "auth.forbidden")
    assert len(warnings) == 1
    assert warnings[0]["extra"]["role"] == "viewer"


async def test_login_rate_limit_logs_warning(client, log_records):
    # ASGITransport's client_ip is 127.0.0.1, which is unconditionally skip-listed —
    # force a forwarded IP via a trusted proxy, mirroring test_rate_limiter.py.
    app.state.config.server.trusted_proxies = ["127.0.0.1"]
    login_rate_limiter._requests["9.9.9.9"] = [time.monotonic()] * login_rate_limiter._max
    try:
        resp = await client.post(
            "/auth/login", json={"username": "x", "password": "y"},
            headers={"X-Real-IP": "9.9.9.9"},
        )
        assert resp.status_code == 429
        assert len(_warnings(log_records, "auth.login_rate_limited")) == 1
    finally:
        login_rate_limiter._requests.pop("9.9.9.9", None)


async def test_general_rate_limit_logs_warning(client, log_records):
    app.state.config.server.trusted_proxies = ["127.0.0.1"]
    rate_limiter._requests["9.9.9.9"] = [time.monotonic()] * rate_limiter._max
    try:
        token = create_access_token(1, "admin", _SECRET, 1800, "HS256")
        resp = await client.get(
            "/status", headers={"Authorization": f"Bearer {token}", "X-Real-IP": "9.9.9.9"},
        )
        assert resp.status_code == 429
        assert len(_warnings(log_records, "rate_limited")) == 1
    finally:
        rate_limiter._requests.pop("9.9.9.9", None)


async def test_webhook_invalid_token_logs_warning(client, log_records):
    resp = await client.post(
        "/webhooks/TestWebhook", json={}, headers={"X-Webhook-Token": "wrong"},
    )
    assert resp.status_code == 403
    warnings = _warnings(log_records, "webhook.invalid_token")
    assert len(warnings) == 1
    assert warnings[0]["extra"]["workflow_name"] == "TestWebhook"
