import os
from contextlib import asynccontextmanager
from pathlib import Path

import yaml
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from loguru import logger

from orchestrator.api import (
    actions_router,
    connectors_router,
    files_router,
    jobs_router,
    logs_router,
    status_router,
    webhooks_router,
    workflow_files_router,
    workflows_router,
)
from orchestrator.config import load_config
from orchestrator.core.git_manager import GitManager
from orchestrator.core.job_manager import JobManager
from orchestrator.core.queue.memory import InMemoryQueue
from orchestrator.core.queue.redis_queue import RedisQueue
from orchestrator.core.scheduler import OrchestratorScheduler
from orchestrator.core.subprocess_runner import SubprocessRunner
from orchestrator.core.worker_pool import WorkerPool
from orchestrator.models import ConcurrencyPolicy
from orchestrator.models.workflow_meta import WorkflowMeta
from orchestrator.store.job_store import JobStore


def create_queue(config):
    if config.queue.backend == "redis":
        return RedisQueue(config.queue.redis_url)
    return InMemoryQueue()


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

    queue = create_queue(config)
    job_store = JobStore(keep_completed=config.jobs.keep_completed)
    runner = SubprocessRunner()
    git = GitManager(
        repo_path=config.git.workflows_repo,
        author_name=config.git.author_name,
        author_email=config.git.author_email,
    )
    await git.ensure_repo()

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


app.include_router(workflows_router)
app.include_router(workflow_files_router)
app.include_router(files_router)
app.include_router(actions_router)
app.include_router(connectors_router)
app.include_router(jobs_router)
app.include_router(webhooks_router)
app.include_router(logs_router)
app.include_router(status_router)
