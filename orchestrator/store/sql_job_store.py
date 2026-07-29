from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

from loguru import logger
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from orchestrator.models.job import JobStatus, WorkflowJob
from orchestrator.store.base import AbstractJobStore
from orchestrator.store.mapping import job_to_record, record_to_job
from orchestrator.store.models import JobRecord

_TERMINAL_STATUSES = (
    JobStatus.COMPLETED.value,
    JobStatus.FAILED.value,
    JobStatus.TIMEOUT.value,
    JobStatus.CANCELLED.value,
)


class SQLJobStore(AbstractJobStore):
    def __init__(self, session_factory: async_sessionmaker):
        self._session_factory = session_factory

    async def save(self, job: WorkflowJob) -> None:
        async with self._session_factory() as session:
            await session.merge(job_to_record(job))
            await session.commit()

    async def get(self, job_id: str) -> WorkflowJob | None:
        async with self._session_factory() as session:
            record = await session.get(JobRecord, job_id)
            return record_to_job(record) if record else None

    async def list(
        self,
        workflow_name: str | None = None,
        status: JobStatus | None = None,
        triggered_by: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[WorkflowJob]:
        stmt = select(JobRecord)
        if workflow_name:
            stmt = stmt.where(JobRecord.workflow_name == workflow_name)
        if status:
            stmt = stmt.where(JobRecord.status == status.value)
        if triggered_by:
            stmt = stmt.where(JobRecord.triggered_by == triggered_by)
        stmt = stmt.order_by(JobRecord.triggered_at.desc()).offset(offset).limit(limit)

        async with self._session_factory() as session:
            result = await session.execute(stmt)
            return [record_to_job(r) for r in result.scalars().all()]

    async def count_by_status(
        self, workflow_name: str, statuses: list[JobStatus], exclude_job_id: str | None = None  # type: ignore[valid-type]
    ) -> int:
        stmt = select(func.count()).select_from(JobRecord).where(
            JobRecord.workflow_name == workflow_name,
            JobRecord.status.in_([s.value for s in statuses]),  # type: ignore[attr-defined]
        )
        if exclude_job_id:
            stmt = stmt.where(JobRecord.id != exclude_job_id)
        async with self._session_factory() as session:
            result = await session.execute(stmt)
            return int(result.scalar_one())

    async def stats(self) -> dict:
        now = datetime.now(UTC)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        async def _count(status: JobStatus, since_finished: bool) -> int:
            stmt = select(func.count()).select_from(JobRecord).where(JobRecord.status == status.value)
            if since_finished:
                stmt = stmt.where(JobRecord.finished_at >= today_start)
            async with self._session_factory() as session:
                result = await session.execute(stmt)
                return int(result.scalar_one())

        return {
            "running": await _count(JobStatus.RUNNING, since_finished=False),
            "completed_today": await _count(JobStatus.COMPLETED, since_finished=True),
            "failed_today": await _count(JobStatus.FAILED, since_finished=True),
            "timeout_today": await _count(JobStatus.TIMEOUT, since_finished=True),
        }

    async def recover_on_startup(self) -> int:
        now = datetime.now(UTC)
        async with self._session_factory() as session:
            result = await session.execute(
                select(JobRecord).where(JobRecord.status == JobStatus.RUNNING.value)
            )
            records = result.scalars().all()
            for record in records:
                record.status = JobStatus.FAILED.value
                record.result_error = "Process died before startup recovery"
                record.finished_at = now
            await session.commit()
            count = len(records)
        if count > 0:
            logger.info(f"Startup recovery: {count} RUNNING jobs marked as FAILED")
        return count

    async def purge_old(self, retention_days: int) -> int:
        threshold = datetime.now(UTC) - timedelta(days=retention_days)
        async with self._session_factory() as session:
            to_delete = await session.execute(
                select(JobRecord.log_path).where(
                    JobRecord.status.in_(_TERMINAL_STATUSES),
                    JobRecord.finished_at < threshold,
                    JobRecord.log_path.is_not(None),
                )
            )
            log_paths = [row[0] for row in to_delete if row[0]]

            result = await session.execute(
                delete(JobRecord).where(
                    JobRecord.status.in_(_TERMINAL_STATUSES),
                    JobRecord.finished_at < threshold,
                )
            )
            await session.commit()
            count = result.rowcount or 0

        for path in log_paths:
            try:
                os.remove(path)
            except FileNotFoundError:
                pass
            except OSError as e:
                logger.warning(f"Retention cleanup: failed to remove log file {path}: {e}")

        if count > 0:
            logger.info(f"Retention cleanup: purged {count} job records older than {retention_days}d")
        return count
