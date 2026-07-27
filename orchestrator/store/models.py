from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from orchestrator.db.base import Base, prefixed


class JobRecord(Base):
    # NOTE: a partial index on (status, triggered_at) WHERE status='PENDING' is
    # added via alembic migration (not declared here) — keeps SQLQueue.pop()'s
    # claim query cheap regardless of historical COMPLETED/FAILED row volume.
    # See docs/compose/specs/2026-07-27-sql-job-queue-design.md [S5].
    __tablename__ = prefixed("workflow_jobs")

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workflow_name: Mapped[str] = mapped_column(String(255), index=True)
    workflow_type: Mapped[str] = mapped_column(String(64))
    triggered_by: Mapped[str] = mapped_column(String(255))
    context: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(32), index=True)
    concurrency: Mapped[str] = mapped_column(String(32))
    pid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    log_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    timeout: Mapped[int | None] = mapped_column(Integer, nullable=True)
    triggered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    result_success: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    result_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    result_error: Mapped[str | None] = mapped_column(Text, nullable=True)
