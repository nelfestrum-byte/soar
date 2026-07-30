"""WorkflowJob <-> JobRecord mapping, shared by SQLJobStore and SQLQueue —
both read/write the same workflow_jobs table (see
docs/compose/specs/2026-07-27-sql-job-queue-design.md [S2]/[S3])."""

from __future__ import annotations

from datetime import UTC, datetime

from orchestrator.models import ConcurrencyPolicy, JobStatus
from orchestrator.models.job import WorkflowJob
from orchestrator.store.models import JobRecord


def ensure_utc(dt: datetime | None) -> datetime | None:
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


def ensure_utc_required(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def job_to_record(job: WorkflowJob) -> JobRecord:
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
        workflow_file=job.workflow_file,
        triggered_at=job.triggered_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        result_success=job.result_success,
        result_data=job.result_data,
        result_error=job.result_error,
    )


def record_to_job(record: JobRecord) -> WorkflowJob:
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
        workflow_file=record.workflow_file or "",
        triggered_at=ensure_utc_required(record.triggered_at),
        started_at=ensure_utc(record.started_at),
        finished_at=ensure_utc(record.finished_at),
        result_success=record.result_success,
        result_data=record.result_data,
        result_error=record.result_error,
    )
