from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.audit.models import AuditLog
from orchestrator.auth.dependencies import require_role
from orchestrator.db.session import get_db

router = APIRouter(prefix="/audit-log", tags=["audit"])


def _to_dict(row: AuditLog) -> dict:
    return {
        "id": row.id,
        "actor_id": row.actor_id,
        "actor_type": row.actor_type,
        "actor_name": row.actor_name,
        "action": row.action,
        "resource_type": row.resource_type,
        "resource_id": row.resource_id,
        "client_ip": row.client_ip,
        "request_id": row.request_id,
        "detail": row.detail,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


@router.get("", dependencies=[Depends(require_role("admin"))])
async def list_audit_log(
    db: AsyncSession = Depends(get_db),
    actor_name: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    action: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    query = select(AuditLog)
    if actor_name:
        query = query.where(AuditLog.actor_name == actor_name)
    if resource_type:
        query = query.where(AuditLog.resource_type == resource_type)
    if resource_id:
        query = query.where(AuditLog.resource_id == resource_id)
    if action:
        query = query.where(AuditLog.action == action)
    if since:
        query = query.where(AuditLog.created_at >= since)
    if until:
        query = query.where(AuditLog.created_at <= until)

    query = query.order_by(AuditLog.created_at.desc()).limit(limit).offset(offset)
    result = await db.execute(query)
    return [_to_dict(row) for row in result.scalars()]
