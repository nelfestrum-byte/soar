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

    def _method_name(self, path: str, method: str, operation: dict) -> str:
        """Derive Python method name from path + operationId or fallback."""
        if "operationId" in operation:
            return operation["operationId"]
        parts = [p for p in path.split("/") if p]
        sanitized = []
        for p in parts:
            if p.startswith("{"):
                sanitized.append("by_" + p[1:-1])
            else:
                sanitized.append(p)
        return method.lower() + "_" + "_".join(sanitized)

    def _extract_security(self) -> dict:
        """Parse securitySchemes into auth config for __init__ and _connect_impl."""
        result = {"params": "", "fields": "", "header_setup": "", "config_lines": []}
        if not self.security_schemes:
            return result

        for name, scheme in self.security_schemes.items():
            if scheme.get("type") == "apiKey":
                param_name = scheme.get("name", "api_key")
                location = scheme.get("in", "header")
                result["params"] += f"{param_name}: str = \"\",\n        "
                result["fields"] += f"self.{param_name} = {param_name}\n        "
                if location == "header":
                    result["header_setup"] += f'headers["{param_name}"] = self.{param_name}\n        '
                # Query apiKey added per-request, not in headers

            elif scheme.get("type") == "http":
                if scheme.get("scheme") == "bearer":
                    result["params"] += "token: str = \"\",\n        "
                    result["fields"] += "self.token = token\n        "
                    result['header_setup'] += 'headers["Authorization"] = f"Bearer {self.token}"\n        '
                elif scheme.get("scheme") == "basic":
                    result["params"] += 'username: str = "",\n        password: str = "",\n        '
                    result["fields"] += "self.username = username\n        self.password = password\n        "
                    result["header_setup"] += "auth = httpx.BasicAuth(self.username, self.password)\n        "

            elif scheme.get("type") == "oauth2":
                result["config_lines"].append(
                    f"# WARNING: OAuth2 scheme '{name}' requires manual implementation"
                )

        return result
