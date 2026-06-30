import importlib
import pkgutil
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
                    self._workflows[attr_name] = obj

    def init(self) -> None:
        self._discover()
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
