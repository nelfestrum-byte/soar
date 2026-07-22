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
