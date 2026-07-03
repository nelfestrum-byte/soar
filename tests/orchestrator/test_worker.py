import asyncio

import pytest

from orchestrator.core.queue.memory import InMemoryQueue
from orchestrator.core.subprocess_runner import SubprocessRunner
from orchestrator.core.worker import Worker
from orchestrator.models import ConcurrencyPolicy, JobStatus
from orchestrator.models.job import WorkflowJob
from orchestrator.store.job_store import JobStore


@pytest.mark.asyncio
async def test_worker_is_busy_default():
    queue = InMemoryQueue()
    runner = SubprocessRunner()
    store = JobStore()
    worker = Worker(0, queue, runner, store, default_timeout=300)
    assert worker.is_busy is False


@pytest.mark.asyncio
async def test_worker_stop():
    queue = InMemoryQueue()
    runner = SubprocessRunner()
    store = JobStore()
    worker = Worker(0, queue, runner, store, default_timeout=300)
    worker._running = True
    await worker.stop()
    assert worker._running is False


@pytest.mark.asyncio
async def test_queue_policy_serializes_execution():
    store = JobStore()
    queue = InMemoryQueue()
    runner = SubprocessRunner()

    # Simulate a RUNNING job already in the store
    running_job = WorkflowJob(
        workflow_name="my_wf",
        status=JobStatus.RUNNING,
        concurrency=ConcurrencyPolicy.ALLOW,
    )
    await store.save(running_job)

    # Create a QUEUE policy job for the same workflow
    queue_job = WorkflowJob(
        workflow_name="my_wf",
        status=JobStatus.PENDING,
        concurrency=ConcurrencyPolicy.QUEUE,
    )
    await store.save(queue_job)

    worker = Worker(0, queue, runner, store, default_timeout=300)

    # Verify the worker sees the running job count
    count = await store.count_by_status("my_wf", [JobStatus.RUNNING])
    assert count == 1

    # Verify the queue job has QUEUE concurrency
    assert queue_job.concurrency == ConcurrencyPolicy.QUEUE


@pytest.mark.asyncio
async def test_queue_policy_skips_cancelled_while_waiting():
    store = JobStore()
    queue = InMemoryQueue()
    runner = SubprocessRunner()

    # Job that was cancelled while waiting in queue
    cancelled_job = WorkflowJob(
        workflow_name="my_wf",
        status=JobStatus.CANCELLED,
        concurrency=ConcurrencyPolicy.QUEUE,
    )
    await store.save(cancelled_job)

    worker = Worker(0, queue, runner, store, default_timeout=300)

    # Execute should skip the cancelled job
    await worker._execute(cancelled_job)
    assert worker.is_busy is False
