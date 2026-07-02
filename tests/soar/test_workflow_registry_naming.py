"""Tests for workflow registry naming consistency.

BUG NEW-1: PUT /workflows/{name}/code accepts snake_case name in URL but registers
workflow under PascalCase class name. All subsequent API calls require PascalCase.
"""
import importlib.util
import sys
import tempfile
from pathlib import Path

import pytest

from soar.workflows import WorkflowRegistry
from soar.workflows.base import ManualWorkflow


@pytest.fixture
def registry():
    return WorkflowRegistry()


@pytest.fixture
def tmp_workflows_dir(tmp_path):
    """Create a temporary directory with a workflow file."""
    return tmp_path


def _create_workflow_file(directory: Path, filename: str, class_name: str):
    """Helper to create a workflow .py file with given filename and class name."""
    code = f'''
from soar.workflows.base import ManualWorkflow

class {class_name}(ManualWorkflow):
    def run(self, context):
        return {{"status": "ok"}}
'''
    (directory / filename).write_text(code)


class TestWorkflowRegistryNaming:
    """Registry should use filename (snake_case) as key, not class name (PascalCase)."""

    def test_external_workflow_registered_by_filename(self, registry, tmp_workflows_dir):
        """External workflow should be registered under filename, not class name."""
        _create_workflow_file(tmp_workflows_dir, "my_workflow.py", "MyWorkflow")

        registry.init(external_dir=str(tmp_workflows_dir))

        # Should be findable by filename (snake_case)
        assert registry.get_class("my_workflow") is not None, (
            "Workflow should be registered as 'my_workflow' (filename), not 'MyWorkflow' (class name)"
        )

    def test_external_workflow_not_registered_by_class_name(self, registry, tmp_workflows_dir):
        """External workflow should NOT be registered under class name."""
        _create_workflow_file(tmp_workflows_dir, "my_workflow.py", "MyWorkflow")

        registry.init(external_dir=str(tmp_workflows_dir))

        # Should NOT be findable by class name
        assert registry.get_class("MyWorkflow") is None, (
            "Workflow should not be registered as 'MyWorkflow' (class name)"
        )

    def test_execute_uses_filename_not_class_name(self, registry, tmp_workflows_dir):
        """execute() should accept filename, not class name."""
        _create_workflow_file(tmp_workflows_dir, "test_exec.py", "TestExec")

        registry.init(external_dir=str(tmp_workflows_dir))

        # Should execute by filename
        result = registry.execute("test_exec", {})
        assert result.success is True

    def test_execute_rejects_class_name(self, registry, tmp_workflows_dir):
        """execute() should reject class name."""
        _create_workflow_file(tmp_workflows_dir, "test_exec.py", "TestExec")

        registry.init(external_dir=str(tmp_workflows_dir))

        # Should raise ValueError for class name
        with pytest.raises(ValueError, match="not found"):
            registry.execute("TestExec", {})

    def test_list_returns_filename_not_class_name(self, registry, tmp_workflows_dir):
        """list() should return filename, not class name."""
        _create_workflow_file(tmp_workflows_dir, "my_wf.py", "MyWf")

        registry.init(external_dir=str(tmp_workflows_dir))

        items = registry.list()
        names = [item["name"] for item in items]
        assert "my_wf" in names
        assert "MyWf" not in names

    def test_multiple_workflows_use_filenames(self, registry, tmp_workflows_dir):
        """Multiple workflows should all use filenames."""
        _create_workflow_file(tmp_workflows_dir, "alpha_workflow.py", "AlphaWorkflow")
        _create_workflow_file(tmp_workflows_dir, "beta_workflow.py", "BetaWorkflow")

        registry.init(external_dir=str(tmp_workflows_dir))

        items = registry.list()
        names = [item["name"] for item in items]
        assert "alpha_workflow" in names
        assert "beta_workflow" in names
        assert "AlphaWorkflow" not in names
        assert "BetaWorkflow" not in names

    def test_builtin_workflow_registered_by_filename(self, registry):
        """Built-in workflows should also be registered by filename."""
        registry.init()

        items = registry.list()
        for item in items:
            # No workflow should have PascalCase name (class name)
            assert item["name"][0].islower() or "_" in item["name"], (
                f"Workflow '{item['name']}' appears to be registered by class name, not filename"
            )

    def test_deleted_workflow_removed_after_reinit(self, tmp_workflows_dir):
        """After deleting a workflow file, re-init should remove it from registry.

        This simulates the real orchestrator behavior where the same registry
        singleton is re-initialized after a workflow file is deleted.
        """
        registry = WorkflowRegistry()
        _create_workflow_file(tmp_workflows_dir, "to_delete.py", "ToDelete")

        registry.init(external_dir=str(tmp_workflows_dir))
        assert registry.get_class("to_delete") is not None

        # Delete the file
        (tmp_workflows_dir / "to_delete.py").unlink()

        # Re-init same registry instance (like orchestrator does)
        registry.init(external_dir=str(tmp_workflows_dir))
        assert registry.get_class("to_delete") is None, (
            "Deleted workflow should be removed from registry after re-init"
        )

    def test_deleted_workflow_not_in_list_after_reinit(self, tmp_workflows_dir):
        """After deleting a workflow file, it should not appear in list().

        This simulates the real orchestrator behavior where the same registry
        singleton is re-initialized after a workflow file is deleted.
        """
        registry = WorkflowRegistry()
        _create_workflow_file(tmp_workflows_dir, "temp_wf.py", "TempWf")

        registry.init(external_dir=str(tmp_workflows_dir))
        names = [item["name"] for item in registry.list()]
        assert "temp_wf" in names

        # Delete the file
        (tmp_workflows_dir / "temp_wf.py").unlink()

        # Re-init same registry instance (like orchestrator does)
        registry.init(external_dir=str(tmp_workflows_dir))
        names2 = [item["name"] for item in registry.list()]
        assert "temp_wf" not in names2, (
            "Deleted workflow should not appear in list after re-init"
        )
