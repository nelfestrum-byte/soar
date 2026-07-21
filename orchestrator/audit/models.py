from datetime import datetime

from sqlalchemy import JSON, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from orchestrator.db.base import Base, prefixed


class AuditLog(Base):
    __tablename__ = prefixed("audit_log")

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor_id: Mapped[int] = mapped_column(Integer, nullable=False)
    actor_type: Mapped[str] = mapped_column(String(16), nullable=False)  # "user" | "service"
    actor_name: Mapped[str] = mapped_column(String(128), nullable=False)  # denormalized, survives actor deletion
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)  # e.g. "workflow.update"
    resource_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)  # e.g. "workflow"
    resource_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    client_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
