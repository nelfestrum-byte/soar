from fastapi import APIRouter, Request

router = APIRouter(tags=["status"])


@router.get("/status")
async def get_status(request: Request):
    pool = request.app.state.pool
    job_store = request.app.state.job_store
    scheduler = request.app.state.scheduler
    config = request.app.state.config
    queue = request.app.state.queue

    queue_size = await queue.size()
    job_stats = await job_store.stats()

    queue_health = await queue.health()
    queue_info = {
        "backend": config.queue.backend,
        "pending": queue_size,
        "connected": queue_health["connected"],
    }

    return {
        "workers": pool.status,
        "queue": queue_info,
        "jobs": job_stats,
        "scheduler": {
            "next_runs": scheduler.next_runs(),
        },
    }
