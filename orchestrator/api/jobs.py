from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from orchestrator.auth.dependencies import require_role
from orchestrator.core.job_manager import WorkflowDisabledError
from orchestrator.models.job import JobStatus

router = APIRouter(prefix="/jobs", tags=["jobs"])

_RO = ("viewer", "analyst", "service", "admin")
_RW = ("analyst", "service", "admin")
_ANALYST = ("analyst", "admin")


class JobRequest(BaseModel):
    workflow_name: str
    context: dict = {}


@router.post("", status_code=202, dependencies=[Depends(require_role(*_RW))])
async def create_job(body: JobRequest, request: Request):
    job_manager = request.app.state.job_manager
    try:
        job = await job_manager.enqueue(
            workflow_name=body.workflow_name,
            context=body.context,
            triggered_by="user",
        )
    except ValueError:
        raise HTTPException(status_code=404, detail="Workflow not found") from None
    except WorkflowDisabledError:
        raise HTTPException(status_code=409, detail="Workflow is disabled") from None
    except Exception:
        raise HTTPException(status_code=409, detail="Failed to enqueue job") from None
    return job.to_dict()


@router.get("", dependencies=[Depends(require_role(*_RO))])
async def list_jobs(
    request: Request,
    workflow_name: str | None = None,
    status: str | None = None,
    triggered_by: str | None = None,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    job_store = request.app.state.job_store
    status_enum = JobStatus(status) if status else None
    jobs = await job_store.list(
        workflow_name=workflow_name,
        status=status_enum,
        triggered_by=triggered_by,
        limit=limit,
        offset=offset,
    )
    return [j.to_dict() for j in jobs]


@router.get("/{job_id}", dependencies=[Depends(require_role(*_RO))])
async def get_job(job_id: str, request: Request):
    job_store = request.app.state.job_store
    job = await job_store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job.to_dict()


@router.post("/{job_id}/cancel", dependencies=[Depends(require_role(*_ANALYST))])
async def cancel_job(job_id: str, request: Request):
    job_manager = request.app.state.job_manager
    try:
        job = await job_manager.cancel(job_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from None
    return job.to_dict()
