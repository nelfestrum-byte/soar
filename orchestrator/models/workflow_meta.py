from dataclasses import dataclass
from orchestrator.models import ConcurrencyPolicy


@dataclass
class WorkflowMeta:
    name: str
    type: str
    enabled: bool = True
    schedule: str | None = None
    interval: int | None = None
    path: str | None = None
    token: str | None = None
    timeout: int | None = None
    concurrency: ConcurrencyPolicy = ConcurrencyPolicy.FORBID
    file_path: str = ""
