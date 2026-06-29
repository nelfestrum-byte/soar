import asyncio
from datetime import datetime, UTC
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from loguru import logger


class OrchestratorScheduler:
    def __init__(self, job_manager):
        self._job_manager = job_manager
        self._scheduler = AsyncIOScheduler()
        self._jobs: dict[str, str] = {}

    async def start(self, workflows: list) -> None:
        self._scheduler.start()
        for meta in workflows:
            if meta.type == "scheduled" and meta.enabled:
                self._add_job(meta)
        logger.info(f"Scheduler started with {len(self._jobs)} jobs")

    def _add_job(self, meta) -> None:
        job_id = f"scheduled_{meta.name}"

        async def trigger():
            try:
                await self._job_manager.enqueue(
                    workflow_name=meta.name,
                    context={},
                    triggered_by="scheduler",
                )
            except Exception as e:
                logger.error(f"Scheduled trigger failed for {meta.name}: {e}")

        if meta.schedule:
            trigger_obj = CronTrigger.from_crontab(meta.schedule)
        elif meta.interval:
            trigger_obj = IntervalTrigger(seconds=meta.interval)
        else:
            return

        self._scheduler.add_job(trigger, trigger_obj, id=job_id, replace_existing=True)
        self._jobs[meta.name] = job_id

    async def reload(self, workflows: list) -> None:
        for job_id in self._jobs.values():
            try:
                self._scheduler.remove_job(job_id)
            except Exception:
                pass
        self._jobs.clear()

        for meta in workflows:
            if meta.type == "scheduled" and meta.enabled:
                self._add_job(meta)
        logger.info(f"Scheduler reloaded with {len(self._jobs)} jobs")

    async def stop(self) -> None:
        self._scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")

    def next_runs(self, limit: int = 10) -> list[dict]:
        result = []
        for job in self._scheduler.get_jobs():
            next_run = job.next_run_time
            if next_run:
                result.append({
                    "workflow": job.id.replace("scheduled_", ""),
                    "at": next_run.isoformat(),
                })
        return sorted(result, key=lambda x: x["at"])[:limit]
