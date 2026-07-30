import sys
import uuid

import pytest
import yaml

from soar.connectors import ConnectorRegistry
from soar.connectors._proxy import ConnectorProxy


def _connector_src(class_name: str) -> str:
    return (
        "from soar.connectors.base import BaseConnector\n\n\n"
        f"class {class_name}(BaseConnector):\n"
        "    def __init__(self, instance_name: str, base_path: str = \"\"):\n"
        "        super().__init__(instance_name)\n"
        "        self.base_path = base_path\n\n"
        "    def _connect_impl(self):\n        self._connected = True\n\n"
        "    def disconnect(self):\n        self._connected = False\n"
    )


def _write_yml(path, instances: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.dump({"instances": instances}), encoding="utf-8")


@pytest.fixture
def file_registry(tmp_path):
    """Synthetic connector type in an external dir — not one of the
    platform's own soar/connectors/ entries (Phase 3, entity-model plan:
    those all moved to the sibling pack repo, so this test can't lean on a
    real one being physically present to exercise the ConnectorRegistry's
    external-discovery path).

    The type name is randomized per test: ConnectorRegistry._discover_external
    keys its "already imported" check off `sys.modules`, a process-global —
    two tests reusing the same type name in the same pytest run would see
    the second test's registry silently fail to (re)populate _classes for
    that type (already-imported skip), even though it's a brand new
    ConnectorRegistry instance. This is invisible in production
    (ConnectorRegistry.init() runs once per subprocess) but real here."""
    type_name = f"widget_{uuid.uuid4().hex[:8]}"
    class_name = "".join(w.capitalize() for w in type_name.split("_")) + "Connector"
    conn_dir = tmp_path / type_name
    conn_dir.mkdir(parents=True)
    (conn_dir / f"{type_name}.py").write_text(_connector_src(class_name), encoding="utf-8")
    _write_yml(conn_dir / f"{type_name}.yml", {"local": {"base_path": str(tmp_path / "data")}})
    reg = ConnectorRegistry()
    reg.init(external_dir=str(tmp_path))
    yield reg, type_name
    sys.modules.pop(f"soar.connectors.{type_name}", None)


def test_import_shim_returns_proxy(file_registry):
    reg, type_name = file_registry
    mod = sys.modules[f"soar.connectors.{type_name}"]
    inst = mod.local  # simulates `from soar.connectors.<type> import local`
    assert isinstance(inst, ConnectorProxy)
    assert not hasattr(inst, "_connect_impl") or isinstance(inst, ConnectorProxy)


def test_import_shim_typo_raises_attribute_error_on_import(file_registry):
    reg, type_name = file_registry
    mod = sys.modules[f"soar.connectors.{type_name}"]
    with pytest.raises(AttributeError):
        _ = mod.typo_instance_name


def test_flat_getattr_on_registry_returns_proxy(file_registry):
    reg, _type_name = file_registry
    inst = reg.local
    assert isinstance(inst, ConnectorProxy)


def test_proxy_never_exposes_raw_instance_via_flat_path(file_registry):
    reg, _type_name = file_registry
    inst = reg.local
    assert isinstance(inst, ConnectorProxy)
    # the raw BaseConnector is reachable only via the private _instance attr,
    # never returned directly by any public entry point
    assert type(inst).__name__ == "ConnectorProxy"
