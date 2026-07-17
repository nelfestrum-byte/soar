from __future__ import annotations

from datetime import UTC, datetime

from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from orchestrator.models import ConcurrencyPolicy, JobStatus
from orchestrator.models.job import WorkflowJob
from orchestrator.store.base import AbstractJobStore
from orchestrator.store.models import JobRecord


def _ensure_utc(dt: datetime | None) -> datetime | None:
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


def _ensure_utc_required(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def _job_to_record(job: WorkflowJob) -> JobRecord:
    return JobRecord(
        id=job.id,
        workflow_name=job.workflow_name,
        workflow_type=job.workflow_type,
        triggered_by=job.triggered_by,
        context=job.context,
        status=job.status.value,
        concurrency=job.concurrency.value,
        pid=job.pid,
        log_path=job.log_path,
        timeout=job.timeout,
        triggered_at=job.triggered_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        result_success=job.result_success,
        result_data=job.result_data,
        result_error=job.result_error,
    )


def _record_to_job(record: JobRecord) -> WorkflowJob:
    return WorkflowJob(
        id=record.id,
        workflow_name=record.workflow_name,
        workflow_type=record.workflow_type,
        triggered_by=record.triggered_by,
        context=record.context or {},
        status=JobStatus(record.status),
        concurrency=ConcurrencyPolicy(record.concurrency),
        pid=record.pid,
        log_path=record.log_path,
        timeout=record.timeout,
        triggered_at=_ensure_utc_required(record.triggered_at),
        started_at=_ensure_utc(record.started_at),
        finished_at=_ensure_utc(record.finished_at),
        result_success=record.result_success,
        result_data=record.result_data,
        result_error=record.result_error,
    )


class SQLJobStore(AbstractJobStore):
    def __init__(self, session_factory: async_sessionmaker):
        self._session_factory = session_factory

    async def save(self, job: WorkflowJob) -> None:
        async with self._session_factory() as session:
            await session.merge(_job_to_record(job))
            await session.commit()

    async def get(self, job_id: str) -> WorkflowJob | None:
        async with self._session_factory() as session:
            record = await session.get(JobRecord, job_id)
            return _record_to_job(record) if record else None

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
            return [_record_to_job(r) for r in result.scalars().all()]

    async def count_by_status(self, workflow_name: str, statuses: list[JobStatus]) -> int:  # type: ignore[valid-type]
        stmt = select(func.count()).select_from(JobRecord).where(
            JobRecord.workflow_name == workflow_name,
            JobRecord.status.in_([s.value for s in statuses]),  # type: ignore[attr-defined]
        )
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
