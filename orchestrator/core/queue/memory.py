import asyncio
from orchestrator.core.queue.base import AbstractJobQueue
from orchestrator.models.job import WorkflowJob


class InMemoryQueue(AbstractJobQueue):
    def __init__(self):
        self._queue: asyncio.Queue[WorkflowJob] = asyncio.Queue()

    async def push(self, job: WorkflowJob) -> None:
        await self._queue.put(job)

    async def pop(self, timeout: float = 1.0) -> WorkflowJob | None:
        try:
            return await asyncio.wait_for(self._queue.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None

    async def size(self) -> int:
        return self._queue.qsize()

    async def clear(self) -> None:
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break
