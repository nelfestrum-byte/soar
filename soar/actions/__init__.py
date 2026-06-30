import importlib
import pkgutil
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

    def init(self) -> None:
        self._discover()
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
