"""Durable file-backed stores for the IRP integration workflows.

JobStore of the orchestrator is in-memory and workflows run as subprocesses,
so progress marks must survive both restarts and process boundaries. A JSON
file with atomic replace (tmp + os.replace) is enough — no new dependencies
(contract §4.3: watermark moves only after a successful ingest).
"""

import json
import os
import time

from soar.logger import get_logger


class WatermarkStore:
    """Key → ISO-8601 UTC timestamp of the last processed event.

    Keys in use: ``siem_alerts`` (triage pull), ``irp_reconcile`` (poller).
    One store, different keys — a single file per deployment.
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
    """Durable "already seen" marks with TTL — dedup between the webhook
    receiver and the reconciliation poller (keys ``irp_seen:{alert_id}``).

    IRP's own Redis dedup keys are not available to us by contract, and the
    orchestrator Redis is optional — a file keeps the guarantee everywhere.
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
