import os
import json
from datetime import datetime, UTC
from soar.connectors.base import BaseConnector


class FileConnector(BaseConnector):
    def __init__(self, instance_name: str, base_dir: str = "/var/log/soar/files"):
        super().__init__(instance_name)
        self.base_dir = base_dir
        self._connected = False

    def _connect_impl(self):
        os.makedirs(self.base_dir, exist_ok=True)
        self._connected = True
        self._logger.info(f"File connector ready: {self.base_dir}")

    def disconnect(self):
        self._connected = False
        self._logger.info(f"Disconnected from {self.instance_name}")

    def write(self, filename: str, content: str) -> str:
        self._ensure_connected()
        filepath = os.path.join(self.base_dir, filename)
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, "w") as f:
            f.write(content)
        self._logger.info(f"Written {len(content)} bytes to {filepath}")
        return filepath

    def write_json(self, filename: str, data: dict) -> str:
        self._ensure_connected()
        content = json.dumps(data, indent=2, default=str)
        return self.write(filename, content)

    def write_lines(self, filename: str, lines: list[str]) -> str:
        self._ensure_connected()
        content = "\n".join(lines) + "\n"
        return self.write(filename, content)

    def append(self, filename: str, content: str) -> str:
        self._ensure_connected()
        filepath = os.path.join(self.base_dir, filename)
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, "a") as f:
            f.write(content)
        self._logger.info(f"Appended {len(content)} bytes to {filepath}")
        return filepath

    def read(self, filename: str) -> str:
        self._ensure_connected()
        filepath = os.path.join(self.base_dir, filename)
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"File not found: {filepath}")
        with open(filepath) as f:
            return f.read()

    def list_files(self, subdir: str = "") -> list[str]:
        self._ensure_connected()
        target = os.path.join(self.base_dir, subdir) if subdir else self.base_dir
        if not os.path.exists(target):
            return []
        result = []
        for entry in os.scandir(target):
            if entry.is_file():
                result.append(entry.name)
            elif entry.is_dir():
                result.append(entry.name + "/")
        return sorted(result)

    def delete(self, filename: str) -> bool:
        self._ensure_connected()
        filepath = os.path.join(self.base_dir, filename)
        if os.path.exists(filepath):
            os.remove(filepath)
            self._logger.info(f"Deleted {filepath}")
            return True
        return False
