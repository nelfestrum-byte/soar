import importlib
import importlib.util
import sys
import types
from pathlib import Path

from soar.connectors._proxy import ConnectorProxy
from soar.connectors.base import BaseConnector
from soar.logger import get_logger

_log = get_logger("connector.registry")


class ConnectorRegistry:
    def __init__(self):
        self._connectors: dict[str, dict[str, BaseConnector]] = {}
        self._classes: dict[str, type[BaseConnector]] = {}
        self._configs: dict[str, dict[str, dict]] = {}  # type -> instance -> params

    def _discover_classes(self) -> None:
        package_dir = Path(__file__).parent
        for connector_dir in package_dir.iterdir():
            if not connector_dir.is_dir() or connector_dir.name.startswith("_"):
                continue
            py_files = list(connector_dir.glob("*.py"))
            for py_file in py_files:
                if py_file.name.startswith("_"):
                    continue
                module_name = py_file.stem
                fqn = f"soar.connectors.{connector_dir.name}.{module_name}"
                try:
                    mod = importlib.import_module(fqn)
                except ImportError as e:
                    _log.warning(f"Failed to import {fqn}: {e}")
                    continue
                for attr_name in dir(mod):
                    obj = getattr(mod, attr_name)
                    if (
                        isinstance(obj, type)
                        and issubclass(obj, BaseConnector)
                        and obj is not BaseConnector
                        and obj.__module__ == fqn
                    ):
                        self._classes[connector_dir.name] = obj

    def _load_configs_from_dir(self, base_dir: Path) -> None:
        for connector_dir in base_dir.iterdir():
            if not connector_dir.is_dir() or connector_dir.name.startswith("_"):
                continue
            type_name = connector_dir.name
            for yml_file in sorted(connector_dir.glob("*.yml")):
                if yml_file.name.endswith(".example.yml"):
                    continue
                try:
                    import yaml

                    with open(yml_file) as f:
                        config = yaml.safe_load(f)
                    if config and "instances" in config:
                        bucket = self._configs.setdefault(type_name, {})
                        for instance_name, params in config["instances"].items():
                            if instance_name in bucket:
                                _log.warning(
                                    f"Duplicate instance '{instance_name}' for "
                                    f"connector type '{type_name}' in {yml_file} — "
                                    "overwriting previous definition"
                                )
                            bucket[instance_name] = params
                except Exception as e:
                    _log.warning(f"Failed to load config {yml_file}: {e}")

    def _load_configs(self, external_dir: str | None = None) -> None:
        self._load_configs_from_dir(Path(__file__).parent)
        if external_dir:
            ext_path = Path(external_dir)
            if ext_path.exists():
                self._load_configs_from_dir(ext_path)

    def _discover_external(self, external_dir: str) -> None:
        ext_path = Path(external_dir)
        if not ext_path.exists():
            return
        for connector_dir in ext_path.iterdir():
            if not connector_dir.is_dir() or connector_dir.name.startswith("_"):
                continue
            py_files = list(connector_dir.glob("*.py"))
            for py_file in py_files:
                if py_file.name.startswith("_"):
                    continue
                module_name = py_file.stem
                fqn = f"soar.connectors.{connector_dir.name}.{module_name}"
                if fqn in sys.modules:
                    continue
                try:
                    spec = importlib.util.spec_from_file_location(fqn, py_file)
                    if spec is None or spec.loader is None:
                        continue
                    mod = importlib.util.module_from_spec(spec)
                    sys.modules[fqn] = mod
                    spec.loader.exec_module(mod)
                except Exception as e:
                    _log.warning(f"Failed to import external connector {fqn}: {e}")
                    continue
                for attr_name in dir(mod):
                    obj = getattr(mod, attr_name)
                    if (
                        isinstance(obj, type)
                        and issubclass(obj, BaseConnector)
                        and obj is not BaseConnector
                        and obj.__module__ == fqn
                    ):
                        self._classes[connector_dir.name] = obj

    def init(self, external_dir: str | None = None) -> None:
        self._discover_classes()
        if external_dir:
            self._discover_external(external_dir)
        self._load_configs(external_dir)
        for type_name, instances in self._configs.items():
            cls = self._classes.get(type_name)
            if cls is None:
                _log.warning(f"No connector class for type '{type_name}'")
                continue
            bucket = self._connectors.setdefault(type_name, {})
            for instance_name, params in instances.items():
                params = params or {}
                bucket[instance_name] = cls(instance_name=instance_name, **params)
        total = sum(len(v) for v in self._connectors.values())
        _log.info(f"Registered {total} connectors")
        _install_shims(self)

    def get_instance(self, type_name: str, instance_name: str) -> BaseConnector | None:
        return self._connectors.get(type_name, {}).get(instance_name)

    def __getattr__(self, name: str) -> "ConnectorProxy":
        if name.startswith("_"):
            raise AttributeError(name)
        for type_name, instances in self._connectors.items():
            if name in instances:
                return ConnectorProxy(instances[name], type_name)
        raise AttributeError(f"Connector '{name}' not found")

    def list(self) -> list[dict]:
        return [
            {"name": name, "type": type_name, "connected": c.is_connected}
            for type_name, instances in self._connectors.items()
            for name, c in instances.items()
        ]

    def shutdown(self) -> None:
        for instances in self._connectors.values():
            for name, connector in instances.items():
                try:
                    connector.disconnect()
                except Exception as e:
                    _log.warning(f"Error disconnecting {name}: {e}")


def _install_shims(registry: "ConnectorRegistry") -> None:
    """Install a module-level __getattr__ for soar.connectors.<type>, so
    `from soar.connectors.<type> import <instance>` resolves lazily to a
    ConnectorProxy. See soar/connectors/_proxy.py docstring (decision 4,
    docs/concepts/ENTITY-MODEL.md) for why this must always hand out a
    proxy, never the raw instance."""
    for type_name in registry._connectors:
        fqn = f"soar.connectors.{type_name}"

        def _getattr(instance_name: str, _type_name: str = type_name) -> ConnectorProxy:
            inst = registry.get_instance(_type_name, instance_name)
            if inst is None:
                raise AttributeError(
                    f"Connector instance '{instance_name}' of type "
                    f"'{_type_name}' not found"
                )
            return ConnectorProxy(inst, _type_name)

        mod = sys.modules.get(fqn) or types.ModuleType(fqn)
        mod.__getattr__ = _getattr
        sys.modules[fqn] = mod


connectors = ConnectorRegistry()
