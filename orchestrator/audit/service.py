from datetime import UTC, datetime

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.audit.models import AuditLog
from orchestrator.auth.dependencies import CurrentUser
from orchestrator.core.net import resolve_client_ip


def git_author(user: CurrentUser) -> tuple[str, str]:
    """Acting user as a git commit author (users have no email field today —
    synthesize one so `git log` still shows a stable, attributable identity)."""
    name = user.username or f"user-{user.id}"
    return name, f"{name}@soar.local"


async def record(
    db: AsyncSession,
    *,
    user: CurrentUser,
    action: str,
    resource_type: str,
    resource_id: str,
    request: Request,
    detail: dict | None = None,
) -> None:
    entry = AuditLog(
        actor_id=user.id,
        actor_type=user.type,
        actor_name=user.username or str(user.id),
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        client_ip=resolve_client_ip(request),
        request_id=getattr(request.state, "request_id", None),
        detail=detail,
        created_at=datetime.now(UTC),
    )
    db.add(entry)
    await db.commit()
