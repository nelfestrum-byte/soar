import importlib
import importlib.util
import pkgutil
import sys
from collections.abc import Callable
from pathlib import Path

from soar.logger import get_logger

_log = get_logger("action.registry")


class ActionsRegistry:
    def __init__(self):
        self._actions: dict[str, Callable] = {}

    def _discover(self) -> None:
        package_dir = Path(__file__).parent
        for _finder, module_name, is_pkg in pkgutil.iter_modules([str(package_dir)]):
            if is_pkg or module_name.startswith("_"):
                continue
            fqn = f"soar.actions.{module_name}"
            try:
                mod = importlib.import_module(fqn)
            except ImportError as e:
                _log.warning(f"Failed to import {fqn}: {e}")
                continue
            func = getattr(mod, module_name, None)
            if callable(func):
                self._actions[module_name] = func
            else:
                _log.warning(f"No callable '{module_name}' in {fqn}")

    def _discover_external(self, external_dir: str) -> None:
        ext_path = Path(external_dir)
        if not ext_path.exists():
            return
        for py_file in ext_path.glob("*.py"):
            if py_file.name.startswith("_"):
                continue
            module_name = py_file.stem
            fqn = f"soar.actions.{module_name}"
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
                _log.warning(f"Failed to import external action {fqn}: {e}")
                continue
            func = getattr(mod, module_name, None)
            if callable(func):
                self._actions[module_name] = func
            else:
                _log.warning(f"No callable '{module_name}' in external {fqn}")

    def init(self, external_dir: str | None = None) -> None:
        self._discover()
        if external_dir:
            self._discover_external(external_dir)
        _log.info(f"Registered {len(self._actions)} actions")

    def __getattr__(self, name: str):
        if name.startswith("_"):
            raise AttributeError(name)
        if name in self._actions:
            return self._actions[name]
        raise AttributeError(f"Action '{name}' not found")

    def list(self) -> list[str]:
        return list(self._actions.keys())


actions = ActionsRegistry()
