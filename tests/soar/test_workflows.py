import pytest
from unittest.mock import MagicMock
from soar.workflows.base import (
    BaseWorkflow, ScheduledWorkflow, WebhookWorkflow, ManualWorkflow, WorkflowResult
)


def test_workflow_result():
    from datetime import datetime, UTC
    now = datetime.now(UTC)
    result = WorkflowResult(
        success=True,
        workflow_name="test",
        started_at=now,
        finished_at=now,
        duration_seconds=0.0,
        data={"key": "value"},
    )
    assert result.success is True
    assert result.workflow_name == "test"
    assert result.data == {"key": "value"}


def test_base_workflow_type():
    assert BaseWorkflow.workflow_type == "manual"


def test_scheduled_workflow_type():
    wf = ScheduledWorkflow()
    assert wf.workflow_type == "scheduled"


def test_webhook_workflow_type():
    wf = WebhookWorkflow()
    assert wf.workflow_type == "webhook"


def test_manual_workflow_type():
    wf = ManualWorkflow()
    assert wf.workflow_type == "manual"


def test_base_workflow_execute_success():
    class TestWorkflow(ManualWorkflow):
        def run(self, context):
            return {"result": "ok"}

    wf = TestWorkflow()
    result = wf.execute({"key": "value"})
    assert result.success is True
    assert result.data == {"result": "ok"}
    assert result.duration_seconds >= 0


def test_base_workflow_execute_failure():
    class FailingWorkflow(ManualWorkflow):
        def run(self, context):
            raise ValueError("test error")

    wf = FailingWorkflow()
    result = wf.execute({})
    assert result.success is False
    assert result.error is not None
    assert "test error" in str(result.error)


def test_base_workflow_run_not_implemented():
    wf = ManualWorkflow()
    with pytest.raises(NotImplementedError):
        wf.run({})
