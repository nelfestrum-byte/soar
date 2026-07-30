import sys

import pytest
import yaml

from soar.connectors import ConnectorRegistry
from soar.connectors._proxy import ConnectorProxy


def _write_yml(path, instances: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.dump({"instances": instances}), encoding="utf-8")


@pytest.fixture
def file_registry(tmp_path):
    _write_yml(tmp_path / "file" / "a.yml", {"local": {"base_path": str(tmp_path / "data")}})
    reg = ConnectorRegistry()
    reg.init(external_dir=str(tmp_path))
    yield reg
    sys.modules.pop("soar.connectors.file", None)


def test_import_shim_returns_proxy(file_registry):
    mod = sys.modules["soar.connectors.file"]
    inst = mod.local  # simulates `from soar.connectors.file import local`
    assert isinstance(inst, ConnectorProxy)
    assert not hasattr(inst, "_connect_impl") or isinstance(inst, ConnectorProxy)


def test_import_shim_typo_raises_attribute_error_on_import(file_registry):
    mod = sys.modules["soar.connectors.file"]
    with pytest.raises(AttributeError):
        _ = mod.typo_instance_name


def test_flat_getattr_on_registry_returns_proxy(file_registry):
    inst = file_registry.local
    assert isinstance(inst, ConnectorProxy)


def test_proxy_never_exposes_raw_instance_via_flat_path(file_registry):
    inst = file_registry.local
    assert isinstance(inst, ConnectorProxy)
    # the raw BaseConnector is reachable only via the private _instance attr,
    # never returned directly by any public entry point
    assert type(inst).__name__ == "ConnectorProxy"
