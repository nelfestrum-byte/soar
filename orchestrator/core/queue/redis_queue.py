import json

from redis import asyncio as aioredis

from orchestrator.core.queue.base import AbstractJobQueue
from orchestrator.models.job import WorkflowJob


class RedisQueue(AbstractJobQueue):
    def __init__(self, redis_url: str):
        self._redis = aioredis.from_url(redis_url)
        self._key = "soar:jobs"

    async def push(self, job: WorkflowJob) -> None:
        data = json.dumps({
            "id": job.id,
            "workflow_name": job.workflow_name,
            "workflow_type": job.workflow_type,
            "triggered_by": job.triggered_by,
            "context": job.context,
            "log_path": job.log_path,
            "timeout": job.timeout,
        })
        await self._redis.lpush(self._key, data)

    async def pop(self, timeout: float = 1.0) -> WorkflowJob | None:
        result = await self._redis.brpop(self._key, timeout=timeout)
        if result is None:
            return None
        _, data = result
        item = json.loads(data)
        return WorkflowJob(
            id=item["id"],
            workflow_name=item["workflow_name"],
            workflow_type=item["workflow_type"],
            triggered_by=item["triggered_by"],
            context=item["context"],
            log_path=item.get("log_path"),
            timeout=item.get("timeout"),
        )

    async def size(self) -> int:
        return await self._redis.llen(self._key)

    async def clear(self) -> None:
        await self._redis.delete(self._key)
