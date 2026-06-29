import pytest
from orchestrator.models import JobStatus, ConcurrencyPolicy


def test_job_status_values():
    assert JobStatus.PENDING == "pending"
    assert JobStatus.RUNNING == "running"
    assert JobStatus.COMPLETED == "completed"
    assert JobStatus.FAILED == "failed"
    assert JobStatus.TIMEOUT == "timeout"
    assert JobStatus.CANCELLED == "cancelled"


def test_concurrency_policy_values():
    assert ConcurrencyPolicy.FORBID == "forbid"
    assert ConcurrencyPolicy.QUEUE == "queue"
    assert ConcurrencyPolicy.ALLOW == "allow"
