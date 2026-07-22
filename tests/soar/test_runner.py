import json

import pytest

from soar import runner


def test_main_missing_workflow_prints_traceback_and_exits(monkeypatch, capsys):
    monkeypatch.setenv("SOAR_WORKFLOW_NAME", "nonexistent_workflow_xyz")
    monkeypatch.setenv("SOAR_CONTEXT", "{}")

    with pytest.raises(SystemExit) as exc_info:
        runner.main()

    assert exc_info.value.code == 1
    output = json.loads(capsys.readouterr().out.strip())
    assert output["success"] is False
    assert output["workflow_name"] == "nonexistent_workflow_xyz"
    assert output["data"] is None
    assert "ValueError" in output["error"]
    assert "nonexistent_workflow_xyz" in output["error"]


def test_main_workflow_run_failure_includes_full_traceback(monkeypatch, capsys):
    from soar.workflows import workflows as wf_registry
    from soar.workflows.base import ManualWorkflow

    class FailingWorkflow(ManualWorkflow):
        def run(self, context):
            raise ValueError("kaboom")

    wf_registry._workflows["failing_test_workflow"] = FailingWorkflow
    try:
        monkeypatch.setenv("SOAR_WORKFLOW_NAME", "failing_test_workflow")
        monkeypatch.setenv("SOAR_CONTEXT", "{}")

        with pytest.raises(SystemExit) as exc_info:
            runner.main()

        assert exc_info.value.code == 1
        output = json.loads(capsys.readouterr().out.strip())
        assert output["success"] is False
        assert "ValueError" in output["error"]
        assert "kaboom" in output["error"]
        assert "test_runner.py" in output["error"]
    finally:
        wf_registry._workflows.pop("failing_test_workflow", None)
