import pytest
import asyncio
from orchestrator.core.queue.memory import InMemoryQueue
from orchestrator.models.job import WorkflowJob, JobStatus


@pytest.mark.asyncio
async def test_memory_queue_push_pop():
    queue = InMemoryQueue()
    job = WorkflowJob(workflow_name="test")
    await queue.push(job)
    assert await queue.size() == 1

    popped = await queue.pop(timeout=0.1)
    assert popped is not None
    assert popped.workflow_name == "test"
    assert await queue.size() == 0


@pytest.mark.asyncio
async def test_memory_queue_pop_empty():
    queue = InMemoryQueue()
    result = await queue.pop(timeout=0.1)
    assert result is None


@pytest.mark.asyncio
async def test_memory_queue_push_multiple():
    queue = InMemoryQueue()
    for i in range(5):
        await queue.push(WorkflowJob(workflow_name=f"wf_{i}"))
    assert await queue.size() == 5

    for i in range(5):
        job = await queue.pop(timeout=0.1)
        assert job.workflow_name == f"wf_{i}"


@pytest.mark.asyncio
async def test_memory_queue_clear():
    queue = InMemoryQueue()
    for i in range(3):
        await queue.push(WorkflowJob(workflow_name=f"wf_{i}"))
    assert await queue.size() == 3

    await queue.clear()
    assert await queue.size() == 0
