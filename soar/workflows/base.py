from dataclasses import dataclass
from datetime import UTC, datetime

from soar.logger import get_logger


@dataclass
class WorkflowResult:
    success: bool
    workflow_name: str
    started_at: datetime
    finished_at: datetime
    duration_seconds: float
    error: Exception | None = None
    data: dict | None = None


class BaseWorkflow:
    workflow_type: str = "manual"

    def __init__(self):
        self._logger = get_logger(f"workflow.{self.__class__.__name__}")

    def run(self, context: dict) -> dict | None:
        raise NotImplementedError

    def execute(self, context: dict | None = None) -> WorkflowResult:
        if context is None:
            context = {}
        log = get_logger(f"workflow.{self.__class__.__name__}")
        started_at = datetime.now(UTC)
        log.info(f"Starting workflow {self.__class__.__name__}")

        try:
            data = self.run(context)
            finished_at = datetime.now(UTC)
            duration = (finished_at - started_at).total_seconds()
            log.info(f"Workflow {self.__class__.__name__} completed in {duration:.2f}s")
            return WorkflowResult(
                success=True,
                workflow_name=self.__class__.__name__,
                started_at=started_at,
                finished_at=finished_at,
                duration_seconds=duration,
                data=data,
            )
        except Exception as e:
            finished_at = datetime.now(UTC)
            duration = (finished_at - started_at).total_seconds()
            log.error(f"Workflow {self.__class__.__name__} failed: {e}")
            return WorkflowResult(
                success=False,
                workflow_name=self.__class__.__name__,
                started_at=started_at,
                finished_at=finished_at,
                duration_seconds=duration,
                error=e,
            )


class ScheduledWorkflow(BaseWorkflow):
    workflow_type = "scheduled"
    schedule: str | None = None
    interval: int | None = None


class WebhookWorkflow(BaseWorkflow):
    workflow_type = "webhook"
    path: str = ""
    token: str = ""


class ManualWorkflow(BaseWorkflow):
    workflow_type = "manual"
