import pytest

from orchestrator.core.introspect import (
    parse_classes,
    parse_connector_usage,
    parse_functions,
    parse_tool_registry,
    parse_workflow_meta,
)

CLASS_MODULE = '''"""Module docstring, not under test."""


class Widget:
    """A small reusable widget.

    Extra detail line, not part of the summary.
    """

    def __init__(self, path, ttl=60):
        self.path = path
        self.ttl = ttl

    def get(self, key):
        """Fetch a value."""
        return None

    def _private(self):
        pass


class _Hidden:
    """Should not be listed — underscore-prefixed."""
'''

FUNCTION_MODULE = '''def enrich(indicator, context):
    """Enrich an indicator."""
    return indicator


def _private_helper():
    pass
'''

EMPTY_MODULE = ""


def test_parse_classes_extracts_methods_and_docstrings(tmp_path):
    path = tmp_path / "widget.py"
    path.write_text(CLASS_MODULE, encoding="utf-8")
    classes = parse_classes(path)
    names = {c["name"] for c in classes}
    assert names == {"Widget"}
    widget = classes[0]
    assert widget["docstring"].startswith("A small reusable widget.")
    assert widget["constructor"] == "(path, ttl)"
    methods = {m["name"]: m for m in widget["methods"]}
    assert methods["get"]["signature"] == "(key)"
    assert methods["get"]["docstring"] == "Fetch a value."
    assert "_private" not in methods


def test_parse_functions_extracts_signature_and_docstring(tmp_path):
    path = tmp_path / "enrich.py"
    path.write_text(FUNCTION_MODULE, encoding="utf-8")
    functions = parse_functions(path)
    names = {f["name"] for f in functions}
    assert names == {"enrich"}
    fn = functions[0]
    assert fn["signature"] == "(indicator, context)"
    assert fn["docstring"] == "Enrich an indicator."


def test_parse_classes_empty_file(tmp_path):
    path = tmp_path / "empty.py"
    path.write_text(EMPTY_MODULE, encoding="utf-8")
    assert parse_classes(path) == []


def test_parse_functions_empty_file(tmp_path):
    path = tmp_path / "empty.py"
    path.write_text(EMPTY_MODULE, encoding="utf-8")
    assert parse_functions(path) == []


FIELDS_MODULE = '''from typing import ClassVar

from soar.connectors.base import BaseConnector


class SampleConnector(BaseConnector):
    HIDDEN_FIELDS: ClassVar[set[str]] = {"password", "api_key"}

    def __init__(
        self,
        instance_name: str,
        host: str = "localhost",
        port: int = 9200,
        api_key: str = "",
        password: str = "",
        verify_certs: bool = True,
    ):
        super().__init__(instance_name)
'''

NO_HIDDEN_FIELDS_MODULE = '''from soar.connectors.base import BaseConnector


class PlainConnector(BaseConnector):
    def __init__(self, instance_name: str, base_path: str = "/tmp"):
        super().__init__(instance_name)
'''


def test_parse_classes_extracts_typed_fields_and_defaults(tmp_path):
    path = tmp_path / "sample.py"
    path.write_text(FIELDS_MODULE, encoding="utf-8")
    cls = parse_classes(path)[0]
    fields = {f["name"]: f for f in cls["fields"]}
    assert fields["instance_name"] == {"name": "instance_name", "type": "str", "default": None}
    assert fields["host"] == {"name": "host", "type": "str", "default": "localhost"}
    assert fields["port"] == {"name": "port", "type": "int", "default": 9200}
    assert fields["verify_certs"] == {"name": "verify_certs", "type": "bool", "default": True}


def test_parse_classes_extracts_hidden_fields(tmp_path):
    path = tmp_path / "sample.py"
    path.write_text(FIELDS_MODULE, encoding="utf-8")
    cls = parse_classes(path)[0]
    assert cls["hidden_fields"] == {"password", "api_key"}


def test_parse_classes_hidden_fields_empty_when_absent(tmp_path):
    path = tmp_path / "plain.py"
    path.write_text(NO_HIDDEN_FIELDS_MODULE, encoding="utf-8")
    cls = parse_classes(path)[0]
    assert cls["hidden_fields"] == set()
    assert cls["fields"] == [
        {"name": "instance_name", "type": "str", "default": None},
        {"name": "base_path", "type": "str", "default": "/tmp"},
    ]


SCHEDULED_WF_MODULE = '''from soar.workflows.base import ScheduledWorkflow


class SyncIndicators(ScheduledWorkflow):
    """Pulls indicators on a timer."""

    schedule = "*/10 * * * *"
    interval = 600

    def run(self, context):
        return {"status": "ok"}
'''

WEBHOOK_WF_MODULE = '''from soar.workflows.base import WebhookWorkflow


class ReceiveAlert(WebhookWorkflow):
    """Receives alerts pushed from an external system."""

    path = "/webhook/alert"
    token = "static-secret-token"

    def run(self, context):
        return {"status": "ok"}
'''

MANUAL_WF_MODULE = '''from soar.workflows.base import ManualWorkflow


class RunOnDemand(ManualWorkflow):
    """Triggered manually by an analyst."""

    def run(self, context):
        return {"status": "ok"}
'''

NO_WORKFLOW_MODULE = '''class NotAWorkflow:
    """Some unrelated class."""

    def run(self, context):
        return None
'''

SYNTAX_ERROR_MODULE = '''class Broken(ScheduledWorkflow
    def run(self, context):
        return None
'''

NO_DOCSTRING_WF_MODULE = '''from soar.workflows.base import ManualWorkflow


class Undocumented(ManualWorkflow):
    def run(self, context):
        return {"status": "ok"}
'''


def test_parse_workflow_meta_scheduled(tmp_path):
    path = tmp_path / "sync_indicators.py"
    path.write_text(SCHEDULED_WF_MODULE, encoding="utf-8")
    meta = parse_workflow_meta(path)
    assert meta["type"] == "scheduled"
    assert meta["schedule"] == "*/10 * * * *"
    assert meta["interval"] == 600
    assert meta["docstring"] == "Pulls indicators on a timer."


def test_parse_workflow_meta_webhook(tmp_path):
    path = tmp_path / "receive_alert.py"
    path.write_text(WEBHOOK_WF_MODULE, encoding="utf-8")
    meta = parse_workflow_meta(path)
    assert meta["type"] == "webhook"
    assert meta["path"] == "/webhook/alert"
    assert meta["token"] == "static-secret-token"
    assert meta["docstring"] == "Receives alerts pushed from an external system."


def test_parse_workflow_meta_manual(tmp_path):
    path = tmp_path / "run_on_demand.py"
    path.write_text(MANUAL_WF_MODULE, encoding="utf-8")
    meta = parse_workflow_meta(path)
    assert meta["type"] == "manual"
    assert meta["docstring"] == "Triggered manually by an analyst."
    assert "schedule" not in meta
    assert "path" not in meta
    assert "token" not in meta


def test_parse_workflow_meta_no_docstring(tmp_path):
    path = tmp_path / "undocumented.py"
    path.write_text(NO_DOCSTRING_WF_MODULE, encoding="utf-8")
    meta = parse_workflow_meta(path)
    assert meta["docstring"] == ""


def test_parse_workflow_meta_no_base_class_returns_none(tmp_path):
    path = tmp_path / "not_a_workflow.py"
    path.write_text(NO_WORKFLOW_MODULE, encoding="utf-8")
    assert parse_workflow_meta(path) is None


def test_parse_workflow_meta_syntax_error_propagates(tmp_path):
    path = tmp_path / "broken.py"
    path.write_text(SYNTAX_ERROR_MODULE, encoding="utf-8")
    with pytest.raises(SyntaxError):
        parse_workflow_meta(path)


SINGLE_CONNECTOR_IMPORT = '''from soar.connectors.virus_total import vt_main
from soar.workflows.base import ManualWorkflow


class EnrichIndicator(ManualWorkflow):
    def run(self, context):
        return vt_main.lookup(context["ioc"])
'''

TWO_TYPE_IMPORTS = '''from soar.connectors.virus_total import vt_main
from soar.connectors.shodan import shodan_prod
from soar.workflows.base import ManualWorkflow


class EnrichIndicator(ManualWorkflow):
    def run(self, context):
        return {}
'''

ALIASED_IMPORT = '''from soar.connectors.ssh import prod as ssh_prod
from soar.workflows.base import ManualWorkflow


class RunCommand(ManualWorkflow):
    def run(self, context):
        return ssh_prod.exec(context["cmd"])
'''

NO_CONNECTOR_IMPORTS = '''from soar.workflows.base import ManualWorkflow


class NoConnectors(ManualWorkflow):
    def run(self, context):
        return {"status": "ok"}
'''

NON_CONNECTOR_IMPORT = '''from soar.tools import http_client
from soar.workflows.base import ManualWorkflow


class UsesTools(ManualWorkflow):
    def run(self, context):
        return http_client.get("https://example.com")
'''


def test_parse_connector_usage_single_import(tmp_path):
    path = tmp_path / "enrich_indicator.py"
    path.write_text(SINGLE_CONNECTOR_IMPORT, encoding="utf-8")
    assert parse_connector_usage(path) == [("virus_total", "vt_main")]


def test_parse_connector_usage_two_types(tmp_path):
    path = tmp_path / "enrich_indicator.py"
    path.write_text(TWO_TYPE_IMPORTS, encoding="utf-8")
    result = parse_connector_usage(path)
    assert set(result) == {("virus_total", "vt_main"), ("shodan", "shodan_prod")}


def test_parse_connector_usage_aliased_import_resolves_real_instance_name(tmp_path):
    """`import prod as ssh_prod` must scope on "prod" (the registry
    instance actually fetched via PEP 562 module __getattr__), not on the
    local alias "ssh_prod" — see parse_connector_usage docstring."""
    path = tmp_path / "run_command.py"
    path.write_text(ALIASED_IMPORT, encoding="utf-8")
    assert parse_connector_usage(path) == [("ssh", "prod")]


def test_parse_connector_usage_no_imports_returns_empty(tmp_path):
    path = tmp_path / "no_connectors.py"
    path.write_text(NO_CONNECTOR_IMPORTS, encoding="utf-8")
    assert parse_connector_usage(path) == []


def test_parse_connector_usage_ignores_non_connector_imports(tmp_path):
    path = tmp_path / "uses_tools.py"
    path.write_text(NON_CONNECTOR_IMPORT, encoding="utf-8")
    assert parse_connector_usage(path) == []


WORKFLOW_IMPORTS_ACTION = '''from soar.actions.check_x import check_x
from soar.workflows.base import ManualWorkflow


class EnrichIndicator(ManualWorkflow):
    def run(self, context):
        return {"result": check_x(context["ioc"])}
'''

ACTION_IMPORTS_CONNECTOR = '''from soar.connectors.virus_total import vt_main


def check_x(ioc):
    return vt_main.lookup(ioc)
'''

WORKFLOW_IMPORTS_CONNECTOR_AND_ACTION = '''from soar.connectors.shodan import shodan_prod
from soar.actions.check_x import check_x
from soar.workflows.base import ManualWorkflow


class EnrichIndicator(ManualWorkflow):
    def run(self, context):
        return {"a": shodan_prod.lookup(context["ip"]), "b": check_x(context["ioc"])}
'''

WORKFLOW_IMPORTS_MISSING_ACTION = '''from soar.actions.does_not_exist import whatever
from soar.workflows.base import ManualWorkflow


class EnrichIndicator(ManualWorkflow):
    def run(self, context):
        return {"result": whatever(context["ioc"])}
'''

ACTION_SYNTAX_ERROR = '''from soar.connectors.virus_total import vt_main

def broken(:
    return vt_main
'''

WORKFLOW_IMPORTS_CONNECTOR_AND_BROKEN_ACTION = '''from soar.connectors.shodan import shodan_prod
from soar.actions.broken_action import whatever
from soar.workflows.base import ManualWorkflow


class EnrichIndicator(ManualWorkflow):
    def run(self, context):
        return {"a": shodan_prod.lookup(context["ip"])}
'''

ACTION_CYCLE_A = '''from soar.actions.cycle_b import helper_b
from soar.connectors.virus_total import vt_main


def helper_a():
    return helper_b()
'''

ACTION_CYCLE_B = '''from soar.actions.cycle_a import helper_a
from soar.connectors.shodan import shodan_prod


def helper_b():
    return helper_a()
'''

WORKFLOW_IMPORTS_CYCLE_A = '''from soar.actions.cycle_a import helper_a
from soar.workflows.base import ManualWorkflow


class EnrichIndicator(ManualWorkflow):
    def run(self, context):
        return {"result": helper_a()}
'''


def test_parse_connector_usage_follows_action_import_transitively(tmp_path):
    workflow_path = tmp_path / "enrich_indicator.py"
    workflow_path.write_text(WORKFLOW_IMPORTS_ACTION, encoding="utf-8")
    actions_dir = tmp_path / "actions"
    actions_dir.mkdir()
    (actions_dir / "check_x.py").write_text(ACTION_IMPORTS_CONNECTOR, encoding="utf-8")

    assert parse_connector_usage(workflow_path, actions_dir=actions_dir) == [
        ("virus_total", "vt_main"),
    ]


def test_parse_connector_usage_without_actions_dir_ignores_action_imports(tmp_path):
    workflow_path = tmp_path / "enrich_indicator.py"
    workflow_path.write_text(WORKFLOW_IMPORTS_ACTION, encoding="utf-8")
    actions_dir = tmp_path / "actions"
    actions_dir.mkdir()
    (actions_dir / "check_x.py").write_text(ACTION_IMPORTS_CONNECTOR, encoding="utf-8")

    assert parse_connector_usage(workflow_path) == []


def test_parse_connector_usage_combines_direct_and_transitive_imports(tmp_path):
    workflow_path = tmp_path / "enrich_indicator.py"
    workflow_path.write_text(WORKFLOW_IMPORTS_CONNECTOR_AND_ACTION, encoding="utf-8")
    actions_dir = tmp_path / "actions"
    actions_dir.mkdir()
    (actions_dir / "check_x.py").write_text(ACTION_IMPORTS_CONNECTOR, encoding="utf-8")

    result = parse_connector_usage(workflow_path, actions_dir=actions_dir)
    assert set(result) == {("shodan", "shodan_prod"), ("virus_total", "vt_main")}


def test_parse_connector_usage_missing_action_file_is_skipped(tmp_path):
    workflow_path = tmp_path / "enrich_indicator.py"
    workflow_path.write_text(WORKFLOW_IMPORTS_MISSING_ACTION, encoding="utf-8")
    actions_dir = tmp_path / "actions"
    actions_dir.mkdir()

    assert parse_connector_usage(workflow_path, actions_dir=actions_dir) == []


def test_parse_connector_usage_broken_action_file_does_not_abort_scan(tmp_path):
    workflow_path = tmp_path / "enrich_indicator.py"
    workflow_path.write_text(WORKFLOW_IMPORTS_CONNECTOR_AND_BROKEN_ACTION, encoding="utf-8")
    actions_dir = tmp_path / "actions"
    actions_dir.mkdir()
    (actions_dir / "broken_action.py").write_text(ACTION_SYNTAX_ERROR, encoding="utf-8")

    assert parse_connector_usage(workflow_path, actions_dir=actions_dir) == [
        ("shodan", "shodan_prod"),
    ]


def test_parse_connector_usage_action_import_cycle_does_not_recurse_infinitely(tmp_path):
    workflow_path = tmp_path / "enrich_indicator.py"
    workflow_path.write_text(WORKFLOW_IMPORTS_CYCLE_A, encoding="utf-8")
    actions_dir = tmp_path / "actions"
    actions_dir.mkdir()
    (actions_dir / "cycle_a.py").write_text(ACTION_CYCLE_A, encoding="utf-8")
    (actions_dir / "cycle_b.py").write_text(ACTION_CYCLE_B, encoding="utf-8")

    result = parse_connector_usage(workflow_path, actions_dir=actions_dir)
    assert set(result) == {("virus_total", "vt_main"), ("shodan", "shodan_prod")}


# --- parse_tool_registry ---


def test_parse_tool_registry_reads_literal_dict(tmp_path):
    init_path = tmp_path / "__init__.py"
    init_path.write_text(
        'TOOL_REGISTRY = {\n'
        '    "http_client": {"kind": "instance", "of": "LoggingHttpClient", "module": "http_client"},\n'
        '    "LoggingHttpClient": {"kind": "class", "module": "http_client"},\n'
        '    "watermark_store": {"kind": "factory", "module": "watermark"},\n'
        '}\n'
        '__all__ = list(TOOL_REGISTRY)\n',
        encoding="utf-8",
    )
    registry = parse_tool_registry(init_path)
    assert registry == {
        "http_client": {"kind": "instance", "of": "LoggingHttpClient", "module": "http_client"},
        "LoggingHttpClient": {"kind": "class", "module": "http_client"},
        "watermark_store": {"kind": "factory", "module": "watermark"},
    }


def test_parse_tool_registry_missing_declaration_returns_empty_dict(tmp_path):
    init_path = tmp_path / "__init__.py"
    init_path.write_text('__all__ = ["Foo"]\n', encoding="utf-8")
    assert parse_tool_registry(init_path) == {}
