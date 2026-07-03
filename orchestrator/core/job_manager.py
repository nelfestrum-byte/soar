import asyncio
from datetime import UTC, datetime
from uuid import uuid4

from loguru import logger

from orchestrator.core.queue.base import AbstractJobQueue
from orchestrator.core.subprocess_runner import SubprocessRunner
from orchestrator.models import ConcurrencyPolicy
from orchestrator.models.job import JobStatus, WorkflowJob
from orchestrator.models.workflow_meta import WorkflowMeta
from orchestrator.store.job_store import JobStore


class JobAlreadyRunningError(Exception):
    pass


class WorkflowDisabledError(Exception):
    pass


class JobManager:
    def __init__(
        self,
        queue: AbstractJobQueue,
        job_store: JobStore,
        runner: SubprocessRunner,
        log_dir: str,
        workflow_registry=None,
    ):
        self.queue = queue
        self.job_store = job_store
        self.runner = runner
        self.log_dir = log_dir
        self._metas: dict[str, WorkflowMeta] = {}
        self._workflow_registry = workflow_registry
        self._locks: dict[str, asyncio.Lock] = {}

    def _get_lock(self, name: str) -> asyncio.Lock:
        if name not in self._locks:
            self._locks[name] = asyncio.Lock()
        return self._locks[name]

    def set_metas(self, metas: list[WorkflowMeta]) -> None:
        self._metas = {m.name: m for m in metas}

    def get_meta(self, name: str) -> WorkflowMeta | None:
        return self._metas.get(name)

    def list_metas(self) -> list[WorkflowMeta]:
        return list(self._metas.values())

    def _get_meta(self, workflow_name: str) -> WorkflowMeta:
        if workflow_name not in self._metas:
            raise ValueError(f"Workflow '{workflow_name}' not found")
        return self._metas[workflow_name]

    def _make_log_path(self, workflow_name: str, job_id: str) -> str:
        import os
        import re
        safe_name = re.sub(r"[^a-zA-Z0-9_\-]", "_", workflow_name)
        path = os.path.join(self.log_dir, safe_name, f"{job_id}.log")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        return path

    async def enqueue(
        self,
        workflow_name: str,
        context: dict,
        triggered_by: str,
    ) -> WorkflowJob:
        meta = self._get_meta(workflow_name)

        if not meta.enabled:
            raise WorkflowDisabledError(workflow_name)

        lock = self._get_lock(workflow_name)
        async with lock:
            await self._check_concurrency(meta)

            job_id = str(uuid4())
            job = WorkflowJob(
                id=job_id,
                workflow_name=workflow_name,
                workflow_type=meta.type,
                triggered_by=triggered_by,
                context=context,
                concurrency=meta.concurrency,
                log_path=self._make_log_path(workflow_name, job_id),
                timeout=meta.timeout,
            )

            await self.job_store.save(job)
            try:
                await self.queue.push(job)
            except Exception as e:
                logger.error(f"Failed to enqueue job {job.id}: {e}")
                job.status = JobStatus.FAILED
                job.result_error = f"Queue push failed: {e}"
                job.finished_at = datetime.now(UTC)
                await self.job_store.save(job)
                raise
            logger.info(f"Enqueued job {job.id} for workflow {workflow_name}")
            return job

    async def cancel(self, job_id: str) -> WorkflowJob:
        job = await self.job_store.get(job_id)
        if not job:
            raise ValueError(f"Job '{job_id}' not found")

        import os
        import signal
        if job.status == JobStatus.RUNNING and job.pid:
            try:
                # On Windows, os.kill calls TerminateProcess (immediate hard kill)
                # On Unix, sends SIGTERM (graceful)
                os.kill(job.pid, signal.SIGTERM)
            except (ProcessLookupError, OSError):
                pass

        job.status = JobStatus.CANCELLED
        job.finished_at = datetime.now(UTC)
        await self.job_store.save(job)
        return job

    async def _check_concurrency(self, meta: WorkflowMeta) -> None:
        if meta.concurrency == ConcurrencyPolicy.FORBID:
            running = await self.job_store.count_by_status(
                meta.name, [JobStatus.RUNNING, JobStatus.PENDING]
            )
            if running > 0:
                raise JobAlreadyRunningError(
                    f"Workflow '{meta.name}' is already running"
                )
        # NOTE: QUEUE policy is not yet implemented — behaves like ALLOW
        # TODO: implement sequential queuing for QUEUE policy
