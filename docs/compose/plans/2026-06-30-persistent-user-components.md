# Persistent User Components Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use compose:subagent (recommended) or compose:execute to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make user-created connectors, actions, and workflows persist across Docker container rebuilds by storing them in the `/app/data/` volume.

**Architecture:** Change config paths from `/app/soar/` to `/app/data/` subdirectories. Update registries to scan both the built-in `soar` package and the external data directories. The existing `soar-data` Docker volume already mounts `/app/data`, so no docker-compose changes are needed.

**Tech Stack:** Python 3.11+, FastAPI, Docker, importlib

## Global Constraints

- Paths must be configurable via `config.yaml` (no hardcoding)
- Built-in components in `soar/` package must continue working alongside user components in `/app/data/`
- Git history must persist in `/app/data/.git/`
- No breaking changes to existing API contracts

---

## File Structure

| File | Responsibility |
|------|---------------|
| `orchestrator/config.py` | Default paths to `/app/data/` subdirs |
| `orchestrator/main.py` | Read `SOAR_CONFIG` env var, pass config to registries |
| `deploy/stage/config.yaml` | Updated paths |
| `deploy/stage/Dockerfile.orchestrator` | Seed `/app/data/` with built-in content |
| `soar/connectors/__init__.py` | Scan external connectors dir |
| `soar/actions/__init__.py` | Scan external actions dir |
| `soar/workflows/__init__.py` | Scan external workflows dir |
| `soar/runner.py` | Load config, pass dirs to registries |

---

### Task 1: Update config paths and SOAR_CONFIG handling

**Covers:** Config defaults, env var support

**Files:**
- Modify: `orchestrator/config.py`
- Modify: `deploy/stage/config.yaml`
- Modify: `orchestrator/main.py`

**Interfaces:**
- Consumes: `SOAR_CONFIG` env var
- Produces: `OrchestratorConfig` with updated default paths

- [ ] **Step 1: Update config defaults**

In `orchestrator/config.py`, change `SoarConfig` defaults:

```python
class SoarConfig(BaseModel):
    workflows_dir: str = "/app/data/workflows"
    connectors_dir: str = "/app/data/connectors"
    actions_dir: str = "/app/data/actions"
```

Change `GitConfig` default:

```python
class GitConfig(BaseModel):
    workflows_repo: str = "/app/data"
    author_name: str = "SOAR Orchestrator"
    author_email: str = "soar@local"
```

- [ ] **Step 2: Update deploy/stage/config.yaml**

```yaml
soar:
  workflows_dir: /app/data/workflows
  connectors_dir: /app/data/connectors
  actions_dir: /app/data/actions

git:
  workflows_repo: /app/data
```

- [ ] **Step 3: Fix main.py to respect SOAR_CONFIG**

In `orchestrator/main.py`, change line 88 from:

```python
config = load_config("config.yaml")
```

to:

```python
import os
config_path = os.environ.get("SOAR_CONFIG", "config.yaml")
config = load_config(config_path)
```

- [ ] **Step 4: Commit**

```bash
git add orchestrator/config.py deploy/stage/config.yaml orchestrator/main.py
git commit -m "feat: update config paths to /app/data/ for persistence"
```

---

### Task 2: Update Dockerfile to seed initial content

**Covers:** First-run initialization

**Files:**
- Modify: `deploy/stage/Dockerfile.orchestrator`

**Interfaces:**
- Consumes: Built-in content from `soar/` package
- Produces: `/app/data/` populated with initial workflows, actions, connectors

- [ ] **Step 1: Update Dockerfile**

In `deploy/stage/Dockerfile.orchestrator`, after the existing `COPY` lines, add seeding logic. Replace the `RUN mkdir` line (line 17) with:

```dockerfile
COPY soar/ /app/soar/
COPY orchestrator/ /app/orchestrator/

RUN pip install --no-cache-dir \
    fastapi uvicorn pyyaml loguru pydantic python-multipart \
    apscheduler sse-starlette redis elasticsearch vt-py \
    requests

RUN mkdir -p /app/data /var/log/soar/jobs && \
    cp -rn /app/soar/workflows/*.py /app/data/workflows/ 2>/dev/null || true && \
    cp -rn /app/soar/actions/*.py /app/data/actions/ 2>/dev/null || true && \
    cp -rn /app/soar/connectors/*/ /app/data/connectors/ 2>/dev/null || true && \
    chown -R soar:soar /app /var/log/soar

COPY deploy/stage/config.yaml /app/data/config.yaml
```

Note: `cp -rn` only copies if the destination doesn't exist, so existing volume data is preserved.

- [ ] **Step 2: Commit**

```bash
git add deploy/stage/Dockerfile.orchestrator
git commit -m "feat: seed /app/data/ with built-in components on first build"
```

---

### Task 3: Update registries to scan external directories

**Covers:** Runtime discovery of user components

**Files:**
- Modify: `soar/connectors/__init__.py`
- Modify: `soar/actions/__init__.py`
- Modify: `soar/workflows/__init__.py`

**Interfaces:**
- Consumes: External directory paths (via config or direct path)
- Produces: Registries that include both built-in and user components

- [ ] **Step 1: Update ConnectorRegistry**

In `soar/connectors/__init__.py`, add a method to scan external directories and update `init()`:

```python
import importlib.util

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
```

- [ ] **Step 2: Update ActionsRegistry**

In `soar/actions/__init__.py`, add external directory scanning:

```python
import importlib.util
import sys

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
```

- [ ] **Step 3: Update WorkflowRegistry**

In `soar/workflows/__init__.py`, add external directory scanning:

```python
import importlib.util
import sys

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
                    self._workflows[attr_name] = obj

    def init(self, external_dir: str | None = None) -> None:
        self._discover()
        if external_dir:
            self._discover_external(external_dir)
        _log.info(f"Registered {len(self._workflows)} workflows")
```

- [ ] **Step 4: Commit**

```bash
git add soar/connectors/__init__.py soar/actions/__init__.py soar/workflows/__init__.py
git commit -m "feat: registries scan external data directories"
```

---

### Task 4: Update runner to pass config to registries

**Covers:** Subprocess execution discovers user components

**Files:**
- Modify: `soar/runner.py`

**Interfaces:**
- Consumes: `SOAR_CONFIG` env var, config paths
- Produces: Registries initialized with external dirs

- [ ] **Step 1: Update runner.py**

In `soar/runner.py`, load config and pass external dirs to registries:

```python
import json
import os
import sys

from soar.actions import actions
from soar.connectors import connectors
from soar.logger import setup_logging
from soar.workflows import workflows

setup_logging(level="INFO")

# Load config to get external directories
from orchestrator.config import load_config
config_path = os.environ.get("SOAR_CONFIG", "config.yaml")
config = load_config(config_path)

workflows.init(external_dir=config.soar.workflows_dir)
connectors.init(external_dir=config.soar.connectors_dir)
actions.init(external_dir=config.soar.actions_dir)
```

- [ ] **Step 2: Commit**

```bash
git add soar/runner.py
git commit -m "feat: runner loads config and passes external dirs to registries"
```

---

### Task 5: Verify with tests

**Covers:** Regression testing

**Files:**
- Test: existing tests should still pass

- [ ] **Step 1: Run existing tests**

```bash
python -m pytest tests/ -v
```

- [ ] **Step 2: Verify lint and typecheck**

```bash
ruff check .
mypy orchestrator/ soar/ --ignore-missing-imports
```

- [ ] **Step 3: Commit if needed**

```bash
git add -A
git commit -m "chore: verify persistence changes pass all checks"
```
