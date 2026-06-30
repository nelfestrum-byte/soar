from unittest.mock import patch

import pytest

from soar.workflows import WorkflowRegistry


def test_workflow_registry_init():
    registry = WorkflowRegistry()
    assert len(registry._workflows) == 0


def test_workflow_registry_discover():
    registry = WorkflowRegistry()
    registry.init()
    assert len(registry._workflows) > 0
    assert "MyAlertCheck" in registry._workflows


def test_workflow_registry_list():
    registry = WorkflowRegistry()
    registry.init()
    result = registry.list()
    assert isinstance(result, list)
    assert len(result) > 0
    names = [wf["name"] for wf in result]
    assert "MyAlertCheck" in names


def test_workflow_registry_get():
    registry = WorkflowRegistry()
    registry.init()
    result = registry.get("MyAlertCheck")
    assert result is not None
    assert result["name"] == "MyAlertCheck"
    assert result["type"] == "scheduled"


def test_workflow_registry_get_not_found():
    registry = WorkflowRegistry()
    registry.init()
    result = registry.get("NonExistentWorkflow")
    assert result is None


@patch("soar.workflows.alert_check.connectors")
def test_workflow_registry_execute(mock_connectors):
    mock_connectors.elastic1.query.return_value = []
    registry = WorkflowRegistry()
    registry.init()
    result = registry.execute("MyAlertCheck", context={})
    assert result.success is True


def test_workflow_registry_execute_not_found():
    registry = WorkflowRegistry()
    registry.init()
    with pytest.raises(ValueError, match="not found"):
        registry.execute("NonExistentWorkflow")
