"""OpenAPI 3.x connector generator for SOAR."""
from __future__ import annotations

from pathlib import Path

# mypy: disable-error-code="no-any-return,operator,attr-defined"


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
        import re

        if not re.match(r"^[a-z][a-z0-9_]*$", name):
            raise ValueError(f"Invalid name '{name}': must be snake_case")

        warnings = []
        for scheme in self.security_schemes.values():
            if scheme.get("type") == "oauth2":
                warnings.append("OAuth2 auth detected — generated stub, requires manual implementation")

        conn_dir = output_dir / name
        conn_dir.mkdir(parents=True, exist_ok=True)

        files = []

        py_file = conn_dir / f"{name}.py"
        py_file.write_text(self._generate_class(name), encoding="utf-8")
        files.append(str(py_file.relative_to(output_dir)))

        init_file = conn_dir / "__init__.py"
        init_file.write_text(self._generate_init(name), encoding="utf-8")
        files.append(str(init_file.relative_to(output_dir)))

        yml_file = conn_dir / f"{name}.example.yml"
        yml_file.write_text(self._generate_config(name), encoding="utf-8")
        files.append(str(yml_file.relative_to(output_dir)))

        return {"files": files, "warnings": warnings}

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

    def _extract_security(self) -> dict:  # type: ignore[type-arg]
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

    def _param_signature(self, params: list[dict]) -> str:
        """Generate Python method signature from OpenAPI params."""
        if not params:
            return ""

        type_map = {
            "string": "str",
            "integer": "int",
            "number": "float",
            "boolean": "bool",
            "array": "list",
            "object": "dict",
        }

        result = []
        for p in params:
            schema = p.get("schema", {})
            py_type = type_map.get(schema.get("type", "string"), "str")
            required = p.get("required", False)
            if required:
                result.append(f"{p['name']}: {py_type}")
            else:
                result.append(f"{p['name']}: {py_type} | None = None")
        return ", ".join(result)

    def _has_request_body(self, operation: dict) -> bool:
        """Check if operation has JSON request body."""
        body = operation.get("requestBody", {})
        content = body.get("content", {})
        return "application/json" in content

    def _generate_class(self, name: str) -> str:
        """Generate complete connector Python source code."""
        class_name = "".join(w.capitalize() for w in name.split("_")) + "Connector"
        title = self.spec.get("info", {}).get("title", name)
        base_url = self.servers[0].get("url", "https://api.example.com") if self.servers else "https://api.example.com"
        sec = self._extract_security()

        # Build methods
        methods = []
        for path, path_item in self.paths.items():
            for method in ["get", "post", "put", "delete", "patch"]:
                if method not in path_item:
                    continue
                operation = path_item[method]
                method_name = self._method_name(path, method, operation)
                params = operation.get("parameters", [])
                has_body = self._has_request_body(operation)
                sig = self._param_signature(params)
                if has_body:
                    if sig:
                        sig += ", body: dict | None = None"
                    else:
                        sig = "body: dict | None = None"

                # Build query params list
                query_params = [p["name"] for p in params if p.get("in") == "query"]

                # Build method body
                query_dict = ", ".join(f'"{p}": {p}' for p in query_params)
                method_body = f"""    def {method_name}(self{', ' + sig if sig else ''}) -> dict:
        self._ensure_connected()
        assert self._client is not None
        resp = self._client.{method}("{path}"{', params={' + query_dict + '}' if query_params else ''}{', json=body' if has_body else ''})
        resp.raise_for_status()
        return resp.json()"""
                methods.append(method_body)

        methods_str = "\n\n".join(methods) if methods else "    pass"

        return f'''"""Auto-generated from OpenAPI spec: {title}"""
from __future__ import annotations
import httpx
from soar.connectors.base import BaseConnector


class {class_name}(BaseConnector):
    """Connector for {title}"""

    def __init__(
        self,
        instance_name: str,
        base_url: str = "{base_url}",
        {sec['params']}**kwargs,
    ):
        super().__init__(instance_name, **kwargs)
        self.base_url = base_url
        {sec['fields']}self._client: httpx.Client | None = None

    def _connect_impl(self):
        headers = {{}}
        {sec['header_setup']}self._client = httpx.Client(
            base_url=self.base_url,
            headers=headers,
            timeout=30.0,
        )

    def disconnect(self):
        if self._client:
            self._client.close()
            self._client = None
            self._connected = False

{methods_str}
'''

    def _generate_init(self, name: str) -> str:
        """Generate __init__.py for the connector package."""
        class_name = "".join(w.capitalize() for w in name.split("_")) + "Connector"
        return f"""from soar.connectors.{name}.{name} import {class_name}

__all__ = ["{class_name}"]
"""

    def _generate_config(self, name: str) -> str:
        """Generate .example.yml from securitySchemes + servers."""
        lines = ["instances:", f"  {name}:"]
        lines.append("    # TODO: add instance-specific configuration")

        for _scheme_name, scheme in self.security_schemes.items():
            if scheme.get("type") == "apiKey":
                lines.append(f"    {scheme.get('name', 'api_key')}: YOUR_{scheme.get('name', 'API_KEY').upper()}")
            elif scheme.get("type") == "http":
                if scheme.get("scheme") == "bearer":
                    lines.append("    token: YOUR_BEARER_TOKEN")
                elif scheme.get("scheme") == "basic":
                    lines.append("    username: YOUR_USERNAME")
                    lines.append("    password: YOUR_PASSWORD")

        if self.servers:
            lines.append(f"    base_url: {self.servers[0].get('url', 'https://api.example.com')}")

        return "\n".join(lines) + "\n"
