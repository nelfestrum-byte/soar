import os

from orchestrator.config import OrchestratorConfig

WEBHOOK_WF_CODE = '''from soar.workflows.base import WebhookWorkflow
import secrets


class LoadMetasTokenWf(WebhookWorkflow):
    path = "/webhook/load-metas-test"
    token = secrets.token_urlsafe(32)

    def run(self, context):
        return {"status": "ok"}
'''


def _config(tmp_path) -> OrchestratorConfig:
    config = OrchestratorConfig()
    config.soar.workflows_dir = str(tmp_path / "workflows")
    os.makedirs(config.soar.workflows_dir, exist_ok=True)
    return config


def test_load_workflow_metas_persists_webhook_token_across_calls(tmp_path):
    from orchestrator.main import load_workflow_metas

    config = _config(tmp_path)
    with open(os.path.join(config.soar.workflows_dir, "load_metas_token_wf.py"), "w") as f:
        f.write(WEBHOOK_WF_CODE)

    metas1 = load_workflow_metas(config)
    token1 = next(m.token for m in metas1 if m.name == "load_metas_token_wf")
    assert token1

    metas2 = load_workflow_metas(config)
    token2 = next(m.token for m in metas2 if m.name == "load_metas_token_wf")

    assert token1 == token2


SCHEDULED_WF_CODE = '''from soar.workflows.base import ScheduledWorkflow


class LoadMetasScheduledWf(ScheduledWorkflow):
    """Runs on a schedule."""

    schedule = "*/5 * * * *"
    interval = 300

    def run(self, context):
        return {"status": "ok"}
'''

MANUAL_WF_CODE = '''from soar.workflows.base import ManualWorkflow


class LoadMetasManualWf(ManualWorkflow):
    """Runs manually."""

    def run(self, context):
        return {"status": "ok"}
'''

SIDE_EFFECT_WF_CODE = '''from pathlib import Path
from soar.workflows.base import ManualWorkflow

Path({marker_path!r}).write_text("imported")


class LoadMetasSideEffectWf(ManualWorkflow):
    """Should never be imported by load_workflow_metas."""

    def run(self, context):
        return {{"status": "ok"}}
'''


def test_load_workflow_metas_scheduled_fields_match_import_based_path(tmp_path):
    """Regression: schedule/interval/docstring/type extracted identically to
    the old import-based WorkflowRegistry path."""
    from orchestrator.main import load_workflow_metas

    config = _config(tmp_path)
    with open(os.path.join(config.soar.workflows_dir, "load_metas_scheduled_wf.py"), "w") as f:
        f.write(SCHEDULED_WF_CODE)

    metas = load_workflow_metas(config)
    meta = next(m for m in metas if m.name == "load_metas_scheduled_wf")
    assert meta.type == "scheduled"
    assert meta.schedule == "*/5 * * * *"
    assert meta.interval == 300
    assert meta.docstring == "Runs on a schedule."


def test_load_workflow_metas_manual_fields_match_import_based_path(tmp_path):
    from orchestrator.main import load_workflow_metas

    config = _config(tmp_path)
    with open(os.path.join(config.soar.workflows_dir, "load_metas_manual_wf.py"), "w") as f:
        f.write(MANUAL_WF_CODE)

    metas = load_workflow_metas(config)
    meta = next(m for m in metas if m.name == "load_metas_manual_wf")
    assert meta.type == "manual"
    assert meta.docstring == "Runs manually."


def test_load_workflow_metas_does_not_import_workflow_module(tmp_path):
    """Non-import guarantee: a workflow file with a top-level side effect
    (writing a marker file) must not have that side effect triggered by
    load_workflow_metas — metadata comes from AST, not from import."""
    from orchestrator.main import load_workflow_metas

    config = _config(tmp_path)
    marker_path = str(tmp_path / "marker.txt")
    with open(os.path.join(config.soar.workflows_dir, "load_metas_side_effect_wf.py"), "w") as f:
        f.write(SIDE_EFFECT_WF_CODE.format(marker_path=marker_path))

    metas = load_workflow_metas(config)

    assert not os.path.exists(marker_path), "load_workflow_metas must not import workflow modules"
    meta = next(m for m in metas if m.name == "load_metas_side_effect_wf")
    assert meta.type == "manual"


def test_load_workflow_metas_token_changes_if_state_cleared(tmp_path):
    from orchestrator.main import load_workflow_metas

    config = _config(tmp_path)
    with open(os.path.join(config.soar.workflows_dir, "load_metas_token_wf.py"), "w") as f:
        f.write(WEBHOOK_WF_CODE)

    metas1 = load_workflow_metas(config)
    token1 = next(m.token for m in metas1 if m.name == "load_metas_token_wf")

    state_path = os.path.join(os.path.dirname(config.soar.workflows_dir), "orchestrator_state.yaml")
    os.remove(state_path)

    metas2 = load_workflow_metas(config)
    token2 = next(m.token for m in metas2 if m.name == "load_metas_token_wf")

    assert token1 != token2
