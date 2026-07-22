from orchestrator.config import OrchestratorConfig
from orchestrator.core import workflow_state
from orchestrator.models import ConcurrencyPolicy
from orchestrator.models.workflow_meta import WorkflowMeta


def _config(tmp_path) -> OrchestratorConfig:
    config = OrchestratorConfig()
    config.soar.workflows_dir = str(tmp_path / "workflows")
    return config


def test_parse_enabled_legacy_string():
    assert workflow_state.parse_enabled("enabled") is True
    assert workflow_state.parse_enabled("disabled") is False


def test_parse_enabled_bool():
    assert workflow_state.parse_enabled(True) is True
    assert workflow_state.parse_enabled(False) is False


def test_parse_enabled_dict():
    assert workflow_state.parse_enabled({"enabled": True, "token": "x"}) is True
    assert workflow_state.parse_enabled({"enabled": False}) is False
    assert workflow_state.parse_enabled({}) is True


def test_parse_token():
    assert workflow_state.parse_token({"enabled": True, "token": "secret"}) == "secret"
    assert workflow_state.parse_token({"enabled": True}) is None
    assert workflow_state.parse_token("enabled") is None
    assert workflow_state.parse_token(True) is None


def test_load_state_missing_file(tmp_path):
    config = _config(tmp_path)
    assert workflow_state.load_state(config) == {}


def test_save_and_load_state_roundtrip(tmp_path):
    config = _config(tmp_path)
    metas = [
        WorkflowMeta(name="wf1", type="scheduled", enabled=True, concurrency=ConcurrencyPolicy.FORBID),
        WorkflowMeta(
            name="wf2", type="webhook", enabled=False, token="tok123",
            concurrency=ConcurrencyPolicy.ALLOW,
        ),
    ]
    workflow_state.save_state(config, metas)

    state = workflow_state.load_state(config)
    assert workflow_state.parse_enabled(state["wf1"]) is True
    assert workflow_state.parse_token(state["wf1"]) is None
    assert workflow_state.parse_enabled(state["wf2"]) is False
    assert workflow_state.parse_token(state["wf2"]) == "tok123"


def test_remove_from_state(tmp_path):
    config = _config(tmp_path)
    metas = [WorkflowMeta(name="wf1", type="scheduled", enabled=True, concurrency=ConcurrencyPolicy.FORBID)]
    workflow_state.save_state(config, metas)

    workflow_state.remove_from_state(config, "wf1")

    state = workflow_state.load_state(config)
    assert "wf1" not in state


def test_remove_from_state_missing_file_noop(tmp_path):
    config = _config(tmp_path)
    workflow_state.remove_from_state(config, "nonexistent")  # must not raise
