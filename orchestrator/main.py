import os
import shutil
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from pathlib import Path

# Config must load — and the table prefix must be applied — before any module below
# imports orchestrator.auth.models / orchestrator.store.models: __tablename__ is fixed
# at class-definition (import) time (see orchestrator/db/base.py::configure_table_prefix).
from orchestrator.config import load_config  # noqa: E402
from orchestrator.db.base import configure_table_prefix  # noqa: E402

_startup_config_path = os.environ.get("SOAR_CONFIG", "config.yaml")
_startup_config = load_config(_startup_config_path)
configure_table_prefix(_startup_config.database.table_prefix)

import yaml  # noqa: E402
from fastapi import FastAPI, Request  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
from loguru import logger  # noqa: E402

from orchestrator.api import (  # noqa: E402
    actions_router,
    connectors_router,
    jobs_router,
    logs_router,
    status_router,
    tools_router,
    webhooks_router,
    workflows_router,
)
from orchestrator.api.transfer import router as transfer_router  # noqa: E402
from orchestrator.auth.router import router as auth_router  # noqa: E402
from orchestrator.core.git_manager import GitManager  # noqa: E402
from orchestrator.core.job_manager import JobManager  # noqa: E402
from orchestrator.core.queue.memory import InMemoryQueue  # noqa: E402
from orchestrator.core.queue.redis_queue import RedisQueue  # noqa: E402
from orchestrator.core.scheduler import OrchestratorScheduler  # noqa: E402
from orchestrator.core.subprocess_runner import SubprocessRunner  # noqa: E402
from orchestrator.core.worker_pool import WorkerPool  # noqa: E402
from orchestrator.db.session import get_session_factory, init_db, init_engine  # noqa: E402
from orchestrator.models import ConcurrencyPolicy  # noqa: E402
from orchestrator.models.workflow_meta import WorkflowMeta  # noqa: E402
from orchestrator.store.base import AbstractJobStore  # noqa: E402
from orchestrator.store.job_store import InMemoryJobStore  # noqa: E402
from orchestrator.store.sql_job_store import SQLJobStore  # noqa: E402

_SOAR_PKG = Path(__file__).resolve().parent.parent / "soar"


def seed_defaults(config):
    """Copy built-in defaults to data dirs if missing (replaces Dockerfile build-time cp)."""
    for d in (config.soar.connectors_dir, config.soar.workflows_dir, config.soar.actions_dir):
        os.makedirs(d, exist_ok=True)

    builtin_connectors = _SOAR_PKG / "connectors"
    if builtin_connectors.is_dir():
        for item in builtin_connectors.iterdir():
            if item.is_dir() and not item.name.startswith("_"):
                dest = Path(config.soar.connectors_dir) / item.name
                if not dest.exists():
                    shutil.copytree(item, dest)

    for src_dir, dest_dir, exclude in [
        (_SOAR_PKG / "workflows", config.soar.workflows_dir, {"__init__.py", "base.py"}),
        (_SOAR_PKG / "actions", config.soar.actions_dir, {"__init__.py"}),
    ]:
        if src_dir.is_dir():
            for f in src_dir.iterdir():
                if f.is_file() and f.suffix == ".py" and f.name not in exclude:
                    dest = Path(dest_dir) / f.name
                    if not dest.exists():
                        shutil.copy2(f, dest)


def create_queue(config):
    if config.queue.backend == "redis":
        return RedisQueue(
            config.queue.redis_url,
            max_connections=config.queue.redis_max_connections,
            push_timeout=config.queue.redis_push_timeout,
            pop_timeout=config.queue.redis_pop_timeout,
        )
    return InMemoryQueue()


def create_job_store(config) -> AbstractJobStore:
    if config.jobs.persistence == "sql":
        return SQLJobStore(get_session_factory())
    return InMemoryJobStore(keep_completed=config.jobs.keep_completed)


def load_workflow_metas(config) -> list[WorkflowMeta]:
    state_path = Path(config.soar.workflows_dir).parent / "orchestrator_state.yaml"
    state: dict = {}
    if state_path.exists():
        with open(state_path) as f:
            state = yaml.safe_load(f) or {}

    state_workflows = state.get("workflows", {})

    soar_metas = []
    try:
        from soar.workflows import workflows as wf_registry
        wf_registry.init(external_dir=config.soar.workflows_dir)
        for wf_info in wf_registry.list():
            name = wf_info["name"]
            wf_type = wf_info["type"]
            enabled = state_workflows.get(name, "enabled")
            enabled = enabled == "enabled" if isinstance(enabled, str) else bool(enabled)

            meta = WorkflowMeta(
                name=name,
                type=wf_type,
                enabled=enabled,
                schedule=wf_info.get("schedule"),
                interval=wf_info.get("interval"),
                path=wf_info.get("path"),
                token=wf_info.get("token"),
                concurrency=ConcurrencyPolicy.ALLOW if wf_type == "webhook" else ConcurrencyPolicy.FORBID,
            )
            soar_metas.append(meta)
    except ImportError:
        pass

    for name, enabled_str in state_workflows.items():
        if any(m.name == name for m in soar_metas):
            continue
        enabled = enabled_str == "enabled" if isinstance(enabled_str, str) else bool(enabled_str)
        soar_metas.append(WorkflowMeta(
            name=name,
            type="scheduled",
            enabled=enabled,
            concurrency=ConcurrencyPolicy.FORBID,
        ))

    return soar_metas


@asynccontextmanager
async def lifespan(app: FastAPI):
    config_path = os.environ.get("SOAR_CONFIG", "config.yaml")
    config = load_config(config_path)

    import sys
    logger.remove()
    logger.add(config.logging.file, level=config.logging.level)
    logger.add(sys.stderr, level=config.logging.level)

    if not config.auth.secret_key:
        logger.warning("auth.secret_key is not set — authentication is DISABLED, all requests treated as admin")

    seed_defaults(config)

    # Database
    init_engine(config.database.url, config.database.pool_size, config.database.max_overflow)
    await init_db()
    app.state.db_session_factory = get_session_factory()

    queue = create_queue(config)
    job_store = create_job_store(config)
    runner = SubprocessRunner()
    git = GitManager(
        repo_path=config.git.workflows_repo,
        author_name=config.git.author_name,
        author_email=config.git.author_email,
    )
    await git.ensure_repo()

    await job_store.recover_on_startup()

    job_manager = JobManager(
        queue=queue,
        job_store=job_store,
        runner=runner,
        log_dir=config.jobs.log_dir,
    )

    workflows = load_workflow_metas(config)
    job_manager.set_metas(workflows)

    pool = WorkerPool(
        count=config.workers.count,
        queue=queue,
        runner=runner,
        job_store=job_store,
        default_timeout=config.workers.default_timeout,
    )

    scheduler = OrchestratorScheduler(job_manager)

    app.state.job_manager = job_manager
    app.state.pool = pool
    app.state.scheduler = scheduler
    app.state.git = git
    app.state.config = config
    app.state.job_store = job_store
    app.state.queue = queue

    await pool.start()
    await scheduler.start(workflows)

    yield

    await scheduler.stop()
    await pool.stop()


app = FastAPI(title="SOAR Orchestrator", lifespan=lifespan)


class RateLimiter:
    def __init__(self, max_requests: int = 60, window: float = 60.0):
        self._requests: dict[str, list[float]] = defaultdict(list)
        self._max = max_requests
        self._window = window

    def is_allowed(self, key: str) -> bool:
        now = time.monotonic()
        self._requests[key] = [t for t in self._requests[key] if now - t < self._window]
        if len(self._requests[key]) >= self._max:
            return False
        self._requests[key].append(now)
        return True


# Use specific origins when credentials are involved (browsers reject "*" + credentials)
_cors_origins = _startup_config.auth.cors_origins if _startup_config.auth.cors_origins else ["*"]
_allow_credentials = bool(_startup_config.auth.cors_origins)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=_allow_credentials,
    allow_methods=["*"],
    allow_headers=["Authorization", "Content-Type", "X-Webhook-Token"],
)


@app.middleware("http")
async def limit_request_body(request: Request, call_next):
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > 5 * 1024 * 1024:
        return JSONResponse(status_code=413, content={"detail": "Request body too large"})
    if request.method in ("POST", "PUT", "PATCH"):
        body = await request.body()
        if len(body) > 5 * 1024 * 1024:
            return JSONResponse(status_code=413, content={"detail": "Request body too large"})
    response = await call_next(request)
    return response


rate_limiter = RateLimiter(max_requests=120, window=60.0)
login_rate_limiter = RateLimiter(max_requests=5, window=60.0)


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    client_ip = request.client.host if request.client else "unknown"

    config = getattr(request.app.state, "config", None)
    trusted_proxies = config.server.trusted_proxies if config else []
    if client_ip in trusted_proxies:
        forwarded_ip = (
            request.headers.get("X-Real-IP")
            or (request.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
        )
        if forwarded_ip:
            client_ip = forwarded_ip

    # Skip rate limiting for localhost/test clients
    if client_ip in ("testclient", "127.0.0.1", "::1"):
        return await call_next(request)

    # Stricter limit for login endpoint (brute-force protection)
    if request.url.path == "/auth/login":
        if not login_rate_limiter.is_allowed(client_ip):
            return JSONResponse(status_code=429, content={"detail": "Too many login attempts"})

    if not rate_limiter.is_allowed(client_ip):
        return JSONResponse(status_code=429, content={"detail": "Rate limit exceeded"})

    return await call_next(request)


app.include_router(auth_router)
app.include_router(workflows_router)
app.include_router(actions_router)
app.include_router(connectors_router)
app.include_router(jobs_router)
app.include_router(webhooks_router)
app.include_router(logs_router)
app.include_router(status_router)
app.include_router(transfer_router)
app.include_router(tools_router)
