from pathlib import Path

import yaml
from pydantic import BaseModel


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


class OrchestratorConfig(BaseModel):
    workers: WorkersConfig = WorkersConfig()
    queue: QueueConfig = QueueConfig()
    soar: SoarConfig = SoarConfig()
    git: GitConfig = GitConfig()
    logging: LoggingConfig = LoggingConfig()
    jobs: JobsConfig = JobsConfig()


def load_config(path: str = "config.yaml") -> OrchestratorConfig:
    config_path = Path(path)
    if config_path.exists():
        with open(config_path) as f:
            data = yaml.safe_load(f) or {}
        return OrchestratorConfig(**data)
    return OrchestratorConfig()
