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


class SoarConfig(BaseModel):
    workflows_dir: str = "/app/data/workflows"
    connectors_dir: str = "/app/data/connectors"
    actions_dir: str = "/app/data/actions"
    tools_dir: str = "soar/tools"


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


class ServerConfig(BaseModel):
    trusted_proxies: list[str] = []


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


def load_config(path: str = "config.yaml") -> OrchestratorConfig:
    config_path = Path(path)
    if config_path.exists():
        with open(config_path) as f:
            data = yaml.safe_load(f) or {}
        return OrchestratorConfig(**data)
    return OrchestratorConfig()
