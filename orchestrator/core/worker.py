import asyncio
from datetime import UTC, datetime

from loguru import logger

from orchestrator.core.queue.base import AbstractJobQueue
from orchestrator.core.subprocess_runner import SubprocessRunner
from orchestrator.models.job import JobStatus, WorkflowJob
from orchestrator.store.job_store import JobStore


class Worker:
    def __init__(
        self,
        worker_id: int,
        queue: AbstractJobQueue,
        runner: SubprocessRunner,
        job_store: JobStore,
        default_timeout: int,
    ):
        self.worker_id = worker_id
        self.queue = queue
        self.runner = runner
        self.job_store = job_store
        self.default_timeout = default_timeout
        self._running = False
        self._busy = False
        self._task: asyncio.Task | None = None

    async def run(self) -> None:
        self._running = True
        while self._running:
            job = await self.queue.pop(timeout=1.0)
            if job:
                await self._execute(job)

    async def _execute(self, job: WorkflowJob) -> None:
        # Check if job was cancelled while in queue
        current = await self.job_store.get(job.id)
        if current and current.status == JobStatus.CANCELLED:
            logger.info(f"Skipping cancelled job {job.id}")
            return
        self._busy = True
        try:
            job.status = JobStatus.RUNNING
            job.started_at = datetime.now(UTC)
            await self.job_store.save(job)

            proc = await self.runner.start(job)
            job.pid = proc.pid
            await self.job_store.save(job)

            timeout = job.timeout if job.timeout is not None else self.default_timeout
            try:
                stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            except TimeoutError:
                proc.kill()
                await proc.wait()
                job.status = JobStatus.TIMEOUT
                job.finished_at = datetime.now(UTC)
                await self.job_store.save(job)
                logger.warning(f"Job {job.id} timed out after {timeout}s")
                return
            except asyncio.CancelledError:
                proc.kill()
                await proc.wait()
                job.status = JobStatus.CANCELLED
                job.finished_at = datetime.now(UTC)
                await self.job_store.save(job)
                raise
            finally:
                if hasattr(proc, '_log_file') and proc._log_file:
                    proc._log_file.close()

            if proc.returncode == 0:
                job.status = JobStatus.COMPLETED
                job.result_success = True
            else:
                job.status = JobStatus.FAILED
                job.result_success = False
                job.result_error = stdout.decode() if stdout else "Process failed"

            job.finished_at = datetime.now(UTC)
            await self.job_store.save(job)
        except Exception as e:
            job.status = JobStatus.FAILED
            job.result_error = str(e)
            job.finished_at = datetime.now(UTC)
            await self.job_store.save(job)
            logger.error(f"Job {job.id} failed: {e}")
        finally:
            self._busy = False

    @property
    def is_busy(self) -> bool:
        return self._busy

    async def stop(self) -> None:
        self._running = False
