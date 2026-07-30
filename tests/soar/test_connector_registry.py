"""Synthetic connector types only, written straight into an external dir —
not soar/connectors/file or soar/connectors/urlhaus: Phase 3 of the
entity-model plan moved every built-in connector out of soar/connectors/
into the sibling pack repo, so these platform-level ConnectorRegistry
tests can no longer lean on a real one being physically present."""

import uuid
from unittest.mock import patch

import yaml

from soar.connectors import ConnectorRegistry

_CONNECTOR_SRC = (
    "from soar.connectors.base import BaseConnector\n\n\n"
    "class {class_name}(BaseConnector):\n"
    "    def __init__(self, instance_name: str, base_path: str = \"\"):\n"
    "        super().__init__(instance_name)\n"
    "        self.base_path = base_path\n\n"
    "    def _connect_impl(self):\n        self._connected = True\n\n"
    "    def disconnect(self):\n        self._connected = False\n"
)


def _write_yml(path, instances: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.dump({"instances": instances}), encoding="utf-8")


def _write_connector(base_dir, type_name: str, class_name: str) -> None:
    conn_dir = base_dir / type_name
    conn_dir.mkdir(parents=True, exist_ok=True)
    (conn_dir / f"{type_name}.py").write_text(
        _CONNECTOR_SRC.format(class_name=class_name), encoding="utf-8",
    )


def _unique_type(prefix: str) -> str:
    # ConnectorRegistry._discover_external keys its "already imported" skip
    # off sys.modules, a process-global — reusing a type name across tests
    # in the same pytest run would make the second registry silently see
    # an empty _classes for that type. See test_connectors_init.py's
    # file_registry fixture docstring for the same issue.
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def test_two_instances_same_name_different_types_coexist(tmp_path):
    type_a, type_b = _unique_type("alpha"), _unique_type("beta")
    _write_connector(tmp_path, type_a, "AlphaConnector")
    _write_connector(tmp_path, type_b, "BetaConnector")
    _write_yml(tmp_path / type_a / "a.yml", {"prod": {"base_path": "/tmp/a"}})
    _write_yml(tmp_path / type_b / "b.yml", {"prod": {}})

    reg = ConnectorRegistry()
    reg.init(external_dir=str(tmp_path))

    a_prod = reg.get_instance(type_a, "prod")
    b_prod = reg.get_instance(type_b, "prod")
    assert a_prod is not None
    assert b_prod is not None
    assert a_prod is not b_prod
    assert type(a_prod).__name__ == "AlphaConnector"
    assert type(b_prod).__name__ == "BetaConnector"


def test_collision_within_same_type_last_wins_with_warning(tmp_path):
    type_name = _unique_type("gamma")
    _write_connector(tmp_path, type_name, "GammaConnector")
    _write_yml(tmp_path / type_name / "a.yml", {"dup": {"base_path": "/tmp/a"}})
    _write_yml(tmp_path / type_name / "b.yml", {"dup": {"base_path": "/tmp/b"}})

    reg = ConnectorRegistry()
    with patch("soar.connectors._log") as mock_log:
        reg.init(external_dir=str(tmp_path))

    inst = reg.get_instance(type_name, "dup")
    assert inst is not None
    # last-wins: b.yml sorts after a.yml
    assert str(inst.base_path).replace("\\", "/").endswith("/tmp/b")
    warnings = [str(c.args[0]) for c in mock_log.warning.call_args_list]
    assert any("Duplicate instance" in w for w in warnings)


def test_discover_external_ignores_class_imported_from_other_module(tmp_path):
    type_a = _unique_type("type_a")
    type_b = _unique_type("type_b")
    type_a_dir = tmp_path / type_a
    type_a_dir.mkdir(parents=True)
    (type_a_dir / "a.py").write_text(
        "from soar.connectors.base import BaseConnector\n"
        "\n"
        "class AaConnector(BaseConnector):\n"
        "    def _connect_impl(self):\n"
        "        pass\n",
        encoding="utf-8",
    )
    type_b_dir = tmp_path / type_b
    type_b_dir.mkdir(parents=True)
    (type_b_dir / "b.py").write_text(
        f"from soar.connectors.{type_a}.a import AaConnector\n"
        "from soar.connectors.base import BaseConnector\n"
        "\n"
        "class AaConnector(BaseConnector):\n"
        "    def _connect_impl(self):\n"
        "        pass\n",
        encoding="utf-8",
    )
    _write_yml(tmp_path / type_b / "b.yml", {"only": {}})

    reg = ConnectorRegistry()
    reg.init(external_dir=str(tmp_path))

    cls = reg._classes.get(type_b)
    assert cls is not None
    # Alphabetically, "AaConnector" imported from type_a comes first in
    # dir(mod) too — a last-wins scan of dir(mod) without the
    # __module__ == fqn check would pick the imported class instead of the
    # module's own (both happen to share the name "AaConnector" here).
    assert cls.__name__ == "AaConnector"
    assert cls.__module__ == f"soar.connectors.{type_b}.b"


def test_list_form_unchanged_after_namespace_refactor(tmp_path):
    type_name = _unique_type("delta")
    _write_connector(tmp_path, type_name, "DeltaConnector")
    _write_yml(tmp_path / type_name / "a.yml", {"myinst": {"base_path": "/tmp/a"}})

    reg = ConnectorRegistry()
    reg.init(external_dir=str(tmp_path))

    items = reg.list()
    assert isinstance(items, list)
    entry = next(i for i in items if i["name"] == "myinst")
    assert set(entry.keys()) == {"name", "type", "connected"}
    assert entry["type"] == type_name
    assert entry["connected"] is False


def test_get_instance_missing_returns_none(tmp_path):
    reg = ConnectorRegistry()
    reg.init(external_dir=str(tmp_path))
    assert reg.get_instance("file", "does_not_exist") is None
    assert reg.get_instance("nonexistent_type", "x") is None
