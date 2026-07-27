"""SQL-backed job queue: polls the same `workflow_jobs` table SQLJobStore
writes to, instead of a separate broker (Redis). Closes the at-most-once
message-loss window in RedisQueue.pop() (BRPOP) — see
docs/compose/specs/2026-07-27-sql-job-queue-design.md.

JobManager.enqueue() writes the PENDING row via job_store.save() *before*
calling queue.push() — so push() here is a no-op, and pop() is an atomic
claim query against the row that already exists.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from loguru import logger
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from orchestrator.core.queue.base import AbstractJobQueue
from orchestrator.models.job import JobStatus, WorkflowJob
from orchestrator.store.mapping import record_to_job
from orchestrator.store.models import JobRecord


class SQLQueue(AbstractJobQueue):
    def __init__(self, session_factory: async_sessionmaker, poll_interval: float = 0.5):
        self._session_factory = session_factory
        self._poll_interval = poll_interval

    async def push(self, job: WorkflowJob) -> None:
        # No-op: JobManager.enqueue() already persisted this row as PENDING via
        # job_store.save() before calling queue.push(). Nothing to add here —
        # duplicating it would create a second row with the same primary key
        # (harmless via merge(), but pointless work).
        return None

    async def _try_claim(self) -> WorkflowJob | None:
        now = datetime.now(UTC)
        async with self._session_factory() as session:
            dialect = session.bind.dialect.name
            select_pending = (
                select(JobRecord.id)
                .where(JobRecord.status == JobStatus.PENDING.value)
                .order_by(JobRecord.triggered_at)
                .limit(1)
            )
            if dialect == "postgresql":
                select_pending = select_pending.with_for_update(skip_locked=True)

            result = await session.execute(select_pending)
            job_id = result.scalar_one_or_none()
            if job_id is None:
                return None

            claim = (
                update(JobRecord)
                .where(JobRecord.id == job_id, JobRecord.status == JobStatus.PENDING.value)
                .values(status=JobStatus.RUNNING.value, started_at=now)
            )
            claim_result = await session.execute(claim)
            if claim_result.rowcount == 0:
                # Another worker claimed it between our SELECT and UPDATE
                # (only possible on sqlite, which has no SKIP LOCKED — the
                # single-writer file lock still guarantees no double-claim).
                await session.commit()
                return None

            record = await session.get(JobRecord, job_id)
            await session.commit()
            return record_to_job(record)

    async def pop(self, timeout: float = 1.0) -> WorkflowJob | None:
        loop = asyncio.get_event_loop()
        deadline = loop.time() + timeout
        while True:
            job = await self._try_claim()
            if job is not None:
                return job
            remaining = deadline - loop.time()
            if remaining <= 0:
                return None
            await asyncio.sleep(min(self._poll_interval, remaining))

    async def size(self) -> int:
        async with self._session_factory() as session:
            result = await session.execute(
                select(func.count()).select_from(JobRecord).where(
                    JobRecord.status == JobStatus.PENDING.value
                )
            )
            return int(result.scalar_one())

    async def clear(self) -> None:
        # SQLQueue does not own a separate list — the PENDING rows *are* the
        # queue. Clearing means marking them CANCELLED so they stop being
        # claimable, mirroring RedisQueue.clear()'s "empty the queue" intent
        # without touching RUNNING/terminal rows.
        async with self._session_factory() as session:
            await session.execute(
                update(JobRecord)
                .where(JobRecord.status == JobStatus.PENDING.value)
                .values(status=JobStatus.CANCELLED.value, finished_at=datetime.now(UTC))
            )
            await session.commit()

    async def health(self) -> dict:
        try:
            size = await self.size()
            return {"connected": True, "size": size}
        except Exception as e:
            logger.error(f"SQLQueue health check failed: {e}")
            return {"connected": False, "size": 0}
