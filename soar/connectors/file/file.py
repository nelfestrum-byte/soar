import json
from pathlib import Path

from soar.connectors.base import BaseConnector


class FileConnector(BaseConnector):
    def __init__(self, instance_name: str, base_path: str = "/tmp"):
        super().__init__(instance_name)
        self.base_path = Path(base_path)

    def _connect_impl(self):
        self.base_path.mkdir(parents=True, exist_ok=True)

    def _resolve(self, path: str) -> Path:
        resolved = (self.base_path / path).resolve()
        if not str(resolved).startswith(str(self.base_path.resolve())):
            raise ValueError(f"Path {path} escapes base_path")
        return resolved

    def write(self, path: str, content: str | bytes) -> bool:
        target = self._resolve(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            target.write_bytes(content)
        else:
            target.write_text(content, encoding="utf-8")
        return True

    def write_json(self, path: str, data: dict) -> bool:
        return self.write(path, json.dumps(data, indent=2, ensure_ascii=False))

    def read(self, path: str) -> str:
        return self._resolve(path).read_text(encoding="utf-8")

    def read_json(self, path: str) -> dict:
        return json.loads(self.read(path))

    def append(self, path: str, content: str) -> bool:
        target = self._resolve(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "a", encoding="utf-8") as f:
            f.write(content)
        return True

    def list_files(self, directory: str = "", pattern: str = "*") -> list[str]:
        target = self._resolve(directory)
        if not target.exists():
            return []
        return [str(p.relative_to(self.base_path)) for p in target.glob(pattern)]

    def delete(self, path: str) -> bool:
        target = self._resolve(path)
        if target.exists():
            target.unlink()
            return True
        return False

    def exists(self, path: str) -> bool:
        return self._resolve(path).exists()
