import asyncio
import os

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse
from sse_starlette.sse import EventSourceResponse

from orchestrator.auth.dependencies import require_role
from orchestrator.models.job import JobStatus

router = APIRouter(prefix="/logs", tags=["logs"])

_RW = ("analyst", "service", "admin", "agent")


@router.get("/{job_id}", dependencies=[Depends(require_role(*_RW))])
async def get_log(job_id: str, request: Request):
    job_store = request.app.state.job_store
    job = await job_store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if not job.log_path or not os.path.exists(job.log_path):
        raise HTTPException(status_code=404, detail="Log file not found")
    with open(job.log_path) as f:
        content = f.read()
    return PlainTextResponse(content)


@router.get("/{job_id}/stream", dependencies=[Depends(require_role(*_RW))])
async def stream_log(job_id: str, request: Request):
    job_store = request.app.state.job_store
    job = await job_store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if not job.log_path:
        raise HTTPException(status_code=404, detail="No log path for job")

    async def event_generator():
        # log_path is assigned at enqueue time but the file itself is only
        # created once the worker picks up the job (SubprocessRunner.start) —
        # a stream opened while the job is still PENDING would otherwise hit
        # open()'s FileNotFoundError mid-generator (M5).
        while not os.path.exists(job.log_path):
            current_job = await job_store.get(job_id)
            if current_job and current_job.status not in (JobStatus.PENDING, JobStatus.RUNNING):
                return
            await asyncio.sleep(0.5)

        with open(job.log_path) as f:
            while True:
                line = f.readline()
                if line:
                    yield line.strip()
                else:
                    current_job = await job_store.get(job_id)
                    if current_job and current_job.status not in (
                        JobStatus.PENDING, JobStatus.RUNNING
                    ):
                        break
                    await asyncio.sleep(0.5)

    return EventSourceResponse(event_generator())
