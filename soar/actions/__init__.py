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

    def _register_public_callables(self, mod, fqn: str) -> bool:
        """Register every public top-level callable whose __module__ matches
        this module (E7) — not just the one matching the filename, and not
        any callable merely imported into the module's namespace."""
        found = False
        for attr_name in dir(mod):
            if attr_name.startswith("_"):
                continue
            obj = getattr(mod, attr_name)
            if callable(obj) and getattr(obj, "__module__", None) == fqn:
                if attr_name in self._actions:
                    _log.warning(
                        f"Duplicate action '{attr_name}' in {fqn} — overwriting previous definition"
                    )
                self._actions[attr_name] = obj
                found = True
        return found

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
            if not self._register_public_callables(mod, fqn):
                _log.warning(f"No public callable in {fqn}")

    def _discover_external(self, external_dir: str) -> None:
        ext_path = Path(external_dir)
        if not ext_path.exists():
            return
        for py_file in sorted(ext_path.glob("*.py")):
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
            if not self._register_public_callables(mod, fqn):
                _log.warning(f"No public callable in external {fqn}")

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
