import asyncio
import json
from datetime import UTC, datetime

from loguru import logger

from orchestrator.core.queue.base import AbstractJobQueue
from orchestrator.core.subprocess_runner import SubprocessRunner
from orchestrator.models import ConcurrencyPolicy
from orchestrator.models.job import JobStatus, WorkflowJob
from orchestrator.store.base import AbstractJobStore


class Worker:
    def __init__(
        self,
        worker_id: int,
        queue: AbstractJobQueue,
        runner: SubprocessRunner,
        job_store: AbstractJobStore,
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

        # QUEUE policy: wait until no other job of this workflow is RUNNING
        if job.concurrency == ConcurrencyPolicy.QUEUE:
            while await self.job_store.count_by_status(job.workflow_name, [JobStatus.RUNNING]) > 0:
                await asyncio.sleep(1.0)
            # Re-check job wasn't cancelled while waiting
            current = await self.job_store.get(job.id)
            if current and current.status == JobStatus.CANCELLED:
                logger.info(f"Skipping cancelled job {job.id} (was waiting in queue)")
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

            # B4: parse result_data from last JSON line of log file (runner contract)
            if job.log_path:
                try:
                    with open(job.log_path) as f:
                        lines = [ln.strip() for ln in f if ln.strip()]
                    if lines:
                        parsed = json.loads(lines[-1])
                        job.result_data = parsed.get("data")
                        if parsed.get("error"):
                            job.result_error = parsed["error"]
                except (OSError, json.JSONDecodeError, ValueError):
                    pass

            # B1: re-read from store — cancel() may have set CANCELLED while process ran
            current = await self.job_store.get(job.id)
            if current and current.status == JobStatus.CANCELLED:
                job.status = JobStatus.CANCELLED
            elif proc.returncode == 0:
                job.status = JobStatus.COMPLETED
                job.result_success = True
            else:
                job.status = JobStatus.FAILED
                job.result_success = False
                if not job.result_error:
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
