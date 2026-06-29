import pytest
from orchestrator.models.workflow_meta import WorkflowMeta
from orchestrator.models import ConcurrencyPolicy


def test_workflow_meta_init():
    meta = WorkflowMeta(name="test", type="manual")
    assert meta.name == "test"
    assert meta.type == "manual"
    assert meta.enabled is True
    assert meta.concurrency == ConcurrencyPolicy.FORBID


def test_workflow_meta_scheduled():
    meta = WorkflowMeta(
        name="scheduled_wf",
        type="scheduled",
        schedule="*/10 * * * *",
    )
    assert meta.schedule == "*/10 * * * *"


def test_workflow_meta_webhook():
    meta = WorkflowMeta(
        name="webhook_wf",
        type="webhook",
        path="/webhook/test",
        token="secret123",
    )
    assert meta.path == "/webhook/test"
    assert meta.token == "secret123"
