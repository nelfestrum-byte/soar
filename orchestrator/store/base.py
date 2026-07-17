from __future__ import annotations

from abc import ABC, abstractmethod

from orchestrator.models.job import JobStatus, WorkflowJob


class AbstractJobStore(ABC):
    @abstractmethod
    async def save(self, job: WorkflowJob) -> None: ...

    @abstractmethod
    async def get(self, job_id: str) -> WorkflowJob | None: ...

    @abstractmethod
    async def list(
        self,
        workflow_name: str | None = None,
        status: JobStatus | None = None,
        triggered_by: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[WorkflowJob]: ...

    @abstractmethod
    async def count_by_status(self, workflow_name: str, statuses: list[JobStatus]) -> int: ...  # type: ignore[valid-type]

    @abstractmethod
    async def stats(self) -> dict: ...

    @abstractmethod
    async def recover_on_startup(self) -> int: ...
