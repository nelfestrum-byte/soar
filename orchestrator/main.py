import os
import secrets
import time
import uuid
from collections import defaultdict
from collections.abc import Iterator
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

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
from loguru import logger  # noqa: E402

from orchestrator.api import (  # noqa: E402
    actions_router,
    connectors_router,
    jobs_router,
    logs_router,
    packs_router,
    prompts_router,
    runtime_router,
    status_router,
    tools_router,
    webhooks_router,
    workflows_router,
)
from orchestrator.api.audit import router as audit_router  # noqa: E402
from orchestrator.api.transfer import router as transfer_router  # noqa: E402
from orchestrator.auth.router import router as auth_router  # noqa: E402
from orchestrator.core.git_manager import GitManager  # noqa: E402
from orchestrator.core.introspect import parse_workflow_meta  # noqa: E402
from orchestrator.core.job_manager import JobManager  # noqa: E402
from orchestrator.core.net import resolve_client_ip  # noqa: E402
from orchestrator.core.pack_install import (  # noqa: E402
    apply_install_dir,
    check_dependencies,
    check_runtime_compat,
    plan_install,
    read_manifest_from_dir,
    read_marker,
)
from orchestrator.core.queue.memory import InMemoryQueue  # noqa: E402
from orchestrator.core.queue.redis_queue import RedisQueue  # noqa: E402
from orchestrator.core.queue.sql_queue import SQLQueue  # noqa: E402
from orchestrator.core.scheduler import OrchestratorScheduler  # noqa: E402
from orchestrator.core.subprocess_runner import SubprocessRunner, resolve_content_python  # noqa: E402
from orchestrator.core.worker_pool import WorkerPool  # noqa: E402
from orchestrator.core.workflow_state import load_state, parse_enabled, parse_token, save_state  # noqa: E402
from orchestrator.db.session import get_session_factory, init_db, init_engine  # noqa: E402
from orchestrator.models import ConcurrencyPolicy  # noqa: E402
from orchestrator.models.workflow_meta import WorkflowMeta  # noqa: E402
from orchestrator.store.base import AbstractJobStore  # noqa: E402
from orchestrator.store.job_store import InMemoryJobStore  # noqa: E402
from orchestrator.store.sql_job_store import SQLJobStore  # noqa: E402
from soar.runtime_contract import CONTRACT, RUNTIME_VERSION  # noqa: E402

_SOAR_PKG = Path(__file__).resolve().parent.parent / "soar"
_LOG_FORMAT = "{time:YYYY-MM-DD HH:mm:ss} | {level} | {name} | {message} | {extra}"


def seed_defaults(config):
    """Ensures the data dirs exist. Connector seeding is
    seed_connector_pack() below (Phase 3, docs/compose/specs/2026-07-30-
    content-as-contentpack-design.md [S8]) — the 24 built-in connectors no
    longer live in soar/connectors/ to copy from. The old workflows/actions
    shutil.copy2 branches are gone too: soar/workflows/ and soar/actions/
    only ever contained __init__.py/base.py, both excluded from that copy
    — it copied nothing, dead code (see the plan's section 5)."""
    for d in (config.soar.connectors_dir, config.soar.workflows_dir, config.soar.actions_dir):
        os.makedirs(d, exist_ok=True)


def seed_connector_pack(config) -> None:
    """Installs the base connector content-pack (SOAR_BASE_PACK_PATH, default
    /app/base-pack — baked into the image at build time, never fetched over
    the network, air-gap-safe) via the same pack_install pipeline `soarctl
    content install` / `POST /connectors/pack/install` use.

    Runs on every startup, not only when connectors_dir is empty:
    plan_install is idempotent (a connector already at the pack's version
    and untouched on disk lands in "unchanged", a no-op), so a newer
    image's base pack reaches an existing installation the next time the
    container starts (`soarctl update`) instead of only on a pack's first
    install — closes E4 (docs/concepts/ENTITY-MODEL.md): the old
    shutil.copytree-based seed_defaults() only ever ran once, when
    connectors_dir didn't exist yet, so new connectors added in a later
    release never reached an existing instance."""
    os.makedirs(config.soar.connectors_dir, exist_ok=True)
    base_pack_path = os.environ.get("SOAR_BASE_PACK_PATH", "/app/base-pack")
    pack_dir = Path(base_pack_path)
    if not (pack_dir / "manifest.yaml").is_file():
        logger.debug(f"No base pack manifest at {base_pack_path} — skipping connector pack seed")
        return

    try:
        manifest = read_manifest_from_dir(str(pack_dir))
        check_runtime_compat(manifest, RUNTIME_VERSION)
    except ValueError as e:
        logger.error(f"Base pack at {base_pack_path} is not installable: {e} — connectors_dir left as-is")
        return

    missing = check_dependencies(manifest, CONTRACT)
    if missing:
        logger.error(
            f"Base pack declares imports not guaranteed by the runtime contract: {missing} "
            "— skipping connector pack seed"
        )
        return

    marker = read_marker(config.soar.connectors_dir)
    plan = plan_install(manifest, marker, config.soar.connectors_dir)
    written = apply_install_dir(plan, str(pack_dir), config.soar.connectors_dir, manifest)
    if written["new"] or written["update"]:
        logger.info(f"Connector pack seed: installed {written}")
    if plan["skip_modified"]:
        skipped = [c["name"] for c in plan["skip_modified"]]
        logger.warning(f"Connector pack seed: left modified connectors untouched: {skipped}")


def create_queue(config):
    if config.queue.backend == "redis":
        return RedisQueue(
            config.queue.redis_url,
            max_connections=config.queue.redis_max_connections,
            push_timeout=config.queue.redis_push_timeout,
            pop_timeout=config.queue.redis_pop_timeout,
        )
    if config.queue.backend == "sql":
        if config.jobs.persistence != "sql":
            raise ValueError(
                "queue.backend: sql requires jobs.persistence: sql — "
                "SQLQueue reads/writes the same workflow_jobs table as JobStore"
            )
        return SQLQueue(get_session_factory(), poll_interval=config.queue.sql_poll_interval)
    return InMemoryQueue()


def create_job_store(config) -> AbstractJobStore:
    if config.jobs.persistence == "sql":
        return SQLJobStore(get_session_factory())
    return InMemoryJobStore(keep_completed=config.jobs.keep_completed)


def _iter_workflow_files(config) -> Iterator[Path]:
    """Same priority order as the old WorkflowRegistry._discover()/
    _discover_external(): built-in package directory wins on name collision
    (empty today, but semantics preserved)."""
    seen: set[str] = set()
    for base_dir in (str(_SOAR_PKG / "workflows"), config.soar.workflows_dir):
        d = Path(base_dir)
        if not d.exists():
            continue
        for py_file in sorted(d.glob("*.py")):
            if py_file.name.startswith("_") or py_file.name == "base.py":
                continue
            if py_file.stem in seen:
                continue
            seen.add(py_file.stem)
            yield py_file


def load_workflow_metas(config) -> list[WorkflowMeta]:
    """Static AST parse only — never imports workflow modules (E10.3, see
    docs/concepts/ENTITY-MODEL.md). A webhook workflow whose `token` isn't a
    literal string constant (e.g. the WEBHOOK_TEMPLATE default `token =
    secrets.token_urlsafe(32)`, evaluated at import time under the old path)
    has no AST-extractable value; the platform generates and persists one
    the first time such a workflow is seen, same as the old path effectively
    did on first import — see orchestrator/api/workflows.py::WEBHOOK_TEMPLATE."""
    state_workflows = load_state(config)
    soar_metas = []
    for py_file in _iter_workflow_files(config):
        try:
            meta = parse_workflow_meta(py_file)
        except SyntaxError as e:
            logger.warning(f"Failed to parse workflow {py_file}: {e}")
            continue
        if meta is None:
            continue
        name = py_file.stem
        saved = state_workflows.get(name)
        enabled = parse_enabled(saved) if saved is not None else True
        token = meta.get("token")
        if meta["type"] == "webhook":
            token = parse_token(saved) or token or secrets.token_urlsafe(32)
        soar_metas.append(WorkflowMeta(
            name=name,
            type=meta["type"],
            enabled=enabled,
            schedule=meta.get("schedule"),
            interval=meta.get("interval"),
            path=meta.get("path"),
            token=token,
            concurrency=ConcurrencyPolicy.ALLOW if meta["type"] == "webhook" else ConcurrencyPolicy.FORBID,
            docstring=meta["docstring"],
            file_path=str(py_file),
        ))

    for name, saved in state_workflows.items():
        if any(m.name == name for m in soar_metas):
            continue
        soar_metas.append(WorkflowMeta(
            name=name,
            type="scheduled",
            enabled=parse_enabled(saved),
            concurrency=ConcurrencyPolicy.FORBID,
        ))

    save_state(config, soar_metas)
    return soar_metas


@asynccontextmanager
async def lifespan(app: FastAPI):
    config_path = os.environ.get("SOAR_CONFIG", "config.yaml")
    config = load_config(config_path)

    import sys
    logger.remove()
    logger.add(config.logging.file, level=config.logging.level, format=_LOG_FORMAT)
    logger.add(sys.stderr, level=config.logging.level, format=_LOG_FORMAT)

    if not config.auth.secret_key:
        logger.warning("auth.secret_key is not set — authentication is DISABLED, all requests treated as admin")

    seed_defaults(config)
    seed_connector_pack(config)

    # Database
    init_engine(config.database.url, config.database.pool_size, config.database.max_overflow)
    await init_db()
    app.state.db_session_factory = get_session_factory()

    queue = create_queue(config)
    job_store = create_job_store(config)
    runner = SubprocessRunner(config=config)
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
        db_session_factory=app.state.db_session_factory,
    )

    scheduler = OrchestratorScheduler(job_manager)

    app.state.job_manager = job_manager
    app.state.pool = pool
    app.state.scheduler = scheduler
    app.state.git = git
    app.state.config = config
    app.state.job_store = job_store
    app.state.queue = queue
    app.state.content_python = resolve_content_python()

    await pool.start()
    await scheduler.start(workflows, retention_days=config.jobs.retention_days)

    yield

    await scheduler.stop()
    await pool.stop()


app = FastAPI(title="SOAR Orchestrator", lifespan=lifespan)


class RateLimiter:
    def __init__(self, max_requests: int = 60, window: float = 60.0):
        self._requests: dict[str, list[float]] = defaultdict(list)
        self._max = max_requests
        self._window = window
        self._last_sweep = time.monotonic()

    def is_allowed(self, key: str) -> bool:
        now = time.monotonic()
        self._requests[key] = [t for t in self._requests[key] if now - t < self._window]
        allowed = len(self._requests[key]) < self._max
        if allowed:
            self._requests[key].append(now)
        self._sweep(now)
        return allowed

    def _sweep(self, now: float) -> None:
        # Every distinct key (client IP) is a permanent dict entry once seen —
        # without eviction this grows without bound (M2). At most once per
        # window, drop keys whose requests have all aged out.
        if now - self._last_sweep < self._window:
            return
        self._last_sweep = now
        stale = [k for k, ts in self._requests.items() if not ts or now - ts[-1] >= self._window]
        for k in stale:
            del self._requests[k]


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
    client_ip = resolve_client_ip(request)

    # Skip rate limiting for localhost/test clients
    if client_ip in ("testclient", "127.0.0.1", "::1"):
        return await call_next(request)

    # Stricter limit for login endpoint (brute-force protection)
    if request.url.path == "/auth/login":
        if not login_rate_limiter.is_allowed(client_ip):
            logger.bind(client_ip=client_ip).warning("auth.login_rate_limited")
            return JSONResponse(status_code=429, content={"detail": "Too many login attempts"})

    if not rate_limiter.is_allowed(client_ip):
        logger.bind(client_ip=client_ip, path=request.url.path).warning("rate_limited")
        return JSONResponse(status_code=429, content={"detail": "Rate limit exceeded"})

    return await call_next(request)


@app.middleware("http")
async def access_log_middleware(request: Request, call_next):
    """Registered last so it ends up the outermost layer — this is what lets
    it log/tag 413 and 429 responses raised by the middlewares above, not
    just responses that reach the router."""
    request_id = uuid.uuid4().hex[:16]
    request.state.request_id = request_id
    start = time.monotonic()

    with logger.contextualize(request_id=request_id):
        response = await call_next(request)
        duration_ms = round((time.monotonic() - start) * 1000, 1)
        logger.bind(
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            duration_ms=duration_ms,
            client_ip=resolve_client_ip(request),
            user_id=getattr(request.state, "user_id", None),
        ).info("request")

    response.headers["X-Request-ID"] = request_id
    return response


app.include_router(auth_router)
app.include_router(workflows_router)
app.include_router(actions_router)
app.include_router(connectors_router)
app.include_router(packs_router)
app.include_router(jobs_router)
app.include_router(webhooks_router)
app.include_router(logs_router)
app.include_router(status_router)
app.include_router(transfer_router)
app.include_router(tools_router)
app.include_router(prompts_router)
app.include_router(runtime_router)
app.include_router(audit_router)
