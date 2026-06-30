import importlib
import importlib.util
import sys
from pathlib import Path

from soar.connectors.base import BaseConnector
from soar.logger import get_logger

_log = get_logger("connector.registry")


class ConnectorRegistry:
    def __init__(self):
        self._connectors: dict[str, BaseConnector] = {}
        self._classes: dict[str, type[BaseConnector]] = {}
        self._configs: dict[str, dict] = {}

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
                    ):
                        self._classes[connector_dir.name] = obj

    def _load_configs(self) -> None:
        package_dir = Path(__file__).parent
        for connector_dir in package_dir.iterdir():
            if not connector_dir.is_dir() or connector_dir.name.startswith("_"):
                continue
            for yml_file in connector_dir.glob("*.yml"):
                if yml_file.name.endswith(".example.yml"):
                    continue
                try:
                    import yaml

                    with open(yml_file) as f:
                        config = yaml.safe_load(f)
                    if config and "instances" in config:
                        for instance_name, params in config["instances"].items():
                            self._configs[instance_name] = {
                                "type": connector_dir.name,
                                "params": params,
                            }
                except Exception as e:
                    _log.warning(f"Failed to load config {yml_file}: {e}")

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
                    ):
                        self._classes[connector_dir.name] = obj

    def init(self, external_dir: str | None = None) -> None:
        self._discover_classes()
        if external_dir:
            self._discover_external(external_dir)
        self._load_configs()
        for instance_name, cfg in self._configs.items():
            connector_type = cfg["type"]
            cls = self._classes.get(connector_type)
            if cls is None:
                _log.warning(f"No connector class for type '{connector_type}'")
                continue
            params = cfg.get("params") or {}
            connector = cls(instance_name=instance_name, **params)
            self._connectors[instance_name] = connector
        _log.info(f"Registered {len(self._connectors)} connectors")

    def __getattr__(self, name: str) -> BaseConnector:
        if name.startswith("_"):
            raise AttributeError(name)
        if name in self._connectors:
            return self._connectors[name]
        raise AttributeError(f"Connector '{name}' not found")

    def list(self) -> list[dict]:
        return [
            {
                "name": name,
                "type": self._configs.get(name, {}).get("type", "unknown"),
                "connected": c.is_connected,
            }
            for name, c in self._connectors.items()
        ]

    def shutdown(self) -> None:
        for name, connector in self._connectors.items():
            try:
                connector.disconnect()
            except Exception as e:
                _log.warning(f"Error disconnecting {name}: {e}")


connectors = ConnectorRegistry()
