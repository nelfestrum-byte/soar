import asyncio
from loguru import logger
from orchestrator.core.worker import Worker
from orchestrator.core.queue.base import AbstractJobQueue
from orchestrator.core.subprocess_runner import SubprocessRunner
from orchestrator.store.job_store import JobStore


class WorkerPool:
    def __init__(
        self,
        count: int,
        queue: AbstractJobQueue,
        runner: SubprocessRunner,
        job_store: JobStore,
        default_timeout: int,
    ):
        self._workers: list[Worker] = [
            Worker(i, queue, runner, job_store, default_timeout)
            for i in range(count)
        ]
        self._tasks: list[asyncio.Task] = []

    async def start(self) -> None:
        for worker in self._workers:
            task = asyncio.create_task(worker.run())
            self._tasks.append(task)
        logger.info(f"Started {len(self._workers)} workers")

    async def stop(self) -> None:
        for worker in self._workers:
            await worker.stop()
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        logger.info("All workers stopped")

    @property
    def status(self) -> dict:
        return {
            "total": len(self._workers),
            "busy": sum(1 for w in self._workers if w.is_busy),
            "idle": sum(1 for w in self._workers if not w.is_busy),
        }
