import pytest

from orchestrator.core.introspect import parse_classes, parse_functions, parse_workflow_meta

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
