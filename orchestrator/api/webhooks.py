import secrets

from fastapi import APIRouter, Depends, HTTPException, Request
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.audit import service as audit_service
from orchestrator.auth.dependencies import CurrentUser
from orchestrator.core.net import resolve_client_ip
from orchestrator.db.session import get_db

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/{workflow_name}", status_code=202)
async def handle_webhook(workflow_name: str, request: Request, db: AsyncSession = Depends(get_db)):
    job_manager = request.app.state.job_manager
    meta = job_manager.get_meta(workflow_name)

    if not meta:
        raise HTTPException(status_code=404, detail="Workflow not found")

    if meta.type != "webhook":
        raise HTTPException(status_code=404, detail="Not a webhook workflow")

    token = request.headers.get("X-Webhook-Token", "")
    if not meta.token or not secrets.compare_digest(token, meta.token):
        logger.bind(workflow_name=workflow_name, client_ip=resolve_client_ip(request)).warning(
            "webhook.invalid_token"
        )
        raise HTTPException(status_code=403, detail="Invalid token")

    if not meta.enabled:
        raise HTTPException(status_code=409, detail="Workflow is disabled")

    body = await request.json()
    try:
        job = await job_manager.enqueue(
            workflow_name=workflow_name,
            context={"payload": body},
            triggered_by="webhook",
        )
    except ValueError:
        raise HTTPException(status_code=404, detail="Workflow not found or disabled") from None
    except Exception:
        raise HTTPException(status_code=409, detail="Failed to enqueue job") from None

    actor = CurrentUser(id=0, role="service", type="webhook", username=f"webhook:{workflow_name}")
    await audit_service.record(
        db, user=actor, action="job.create", resource_type="job",
        resource_id=job.id, request=request,
        detail={"workflow_name": workflow_name, "triggered_by": "webhook"},
    )
    return {"job_id": job.id}
