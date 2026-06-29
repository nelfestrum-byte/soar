import asyncio
import os
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse
from sse_starlette.sse import EventSourceResponse
from orchestrator.models.job import JobStatus

router = APIRouter(prefix="/logs", tags=["logs"])


@router.get("/{job_id}")
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


@router.get("/{job_id}/stream")
async def stream_log(job_id: str, request: Request):
    job_store = request.app.state.job_store
    job = await job_store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if not job.log_path:
        raise HTTPException(status_code=404, detail="No log path for job")

    async def event_generator():
        with open(job.log_path, "r") as f:
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
