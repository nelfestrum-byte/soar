from dataclasses import dataclass, field
from datetime import datetime, UTC
from uuid import uuid4
from orchestrator.models import JobStatus


@dataclass
class WorkflowJob:
    id: str = field(default_factory=lambda: str(uuid4()))
    workflow_name: str = ""
    workflow_type: str = ""
    triggered_by: str = ""
    context: dict = field(default_factory=dict)

    status: JobStatus = JobStatus.PENDING
    pid: int | None = None
    log_path: str | None = None
    timeout: int | None = None

    triggered_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = None
    finished_at: datetime | None = None

    result_success: bool | None = None
    result_data: dict | None = None
    result_error: str | None = None

    @property
    def duration_seconds(self) -> float | None:
        if self.started_at and self.finished_at:
            return (self.finished_at - self.started_at).total_seconds()
        return None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "workflow_name": self.workflow_name,
            "workflow_type": self.workflow_type,
            "triggered_by": self.triggered_by,
            "context": self.context,
            "status": self.status.value,
            "pid": self.pid,
            "log_path": self.log_path,
            "timeout": self.timeout,
            "triggered_at": self.triggered_at.isoformat() if self.triggered_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "duration_seconds": self.duration_seconds,
            "result_success": self.result_success,
            "result_data": self.result_data,
            "result_error": self.result_error,
        }
