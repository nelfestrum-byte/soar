from abc import ABC, abstractmethod

from orchestrator.models.job import WorkflowJob


class AbstractJobQueue(ABC):
    @abstractmethod
    async def push(self, job: WorkflowJob) -> None: ...

    @abstractmethod
    async def pop(self, timeout: float = 1.0) -> WorkflowJob | None: ...

    @abstractmethod
    async def size(self) -> int: ...

    @abstractmethod
    async def clear(self) -> None: ...
