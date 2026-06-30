from __future__ import annotations

from datetime import UTC, datetime

from orchestrator.models.job import JobStatus, WorkflowJob


class JobStore:
    def __init__(self, keep_completed: int = 1000):
        self._jobs: dict[str, WorkflowJob] = {}
        self._keep_completed = keep_completed

    async def save(self, job: WorkflowJob) -> None:
        self._jobs[job.id] = job
        self._cleanup()

    async def get(self, job_id: str) -> WorkflowJob | None:
        return self._jobs.get(job_id)

    async def list(
        self,
        workflow_name: str | None = None,
        status: JobStatus | None = None,
        triggered_by: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[WorkflowJob]:
        jobs = list(self._jobs.values())

        if workflow_name:
            jobs = [j for j in jobs if j.workflow_name == workflow_name]
        if status:
            jobs = [j for j in jobs if j.status == status]
        if triggered_by:
            jobs = [j for j in jobs if j.triggered_by == triggered_by]

        jobs.sort(key=lambda j: j.triggered_at or datetime.min.replace(tzinfo=UTC), reverse=True)
        return jobs[offset: offset + limit]

    async def count_by_status(self, workflow_name: str, statuses: list[JobStatus]) -> int:  # type: ignore[valid-type, no-redef]
        return sum(1 for j in self._jobs.values()  # type: ignore[misc]
                   if j.workflow_name == workflow_name and j.status in statuses)  # type: ignore[misc, attr-defined]

    async def stats(self) -> dict:
        now = datetime.now(UTC)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        running = sum(1 for j in self._jobs.values() if j.status == JobStatus.RUNNING)
        completed_today = sum(
            1 for j in self._jobs.values()
            if j.status == JobStatus.COMPLETED
            and j.finished_at and j.finished_at >= today_start
        )
        failed_today = sum(
            1 for j in self._jobs.values()
            if j.status == JobStatus.FAILED
            and j.finished_at and j.finished_at >= today_start
        )
        timeout_today = sum(
            1 for j in self._jobs.values()
            if j.status == JobStatus.TIMEOUT
            and j.finished_at and j.finished_at >= today_start
        )

        return {
            "running": running,
            "completed_today": completed_today,
            "failed_today": failed_today,
            "timeout_today": timeout_today,
        }

    def _cleanup(self) -> None:
        completed = [
            j for j in self._jobs.values()
            if j.status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.TIMEOUT, JobStatus.CANCELLED)
        ]
        if len(completed) > self._keep_completed:
            completed.sort(key=lambda j: j.finished_at or datetime.min.replace(tzinfo=UTC))
            to_remove = completed[: len(completed) - self._keep_completed]
            for job in to_remove:
                self._jobs.pop(job.id, None)
