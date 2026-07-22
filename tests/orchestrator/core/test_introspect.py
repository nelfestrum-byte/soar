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
