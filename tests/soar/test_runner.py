import inspect
import json
from unittest.mock import patch

import pytest

import soar.tools as tools
from soar import runner
from soar.tools._cache import InMemoryCache, RedisCache
from soar.tools.http_client import CachingHttpClient, LoggingHttpClient
from soar.workflows import WorkflowRegistry


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


def test_build_http_client_defaults_to_memory_cache():
    client = runner._build_http_client({})
    assert isinstance(client, CachingHttpClient)
    assert isinstance(client._cache, InMemoryCache)
    assert client._default_ttl == 3600


def test_build_http_client_none_backend_has_no_cache():
    client = runner._build_http_client({"http_client": {"cache_backend": "none"}})
    assert isinstance(client, LoggingHttpClient)
    assert not isinstance(client, CachingHttpClient)


def test_build_http_client_reads_ttl_and_domain_ttl():
    client = runner._build_http_client({
        "http_client": {
            "cache_backend": "memory",
            "default_ttl": 60,
            "domain_ttl": {"api.virustotal.com": 86400},
        }
    })
    assert client._default_ttl == 60
    assert client._domain_ttl == {"api.virustotal.com": 86400}


def test_build_http_client_redis_backend_uses_queue_redis_url():
    with patch("redis.from_url") as mock_from_url:
        client = runner._build_http_client({
            "http_client": {"cache_backend": "redis"},
            "queue": {"redis_url": "redis://localhost:6379/2"},
        })
        assert isinstance(client._cache, RedisCache)
        mock_from_url.assert_called_once_with("redis://localhost:6379/2")


def test_build_http_client_redis_backend_without_redis_url_raises():
    with pytest.raises(ValueError, match="redis_url"):
        runner._build_http_client({
            "http_client": {"cache_backend": "redis"},
            "queue": {"redis_url": ""},
        })


def test_build_http_client_unknown_backend_raises():
    with pytest.raises(ValueError, match="Unknown"):
        runner._build_http_client({"http_client": {"cache_backend": "bogus"}})


def test_build_http_client_fills_shared_new_client_state():
    """_build_http_client must populate http_client.py's module-level
    _shared_* globals so new_client() (called from a connector's
    _connect_impl) shares the same cache/ttl config as the tools.http_client
    singleton — see soar/tools/http_client.py::new_client and spec
    2026-08-03-tools-redesign-design.md [S2](d)/(e)."""
    import importlib
    http_client_module = importlib.import_module("soar.tools.http_client")

    client = runner._build_http_client({
        "http_client": {
            "cache_backend": "memory",
            "default_ttl": 60,
            "domain_ttl": {"api.virustotal.com": 86400},
        }
    })

    assert http_client_module._shared_cache is client._cache
    assert http_client_module._shared_default_ttl == 60
    assert http_client_module._shared_domain_ttl == {"api.virustotal.com": 86400}


def _write_capture_fixture(tmp_path, filename: str, class_name: str):
    (tmp_path / filename).write_text(
        "from soar.tools import http_client\n"
        "from soar.workflows.base import ManualWorkflow\n"
        "\n"
        f"class {class_name}(ManualWorkflow):\n"
        "    captured_http_client = http_client\n"
        "\n"
        "    def run(self, context):\n"
        "        return {}\n"
    )


def test_from_import_http_client_sees_configured_instance_when_assigned_before_init(
    tmp_path, monkeypatch
):
    """Mirrors the fixed soar/runner.py order: assign tools.http_client, *then*
    call *.init() (which imports user workflow/action/connector modules)."""
    _write_capture_fixture(tmp_path, "capture_before.py", "CaptureBefore")

    configured = runner._build_http_client({"http_client": {"default_ttl": 999}})
    monkeypatch.setattr(tools, "http_client", configured)

    registry = WorkflowRegistry()
    registry.init(external_dir=str(tmp_path))

    cls = registry.get_class("capture_before")
    assert cls.captured_http_client is configured
    assert cls.captured_http_client._default_ttl == 999


def test_from_import_http_client_captures_stale_default_when_assigned_after_init(
    tmp_path, monkeypatch
):
    """Mirrors the pre-fix (buggy) order: *.init() imports user modules first,
    tools.http_client is only reassigned afterwards — the module-level
    `from soar.tools import http_client` binding in the fixture is stuck on
    whatever tools.http_client was at import time, not the later assignment.
    Pins down that ordering is actually load-bearing for the fix above."""
    _write_capture_fixture(tmp_path, "capture_after.py", "CaptureAfter")

    stale_default = tools.http_client
    registry = WorkflowRegistry()
    registry.init(external_dir=str(tmp_path))

    configured = runner._build_http_client({"http_client": {"default_ttl": 999}})
    monkeypatch.setattr(tools, "http_client", configured)

    cls = registry.get_class("capture_after")
    assert cls.captured_http_client is stale_default
    assert cls.captured_http_client is not configured


def test_runner_assigns_http_client_before_registry_init():
    """Direct check on soar/runner.py's own source: the http_client/
    http_client_sync assignment lines must precede all three *.init() calls,
    per docs/compose/specs/2026-07-28-http-client-init-order-design.md [S2]."""
    source = inspect.getsource(runner)
    assign_pos = source.index("tools.http_client = _build_http_client(config)")
    init_positions = [
        source.index("workflows.init(external_dir="),
        source.index("connectors.init(external_dir="),
        source.index("actions.init(external_dir="),
    ]
    assert all(assign_pos < pos for pos in init_positions)


def test_runner_initializes_connectors_and_actions_before_workflows():
    """connectors.init()/actions.init() must run before workflows.init(),
    per docs/compose/specs/2026-07-31-workflow-connector-scoping-design.md
    [S2] (Д1) — workflows may top-level-import actions/connectors, and
    actions may themselves top-level-import connectors; both resolution
    paths depend on the earlier registry's init() having already run
    (connector shims installed / action modules registered in sys.modules)."""
    source = inspect.getsource(runner)
    connectors_pos = source.index("connectors.init(external_dir=")
    actions_pos = source.index("actions.init(external_dir=")
    workflows_pos = source.index("workflows.init(external_dir=")
    assert connectors_pos < actions_pos < workflows_pos


def _write_qa_connector(connectors_dir, suffix: str):
    conn_dir = connectors_dir / f"qa_httpbin_{suffix}"
    conn_dir.mkdir(parents=True)
    (conn_dir / f"qa_httpbin_{suffix}.py").write_text(
        "from soar.connectors.base import BaseConnector\n"
        "\n\n"
        f"class QaHttpbin{suffix.title()}(BaseConnector):\n"
        "    def __init__(self, instance_name):\n"
        "        super().__init__(instance_name)\n"
        "\n"
        "    def ping(self):\n"
        "        return True\n",
        encoding="utf-8",
    )
    (conn_dir / f"qa_httpbin_{suffix}.yml").write_text(
        "instances:\n"
        "  x: {}\n",
        encoding="utf-8",
    )


def _write_qa_action(actions_dir, suffix: str):
    (actions_dir / f"check_qa_ip_{suffix}.py").write_text(
        f"from soar.connectors.qa_httpbin_{suffix} import x\n"
        "\n\n"
        f"def check_qa_ip_{suffix}():\n"
        "    return x.ping()\n",
        encoding="utf-8",
    )


def _write_qa_workflow(workflows_dir, suffix: str):
    (workflows_dir / f"qa_manual_test_{suffix}.py").write_text(
        f"from soar.actions.check_qa_ip_{suffix} import check_qa_ip_{suffix}\n"
        "from soar.workflows.base import ManualWorkflow\n"
        "\n\n"
        f"class QaManualTest{suffix.title()}(ManualWorkflow):\n"
        "    def run(self, context):\n"
        f"        return {{'ok': check_qa_ip_{suffix}()}}\n",
        encoding="utf-8",
    )


def test_correct_registry_init_order_registers_workflow_with_transitive_action_import(tmp_path):
    """Integration regression for Д1: on fresh (non-singleton) registries,
    connectors -> actions -> workflows init order registers a workflow whose
    action import (and that action's connector import) are both top-level."""
    from soar.actions import ActionsRegistry
    from soar.connectors import ConnectorRegistry

    suffix = "ok"
    connectors_dir = tmp_path / "connectors"
    actions_dir = tmp_path / "actions"
    workflows_dir = tmp_path / "workflows"
    connectors_dir.mkdir()
    actions_dir.mkdir()
    workflows_dir.mkdir()

    _write_qa_connector(connectors_dir, suffix)
    _write_qa_action(actions_dir, suffix)
    _write_qa_workflow(workflows_dir, suffix)

    ConnectorRegistry().init(external_dir=str(connectors_dir))
    ActionsRegistry().init(external_dir=str(actions_dir))
    workflow_registry = WorkflowRegistry()
    workflow_registry.init(external_dir=str(workflows_dir))

    assert workflow_registry.get_class(f"qa_manual_test_{suffix}") is not None


def test_wrong_registry_init_order_fails_to_register_workflow(tmp_path):
    """Companion negative test — reproduces the found bug: workflows.init()
    running before connectors/actions are initialized fails to register a
    workflow that top-level-imports an action (which itself top-level-
    imports a connector). Pins the regression down to the actual ordering,
    not an accidental pass. Uses distinct fixture names from the "correct
    order" test above — sys.modules is process-global and _discover_external
    on both ActionsRegistry/ConnectorRegistry skips re-exec of an fqn already
    present there, so reusing the same module names across tests would let
    this test accidentally pass via cache leakage from the other test."""
    suffix = "bad"
    connectors_dir = tmp_path / "connectors"
    actions_dir = tmp_path / "actions"
    workflows_dir = tmp_path / "workflows"
    connectors_dir.mkdir()
    actions_dir.mkdir()
    workflows_dir.mkdir()

    _write_qa_connector(connectors_dir, suffix)
    _write_qa_action(actions_dir, suffix)
    _write_qa_workflow(workflows_dir, suffix)

    workflow_registry = WorkflowRegistry()
    workflow_registry.init(external_dir=str(workflows_dir))

    assert workflow_registry.get_class(f"qa_manual_test_{suffix}") is None
