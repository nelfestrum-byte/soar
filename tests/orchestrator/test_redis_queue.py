import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from orchestrator.core.queue.redis_queue import RedisQueue
from orchestrator.models.job import WorkflowJob


@pytest.mark.asyncio
async def test_redis_queue_push_with_pool():
    with patch('orchestrator.core.queue.redis_queue.aioredis') as mock_redis:
        mock_redis.from_url.return_value = AsyncMock()

        queue = RedisQueue("redis://localhost:6379/0", max_connections=10)
        job = WorkflowJob(workflow_name="test")

        await queue.push(job)

        mock_redis.from_url.assert_called_once_with(
            "redis://localhost:6379/0",
            max_connections=10,
            decode_responses=True,
        )


@pytest.mark.asyncio
async def test_redis_queue_push_success():
    with patch('orchestrator.core.queue.redis_queue.aioredis') as mock_redis:
        mock_redis.from_url.return_value = AsyncMock()

        queue = RedisQueue("redis://localhost:6379/0")
        job = WorkflowJob(workflow_name="test")

        await queue.push(job)

        queue._redis.lpush.assert_called_once()


@pytest.mark.asyncio
async def test_redis_queue_pop_success():
    with patch('orchestrator.core.queue.redis_queue.aioredis') as mock_redis:
        mock_redis.from_url.return_value = AsyncMock()
        mock_redis.from_url.return_value.brpop = AsyncMock(return_value=(
            "soar:jobs",
            '{"id": "123", "workflow_name": "test", "workflow_type": "manual", "triggered_by": "api", "context": {}}',
        ))

        queue = RedisQueue("redis://localhost:6379/0")
        job = await queue.pop()

        assert job is not None
        assert job.workflow_name == "test"


@pytest.mark.asyncio
async def test_redis_queue_pop_empty():
    with patch('orchestrator.core.queue.redis_queue.aioredis') as mock_redis:
        mock_redis.from_url.return_value = AsyncMock()
        mock_redis.from_url.return_value.brpop = AsyncMock(return_value=None)

        queue = RedisQueue("redis://localhost:6379/0")
        job = await queue.pop()

        assert job is None


@pytest.mark.asyncio
async def test_redis_queue_size():
    with patch('orchestrator.core.queue.redis_queue.aioredis') as mock_redis:
        mock_redis.from_url.return_value = AsyncMock()
        mock_redis.from_url.return_value.llen = AsyncMock(return_value=5)

        queue = RedisQueue("redis://localhost:6379/0")
        size = await queue.size()

        assert size == 5


@pytest.mark.asyncio
async def test_redis_queue_clear():
    with patch('orchestrator.core.queue.redis_queue.aioredis') as mock_redis:
        mock_redis.from_url.return_value = AsyncMock()
        mock_redis.from_url.return_value.delete = AsyncMock()

        queue = RedisQueue("redis://localhost:6379/0")
        await queue.clear()

        queue._redis.delete.assert_called_once()


@pytest.mark.asyncio
async def test_redis_queue_concurrency_preserved():
    """B3: concurrency field must survive push→pop round-trip through Redis."""
    import json
    from orchestrator.models import ConcurrencyPolicy

    with patch('orchestrator.core.queue.redis_queue.aioredis') as mock_redis:
        client = AsyncMock()
        mock_redis.from_url.return_value = client

        queue = RedisQueue("redis://localhost:6379/0")
        job = WorkflowJob(workflow_name="wf", concurrency=ConcurrencyPolicy.QUEUE)

        # Capture what gets pushed to Redis
        pushed_data = []
        async def fake_lpush(key, data):
            pushed_data.append(data)
        client.lpush = fake_lpush

        await queue.push(job)

        assert pushed_data, "nothing was pushed"
        payload = json.loads(pushed_data[0])
        assert payload.get("concurrency") == ConcurrencyPolicy.QUEUE.value

        # Now simulate pop returning that same payload
        client.brpop = AsyncMock(return_value=("soar:jobs", pushed_data[0]))
        popped = await queue.pop()

        assert popped is not None
        assert popped.concurrency == ConcurrencyPolicy.QUEUE


@pytest.mark.asyncio
async def test_redis_queue_concurrency_fallback_to_forbid():
    """B3: old messages without concurrency field default to FORBID."""
    import json
    from orchestrator.models import ConcurrencyPolicy

    old_payload = json.dumps({
        "id": "abc", "workflow_name": "wf", "workflow_type": "manual",
        "triggered_by": "api", "context": {},
    })
    with patch('orchestrator.core.queue.redis_queue.aioredis') as mock_redis:
        client = AsyncMock()
        mock_redis.from_url.return_value = client
        client.brpop = AsyncMock(return_value=("soar:jobs", old_payload))

        queue = RedisQueue("redis://localhost:6379/0")
        popped = await queue.pop()

        assert popped is not None
        assert popped.concurrency == ConcurrencyPolicy.FORBID


@pytest.mark.asyncio
async def test_redis_queue_push_connection_error():
    from redis.exceptions import ConnectionError

    with patch('orchestrator.core.queue.redis_queue.aioredis') as mock_redis:
        mock_redis.from_url.return_value = AsyncMock()
        mock_redis.from_url.return_value.lpush = AsyncMock(side_effect=ConnectionError())

        queue = RedisQueue("redis://localhost:6379/0")
        job = WorkflowJob(workflow_name="test")

        with pytest.raises(ConnectionError):
            await queue.push(job)

        assert mock_redis.from_url.call_count == 2
