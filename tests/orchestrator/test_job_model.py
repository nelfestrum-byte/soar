import pytest
from datetime import datetime, UTC
from orchestrator.models.job import WorkflowJob, JobStatus


def test_workflow_job_init():
    job = WorkflowJob(workflow_name="test", workflow_type="manual", triggered_by="user")
    assert job.workflow_name == "test"
    assert job.workflow_type == "manual"
    assert job.triggered_by == "user"
    assert job.status == JobStatus.PENDING
    assert job.pid is None
    assert job.result_success is None


def test_workflow_job_default_values():
    job = WorkflowJob()
    assert job.id is not None
    assert len(job.id) > 0
    assert job.context == {}
    assert job.triggered_at is not None


def test_workflow_job_duration_seconds():
    job = WorkflowJob()
    job.started_at = datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)
    job.finished_at = datetime(2024, 1, 1, 10, 0, 10, tzinfo=UTC)
    assert job.duration_seconds == 10.0


def test_workflow_job_duration_seconds_no_times():
    job = WorkflowJob()
    assert job.duration_seconds is None


def test_workflow_job_to_dict():
    job = WorkflowJob(workflow_name="test", triggered_by="user")
    d = job.to_dict()
    assert d["workflow_name"] == "test"
    assert d["triggered_by"] == "user"
    assert d["status"] == "pending"
    assert "id" in d
    assert "triggered_at" in d
