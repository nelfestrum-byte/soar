import pytest
import redis.asyncio as aioredis
from orchestrator.core.queue.redis_queue import RedisQueue
from orchestrator.models.job import WorkflowJob


@pytest.fixture
async def redis_queue():
    try:
        queue = RedisQueue("redis://localhost:6379/1")
        await queue.clear()
        yield queue
        await queue.clear()
    except Exception:
        pytest.skip("Redis server not available")


@pytest.mark.asyncio
async def test_redis_integration_push_pop(redis_queue):
    job = WorkflowJob(workflow_name="integration_test")
    await redis_queue.push(job)

    assert await redis_queue.size() == 1

    popped = await redis_queue.pop(timeout=0.1)
    assert popped is not None
    assert popped.workflow_name == "integration_test"
    assert await redis_queue.size() == 0


@pytest.mark.asyncio
async def test_redis_integration_multiple_jobs(redis_queue):
    for i in range(5):
        await redis_queue.push(WorkflowJob(workflow_name=f"wf_{i}"))

    assert await redis_queue.size() == 5

    for i in range(5):
        job = await redis_queue.pop(timeout=0.1)
        assert job.workflow_name == f"wf_{i}"


@pytest.mark.asyncio
async def test_redis_integration_clear(redis_queue):
    for i in range(3):
        await redis_queue.push(WorkflowJob(workflow_name=f"wf_{i}"))

    assert await redis_queue.size() == 3

    await redis_queue.clear()
    assert await redis_queue.size() == 0
