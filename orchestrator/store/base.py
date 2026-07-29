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
    async def count_by_status(
        self, workflow_name: str, statuses: list[JobStatus], exclude_job_id: str | None = None  # type: ignore[valid-type]
    ) -> int: ...

    @abstractmethod
    async def stats(self) -> dict: ...

    @abstractmethod
    async def recover_on_startup(self) -> int: ...

    @abstractmethod
    async def purge_old(self, retention_days: int) -> int: ...
