import json
from datetime import datetime
from typing import Optional

from loguru import logger
from redis import asyncio as aioredis
from redis.exceptions import ConnectionError, TimeoutError

from orchestrator.core.queue.base import AbstractJobQueue
from orchestrator.models import ConcurrencyPolicy
from orchestrator.models.job import WorkflowJob


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
        if self._redis is not None:
            try:
                import asyncio
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.ensure_future(self._redis.close())
                else:
                    loop.run_until_complete(self._redis.close())
            except Exception:
                pass
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
            "triggered_at": job.triggered_at.isoformat() if job.triggered_at else None,
            "concurrency": job.concurrency.value,
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
            # NOTE: brpop is atomic but message loss is possible if connection drops
            # between item removal and response receipt. For at-least-once delivery,
            # consider RPOPLPUSH or Redis Streams in the future.
            result = await self._redis.brpop(self._key, timeout=timeout)
            if result is None:
                return None
            _, data = result
            item = json.loads(data)
            triggered_at = None
            if item.get("triggered_at"):
                triggered_at = datetime.fromisoformat(item["triggered_at"])
            concurrency = ConcurrencyPolicy(item["concurrency"]) if item.get("concurrency") else ConcurrencyPolicy.FORBID
            return WorkflowJob(
                id=item["id"],
                workflow_name=item["workflow_name"],
                workflow_type=item["workflow_type"],
                triggered_by=item["triggered_by"],
                context=item["context"],
                log_path=item.get("log_path"),
                timeout=item.get("timeout"),
                triggered_at=triggered_at,
                concurrency=concurrency,
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

    async def health(self) -> dict:
        await self._ensure_connected()
        try:
            await self._redis.ping()
            size = await self._redis.llen(self._key)
            return {"connected": True, "size": size}
        except Exception:
            return {"connected": False, "size": 0}
