from orchestrator.core.introspect import parse_classes, parse_functions

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
