from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from orchestrator.db.base import Base, prefixed


class JobRecord(Base):
    # Partial index on (status, triggered_at) WHERE status='PENDING' — keeps
    # SQLQueue.pop()'s claim query cheap regardless of historical
    # COMPLETED/FAILED row volume. Declared here (not just in the
    # 42fbd47b0d46 migration) so create_all() creates it on fresh installs too
    # — `soarctl migrate --fresh` only stamps the alembic revision, it never
    # runs migration DDL. Same index name in both places by design: fresh
    # installs get it from create_all(), upgrades of pre-existing installs get
    # it from the migration; see
    # docs/compose/specs/2026-07-27-sql-job-queue-design.md [S5] and
    # docs/compose/specs/2026-07-28-workflow-jobs-index-table-prefix-design.md.
    __tablename__ = prefixed("workflow_jobs")
    __table_args__ = (
        Index(
            f"ix_{prefixed('workflow_jobs')}_pending_triggered_at",
            "status",
            "triggered_at",
            postgresql_where=text("status = 'PENDING'"),
            sqlite_where=text("status = 'PENDING'"),
        ),
    )

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
    # WorkflowMeta.file_path at enqueue time — SubprocessRunner statically
    # scans this for connector imports to build the job's scoped config
    # (privilege narrowing). Must round-trip through SQL/Redis queues, not
    # just the in-memory one, or SQL/Redis-backed installs would silently
    # get zero connector credentials for every job (see
    # docs/compose/specs/2026-07-30-privilege-narrowing-design.md).
    workflow_file: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    triggered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    result_success: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    result_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    result_error: Mapped[str | None] = mapped_column(Text, nullable=True)
