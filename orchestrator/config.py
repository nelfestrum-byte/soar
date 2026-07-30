import re
from pathlib import Path

import yaml
from pydantic import BaseModel, field_validator


class AuthConfig(BaseModel):
    secret_key: str = ""
    access_token_ttl: int = 1800
    refresh_token_ttl: int = 604800
    algorithm: str = "HS256"
    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:5173"]


_TABLE_PREFIX_RE = re.compile(r"^[a-zA-Z0-9_]*$")


class DatabaseConfig(BaseModel):
    url: str = "sqlite+aiosqlite:///./soar.db"
    pool_size: int = 10
    max_overflow: int = 20
    table_prefix: str = ""

    @field_validator("table_prefix")
    @classmethod
    def _validate_table_prefix(cls, v: str) -> str:
        if not _TABLE_PREFIX_RE.match(v):
            raise ValueError(
                "table_prefix must match ^[a-zA-Z0-9_]*$ (it feeds SQL table identifiers)"
            )
        return v


class WorkersConfig(BaseModel):
    count: int = 4
    default_timeout: int = 300


class QueueConfig(BaseModel):
    backend: str = "memory"
    redis_url: str = "redis://localhost:6379/0"
    redis_max_connections: int = 10
    redis_push_timeout: float = 5.0
    redis_pop_timeout: float = 1.0
    sql_poll_interval: float = 0.5


class SoarConfig(BaseModel):
    workflows_dir: str = "/app/data/workflows"
    connectors_dir: str = "/app/data/connectors"
    actions_dir: str = "/app/data/actions"
    tools_dir: str = "soar/tools"
    state_dir: str = "/app/data/state"  # WatermarkStore/SeenStore factories, soar/tools/watermark.py
    system_prompt_path: str = "orchestrator/prompts/system_prompt.md"


class GitConfig(BaseModel):
    workflows_repo: str = "/app/data"
    author_name: str = "SOAR Orchestrator"
    author_email: str = "soar@local"


class LoggingConfig(BaseModel):
    level: str = "INFO"
    file: str = "/var/log/soar/orchestrator.log"


class JobsConfig(BaseModel):
    log_dir: str = "/var/log/soar/jobs"
    keep_completed: int = 1000
    persistence: str = "memory"  # memory | sql
    retention_days: int = 0  # 0 = disabled — explicit opt-in, not a silent default

    # Privilege narrowing (Фаза 4, docs/compose/specs/2026-07-30-privilege-
    # narrowing-design.md [S3]) — POSIX/Docker only, no-op on Windows dev.
    # None = today's behavior unchanged: runner subprocess inherits the
    # orchestrator's own UID, no rlimits applied. Setting runner_uid opts
    # into dropping the job subprocess to a separate, less-privileged UID
    # via a setpriv wrapper (see subprocess_runner.py::_runner_argv —
    # os.setuid/setgid directly in preexec_fn does NOT work from a non-root
    # parent without CAP_SETUID/CAP_SETGID on the interpreter itself, which
    # would be a bigger privilege grant than the mechanism is meant to
    # provide; verified empirically in Docker, see the Phase 4 report).
    runner_uid: int | None = None
    runner_gid: int | None = None
    runner_max_memory_mb: int = 512
    runner_max_cpu_seconds: int = 300
    runner_max_procs: int = 32


class ServerConfig(BaseModel):
    trusted_proxies: list[str] = []


class HttpClientConfig(BaseModel):
    cache_backend: str = "memory"   # memory | redis | none
    default_ttl: int = 3600
    domain_ttl: dict[str, int] = {}


class OrchestratorConfig(BaseModel):
    workers: WorkersConfig = WorkersConfig()
    queue: QueueConfig = QueueConfig()
    soar: SoarConfig = SoarConfig()
    git: GitConfig = GitConfig()
    logging: LoggingConfig = LoggingConfig()
    jobs: JobsConfig = JobsConfig()
    server: ServerConfig = ServerConfig()
    auth: AuthConfig = AuthConfig()
    database: DatabaseConfig = DatabaseConfig()
    http_client: HttpClientConfig = HttpClientConfig()


def load_config(path: str = "config.yaml") -> OrchestratorConfig:
    config_path = Path(path)
    if config_path.exists():
        with open(config_path) as f:
            data = yaml.safe_load(f) or {}
        return OrchestratorConfig(**data)
    return OrchestratorConfig()
