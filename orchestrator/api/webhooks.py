import secrets

from fastapi import APIRouter, HTTPException, Request

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/{workflow_name}", status_code=202)
async def handle_webhook(workflow_name: str, request: Request):
    job_manager = request.app.state.job_manager
    meta = job_manager._metas.get(workflow_name)

    if not meta:
        raise HTTPException(status_code=404, detail="Workflow not found")

    if meta.type != "webhook":
        raise HTTPException(status_code=404, detail="Not a webhook workflow")

    token = request.headers.get("X-Webhook-Token", "")
    if not meta.token or not secrets.compare_digest(token, meta.token):
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
    return {"job_id": job.id}
