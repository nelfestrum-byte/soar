import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from orchestrator.core.queue.redis_queue import RedisQueue
from orchestrator.models.job import WorkflowJob


@pytest.mark.asyncio
async def test_redis_queue_push_with_pool():
    with patch('orchestrator.core.queue.redis_queue.aioredis') as mock_redis:
        mock_pool = AsyncMock()
        mock_redis.ConnectionPool.return_value = mock_pool
        mock_redis.Redis.return_value = AsyncMock()

        queue = RedisQueue("redis://localhost:6379/0", max_connections=10)
        job = WorkflowJob(workflow_name="test")

        await queue.push(job)

        mock_redis.ConnectionPool.assert_called_once_with(
            "redis://localhost:6379/0",
            max_connections=10,
            decode_responses=True
        )
