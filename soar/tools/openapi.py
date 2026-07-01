"""OpenAPI 3.x connector generator for SOAR."""
from __future__ import annotations

from pathlib import Path


class OpenAPIGenerator:
    """Parse OpenAPI spec and generate SOAR connector code."""

    def __init__(self, spec: dict):
        if "openapi" not in spec:
            raise ValueError("Not an OpenAPI spec: missing 'openapi' version field")
        if "paths" not in spec:
            raise ValueError("Not an OpenAPI spec: missing 'paths' section")
        self.spec = spec
        self.servers = spec.get("servers", [])
        self.paths = spec.get("paths", {})
        self.components = spec.get("components", {})
        self.security_schemes = self.components.get("securitySchemes", {})

    def generate(self, name: str, output_dir: Path) -> dict:
        """Generate connector files. Returns dict with 'files' and 'warnings'."""
        raise NotImplementedError

    def _resolve_ref(self, ref: str) -> dict:
        """Resolve a $ref pointer like '#/components/schemas/User'."""
        if not ref.startswith("#/"):
            raise ValueError(f"Cannot resolve external $ref: {ref}")
        parts = ref[2:].split("/")
        current = self.spec
        for part in parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                raise ValueError(f"Cannot resolve $ref: {ref}")
        return current
