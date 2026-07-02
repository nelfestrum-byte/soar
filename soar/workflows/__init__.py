import importlib
import importlib.util
import pkgutil
import sys
from pathlib import Path

from soar.logger import get_logger
from soar.workflows.base import BaseWorkflow, WorkflowResult

_log = get_logger("workflow.registry")


class WorkflowRegistry:
    def __init__(self):
        self._workflows: dict[str, type[BaseWorkflow]] = {}

    def _discover(self) -> None:
        package_dir = Path(__file__).parent
        for _finder, module_name, is_pkg in pkgutil.iter_modules([str(package_dir)]):
            if is_pkg or module_name.startswith("_") or module_name == "base":
                continue
            fqn = f"soar.workflows.{module_name}"
            try:
                mod = importlib.import_module(fqn)
            except ImportError as e:
                _log.warning(f"Failed to import {fqn}: {e}")
                continue
            for attr_name in dir(mod):
                obj = getattr(mod, attr_name)
                if (
                    isinstance(obj, type)
                    and issubclass(obj, BaseWorkflow)
                    and obj is not BaseWorkflow
                    and obj.__module__ == fqn
                ):
                    # Use filename (module_name) as key, not class name
                    self._workflows[module_name] = obj

    def _discover_external(self, external_dir: str) -> None:
        ext_path = Path(external_dir)
        if not ext_path.exists():
            return
        for py_file in ext_path.glob("*.py"):
            if py_file.name.startswith("_") or py_file.name == "base.py":
                continue
            module_name = py_file.stem
            fqn = f"soar.workflows.{module_name}"
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
                _log.warning(f"Failed to import external workflow {fqn}: {e}")
                continue
            for attr_name in dir(mod):
                obj = getattr(mod, attr_name)
                if (
                    isinstance(obj, type)
                    and issubclass(obj, BaseWorkflow)
                    and obj is not BaseWorkflow
                    and obj.__module__ == fqn
                ):
                    # Use filename (module_name) as key, not class name
                    self._workflows[module_name] = obj

    def init(self, external_dir: str | None = None) -> None:
        self._workflows.clear()
        # Remove stale sys.modules entries for external workflows
        stale = [k for k in sys.modules if k.startswith("soar.workflows.") and k != "soar.workflows.__init__"]
        for key in stale:
            mod = sys.modules.get(key)
            if hasattr(mod, "__file__") and mod.__file__ and not mod.__file__.startswith(str(Path(__file__).parent)):
                del sys.modules[key]
        self._discover()
        if external_dir:
            self._discover_external(external_dir)
        _log.info(f"Registered {len(self._workflows)} workflows")

    def list(self) -> list[dict]:
        result = []
        for name, cls in self._workflows.items():
            meta = {"name": name, "type": cls.workflow_type}
            if hasattr(cls, "schedule"):
                meta["schedule"] = cls.schedule
            if hasattr(cls, "interval"):
                meta["interval"] = cls.interval
            if hasattr(cls, "path"):
                meta["path"] = cls.path
            if hasattr(cls, "token"):
                meta["token"] = cls.token
            result.append(meta)
        return result

    def get(self, name: str) -> dict | None:
        for item in self.list():
            if item["name"] == name:
                return item
        return None

    def get_class(self, name: str) -> type[BaseWorkflow] | None:
        return self._workflows.get(name)

    def execute(self, name: str, context: dict | None = None) -> WorkflowResult:
        cls = self._workflows.get(name)
        if cls is None:
            raise ValueError(f"Workflow '{name}' not found")
        instance = cls()
        return instance.execute(context or {})


workflows = WorkflowRegistry()
