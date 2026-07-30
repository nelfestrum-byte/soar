"""Durable file-backed stores for polling/webhook workflows.

JobStore of the orchestrator is in-memory and workflows run as subprocesses,
so progress marks must survive both restarts and process boundaries. A JSON
file with atomic replace (tmp + os.replace) is enough — no new dependencies.
"""

import json
import os
import time

from soar.logger import get_logger

_DEFAULT_STATE_DIR = "/app/data/state"  # mirrors orchestrator/config.py::SoarConfig.state_dir default


class WatermarkStore:
    """Key → ISO-8601 UTC timestamp of the last processed event.

    One store, many independent keys (e.g. one per poller/pull cycle) —
    a single file per deployment.
    """

    def __init__(self, path: str):
        self.path = path
        self._logger = get_logger("tools.watermark")

    def _load(self) -> dict:
        if not os.path.exists(self.path):
            return {}
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, OSError) as e:
            self._logger.warning(f"watermark file {self.path} unreadable ({e}), treating as empty")
            return {}

    def _save(self, data: dict) -> None:
        directory = os.path.dirname(self.path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        tmp = f"{self.path}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=0)
        os.replace(tmp, self.path)

    def get(self, key: str) -> str | None:
        value = self._load().get(key)
        return value if isinstance(value, str) and value else None

    def set(self, key: str, ts: str) -> None:
        data = self._load()
        data[key] = ts
        self._save(data)


class SeenStore:
    """Durable "already seen" marks with TTL — dedup between two delivery
    paths for the same event (e.g. a webhook receiver and a reconciliation
    poller covering the same source).

    The orchestrator Redis backend is optional — a file keeps the dedup
    guarantee available regardless of deployment.
    """

    def __init__(self, path: str, ttl: int = 86400):
        self.path = path
        self.ttl = ttl
        self._logger = get_logger("tools.seen")

    def _load(self) -> dict:
        if not os.path.exists(self.path):
            return {}
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            self._logger.warning(f"seen file {self.path} unreadable ({e}), treating as empty")
            return {}
        if not isinstance(data, dict):
            return {}
        now = time.time()
        return {k: v for k, v in data.items() if isinstance(v, (int, float)) and v > now}

    def _save(self, data: dict) -> None:
        directory = os.path.dirname(self.path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        tmp = f"{self.path}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp, self.path)

    def is_seen(self, key: str) -> bool:
        return key in self._load()

    def mark(self, key: str) -> None:
        data = self._load()
        data[key] = time.time() + self.ttl
        self._save(data)


def _state_dir() -> str:
    """Read soar.state_dir the same way soar/runner.py reads the rest of
    config.yaml (SOAR_CONFIG env var, raw yaml dict) — soar/ must not import
    orchestrator/ (subprocess runner boundary, one-way dependency, see
    soar/tools/http_client.py docstring for the same rule applied to the
    SSRF guard), so this can't reuse orchestrator.config.SoarConfig."""
    config_path = os.environ.get("SOAR_CONFIG", "config.yaml")
    try:
        import yaml

        with open(config_path) as f:
            config = yaml.safe_load(f) or {}
        state_dir = config.get("soar", {}).get("state_dir")
        if state_dir:
            return state_dir
    except (OSError, yaml.YAMLError):
        pass
    return _DEFAULT_STATE_DIR


def watermark_store(name: str) -> WatermarkStore:
    """Contract-of-singleton factory, like `http_client`: the workflow gives
    a name (usually its own), not a path — the path is a deployment detail
    it shouldn't need to know."""
    return WatermarkStore(path=os.path.join(_state_dir(), f"{name}.watermark.json"))


def seen_store(name: str, ttl: int = 86400) -> SeenStore:
    return SeenStore(path=os.path.join(_state_dir(), f"{name}.seen.json"), ttl=ttl)
