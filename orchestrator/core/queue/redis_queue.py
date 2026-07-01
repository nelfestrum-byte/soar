import json
from typing import Optional

from redis import asyncio as aioredis
from redis.exceptions import ConnectionError, TimeoutError

from orchestrator.core.queue.base import AbstractJobQueue
from orchestrator.models.job import WorkflowJob
from loguru import logger


class RedisQueue(AbstractJobQueue):
    def __init__(
        self,
        redis_url: str,
        max_connections: int = 10,
        push_timeout: float = 5.0,
        pop_timeout: float = 1.0,
    ):
        self._redis_url = redis_url
        self._max_connections = max_connections
        self._push_timeout = push_timeout
        self._pop_timeout = pop_timeout
        self._key = "soar:jobs"
        self._redis: Optional[aioredis.Redis] = None
        self._connect()

    def _connect(self):
        self._redis = aioredis.from_url(
            self._redis_url,
            max_connections=self._max_connections,
            decode_responses=True,
        )

    async def _ensure_connected(self):
        if self._redis is None:
            self._connect()

    async def push(self, job: WorkflowJob) -> None:
        await self._ensure_connected()
        data = json.dumps({
            "id": job.id,
            "workflow_name": job.workflow_name,
            "workflow_type": job.workflow_type,
            "triggered_by": job.triggered_by,
            "context": job.context,
            "log_path": job.log_path,
            "timeout": job.timeout,
        })
        try:
            await self._redis.lpush(self._key, data)
        except (ConnectionError, TimeoutError) as e:
            logger.error(f"Redis push failed: {e}")
            self._connect()
            await self._redis.lpush(self._key, data)

    async def pop(self, timeout: float = 1.0) -> Optional[WorkflowJob]:
        await self._ensure_connected()
        try:
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
        except (ConnectionError, TimeoutError) as e:
            logger.error(f"Redis pop failed: {e}")
            self._connect()
            return None

    async def size(self) -> int:
        await self._ensure_connected()
        try:
            return await self._redis.llen(self._key)
        except (ConnectionError, TimeoutError) as e:
            logger.error(f"Redis size failed: {e}")
            return 0

    async def clear(self) -> None:
        await self._ensure_connected()
        try:
            await self._redis.delete(self._key)
        except (ConnectionError, TimeoutError) as e:
            logger.error(f"Redis clear failed: {e}")
