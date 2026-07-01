# OpenAPI Connector Generator Implementation Plan

> [!NOTE]
> This document may not reflect the current implementation.
> See the final report for up-to-date state:
> [Final Report](../reports/openapi-connector-generator.md)

> **For agentic workers:** REQUIRED SUB-SKILL: Use compose:subagent (recommended) or compose:execute to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate working SOAR connectors from OpenAPI 3.x specs via API endpoint

**Architecture:** Generator module (`soar/tools/openapi.py`) + API endpoint (`POST /connectors/generate`). Uses httpx as HTTP client. Auth: API key, Bearer, Basic (MVP). Generates: connector .py, __init__.py, .example.yml.

**Tech Stack:** Python 3.11+, httpx, PyYAML, FastAPI, pytest

## Global Constraints

- Python 3.11+ only (use `X | None` syntax, not Optional)
- httpx for HTTP client (not requests)
- f-strings for code generation (no Jinja2)
- All connector methods return `dict` or `list[dict]`
- Follow existing connector patterns in `soar/connectors/`
- Tests use pytest + pytest-asyncio + httpx.AsyncClient

---

## File Map

```
soar/
├── tools/
│   ├── __init__.py          # NEW — empty
│   └── openapi.py           # NEW — OpenAPIGenerator class
orchestrator/
├── api/
│   └── connectors.py        # MODIFY — add POST /connectors/generate
tests/
├── soar/
│   └── tools/
│       └── test_openapi.py  # NEW — unit tests for generator
└── orchestrator/
    └── api/
        └── test_connectors_api.py  # MODIFY — add generate endpoint tests
```

---

## Task 1: Create generator module scaffold with spec parsing

**Covers:** [S1, S2, S5]

**Files:**
- Create: `soar/tools/__init__.py`
- Create: `soar/tools/openapi.py`
- Create: `tests/soar/tools/test_openapi.py`

**Interfaces:**
- Consumes: OpenAPI spec as `dict` (parsed from YAML/JSON)
- Produces: `OpenAPIGenerator` class with `generate()` method

- [ ] **Step 1: Create soar/tools/__init__.py**

```python
```

Empty file, makes `soar.tools` a package.

- [ ] **Step 2: Write failing test for spec parsing**

Create `tests/soar/tools/test_openapi.py`:

```python
import pytest
from pathlib import Path
from soar.tools.openapi import OpenAPIGenerator


MINIMAL_SPEC = {
    "openapi": "3.0.0",
    "info": {"title": "Test API", "version": "1.0.0"},
    "paths": {},
}


def test_generator_parses_spec():
    gen = OpenAPIGenerator(MINIMAL_SPEC)
    assert gen.spec == MINIMAL_SPEC
    assert gen.paths == {}


def test_generator_requires_openapi_version():
    with pytest.raises(ValueError, match="openapi"):
        OpenAPIGenerator({"paths": {}})


def test_generator_requires_paths():
    with pytest.raises(ValueError, match="paths"):
        OpenAPIGenerator({"openapi": "3.0.0", "info": {"title": "X", "version": "1"}})
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m pytest tests/soar/tools/test_openapi.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'soar.tools.openapi'`

- [ ] **Step 4: Implement spec parsing in soar/tools/openapi.py**

```python
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
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/soar/tools/test_openapi.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add soar/tools/__init__.py soar/tools/openapi.py tests/soar/tools/test_openapi.py
git commit -m "feat: add OpenAPI generator scaffold with spec parsing"
```

---

## Task 2: Implement $ref resolution

**Covers:** [S5]

**Files:**
- Modify: `soar/tools/openapi.py`
- Modify: `tests/soar/tools/test_openapi.py`

**Interfaces:**
- Consumes: OpenAPI spec with `$ref` pointers
- Produces: `_resolve_ref(ref: str) -> dict` method

- [ ] **Step 1: Write failing tests for $ref resolution**

Add to `tests/soar/tools/test_openapi.py`:

```python
SPEC_WITH_REFS = {
    "openapi": "3.0.0",
    "info": {"title": "Test API", "version": "1.0.0"},
    "paths": {},
    "components": {
        "schemas": {
            "User": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "name": {"type": "string"},
                },
            }
        }
    },
}


def test_resolve_ref():
    gen = OpenAPIGenerator(SPEC_WITH_REFS)
    result = gen._resolve_ref("#/components/schemas/User")
    assert result["type"] == "object"
    assert "id" in result["properties"]


def test_resolve_ref_not_found():
    gen = OpenAPIGenerator(MINIMAL_SPEC)
    with pytest.raises(ValueError, match="Cannot resolve"):
        gen._resolve_ref("#/components/schemas/Nonexistent")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/soar/tools/test_openapi.py -v`
Expected: FAIL — `AttributeError: 'OpenAPIGenerator' has no attribute '_resolve_ref'`

- [ ] **Step 3: Implement _resolve_ref**

Add to `soar/tools/openapi.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/soar/tools/test_openapi.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add soar/tools/openapi.py tests/soar/tools/test_openapi.py
git commit -m "feat: add $ref resolution to OpenAPI generator"
```

---

## Task 3: Implement method name derivation

**Covers:** [S5]

**Files:**
- Modify: `soar/tools/openapi.py`
- Modify: `tests/soar/tools/test_openapi.py`

**Interfaces:**
- Consumes: path string, HTTP method, operation dict
- Produces: `_method_name(path, method, operation) -> str`

- [ ] **Step 1: Write failing tests for method naming**

Add to `tests/soar/tools/test_openapi.py`:

```python
def test_method_name_from_operation_id():
    gen = OpenAPIGenerator(MINIMAL_SPEC)
    result = gen._method_name("/users", "get", {"operationId": "listUsers"})
    assert result == "listUsers"


def test_method_name_derived_from_path():
    gen = OpenAPIGenerator(MINIMAL_SPEC)
    result = gen._method_name("/users/{id}/posts", "get", {})
    assert result == "get_users_by_id_posts"


def test_method_name_simple_path():
    gen = OpenAPIGenerator(MINIMAL_SPEC)
    result = gen._method_name("/health", "get", {})
    assert result == "get_health"


def test_method_name_post_with_body():
    gen = OpenAPIGenerator(MINIMAL_SPEC)
    result = gen._method_name("/users", "post", {})
    assert result == "post_users"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/soar/tools/test_openapi.py::test_method_name_from_operation_id -v`
Expected: FAIL — `AttributeError`

- [ ] **Step 3: Implement _method_name**

Add to `soar/tools/openapi.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/soar/tools/test_openapi.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add soar/tools/openapi.py tests/soar/tools/test_openapi.py
git commit -m "feat: add method name derivation from OpenAPI paths"
```

---

## Task 4: Implement auth scheme extraction

**Covers:** [S3, S5]

**Files:**
- Modify: `soar/tools/openapi.py`
- Modify: `tests/soar/tools/test_openapi.py`

**Interfaces:**
- Consumes: `securitySchemes` from OpenAPI spec
- Produces: `_extract_security() -> dict` with `params`, `fields`, `header_setup`, `config_lines`

- [ ] **Step 1: Write failing tests for auth extraction**

Add to `tests/soar/tools/test_openapi.py`:

```python
SPEC_API_KEY_HEADER = {
    "openapi": "3.0.0",
    "info": {"title": "API Key API", "version": "1.0.0"},
    "paths": {},
    "components": {
        "securitySchemes": {
            "ApiKey": {"type": "apiKey", "in": "header", "name": "X-API-Key"}
        }
    },
}

SPEC_BEARER = {
    "openapi": "3.0.0",
    "info": {"title": "Bearer API", "version": "1.0.0"},
    "paths": {},
    "components": {
        "securitySchemes": {
            "BearerAuth": {"type": "http", "scheme": "bearer"}
        }
    },
}

SPEC_BASIC = {
    "openapi": "3.0.0",
    "info": {"title": "Basic API", "version": "1.0.0"},
    "paths": {},
    "components": {
        "securitySchemes": {
            "BasicAuth": {"type": "http", "scheme": "basic"}
        }
    },
}


def test_extract_api_key_header():
    gen = OpenAPIGenerator(SPEC_API_KEY_HEADER)
    sec = gen._extract_security()
    assert sec["params"] == "api_key: str = \"\",\n        "
    assert "X-API-Key" in sec["header_setup"]


def test_extract_bearer():
    gen = OpenAPIGenerator(SPEC_BEARER)
    sec = gen._extract_security()
    assert sec["params"] == "token: str = \"\",\n        "
    assert "Bearer" in sec["header_setup"]


def test_extract_basic():
    gen = OpenAPIGenerator(SPEC_BASIC)
    sec = gen._extract_security()
    assert "username" in sec["params"]
    assert "password" in sec["params"]
    assert "BasicAuth" in sec["header_setup"]


def test_extract_no_security():
    gen = OpenAPIGenerator(MINIMAL_SPEC)
    sec = gen._extract_security()
    assert sec["params"] == ""
    assert sec["header_setup"] == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/soar/tools/test_openapi.py::test_extract_api_key_header -v`
Expected: FAIL — `AttributeError`

- [ ] **Step 3: Implement _extract_security**

Add to `soar/tools/openapi.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/soar/tools/test_openapi.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add soar/tools/openapi.py tests/soar/tools/test_openapi.py
git commit -m "feat: add auth scheme extraction for API key, Bearer, Basic"
```

---

## Task 5: Implement method signature generation

**Covers:** [S5]

**Files:**
- Modify: `soar/tools/openapi.py`
- Modify: `tests/soar/tools/test_openapi.py`

**Interfaces:**
- Consumes: list of OpenAPI parameter objects
- Produces: `_param_signature(params) -> str` with Python method parameters

- [ ] **Step 1: Write failing tests for param signatures**

Add to `tests/soar/tools/test_openapi.py`:

```python
def test_param_signature_empty():
    gen = OpenAPIGenerator(MINIMAL_SPEC)
    result = gen._param_signature([])
    assert result == ""


def test_param_signature_path_params():
    gen = OpenAPIGenerator(MINIMAL_SPEC)
    params = [
        {"name": "user_id", "in": "path", "required": True, "schema": {"type": "integer"}},
    ]
    result = gen._param_signature(params)
    assert "user_id: int" in result


def test_param_signature_query_params():
    gen = OpenAPIGenerator(MINIMAL_SPEC)
    params = [
        {"name": "limit", "in": "query", "required": False, "schema": {"type": "integer"}},
        {"name": "q", "in": "query", "required": False, "schema": {"type": "string"}},
    ]
    result = gen._param_signature(params)
    assert "limit: int | None = None" in result
    assert "q: str | None = None" in result


def test_param_signature_mixed():
    gen = OpenAPIGenerator(MINIMAL_SPEC)
    params = [
        {"name": "org", "in": "path", "required": True, "schema": {"type": "string"}},
        {"name": "page", "in": "query", "required": False, "schema": {"type": "integer"}},
    ]
    result = gen._param_signature(params)
    assert "org: str" in result
    assert "page: int | None = None" in result
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/soar/tools/test_openapi.py::test_param_signature_empty -v`
Expected: FAIL — `AttributeError`

- [ ] **Step 3: Implement _param_signature**

Add to `soar/tools/openapi.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/soar/tools/test_openapi.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add soar/tools/openapi.py tests/soar/tools/test_openapi.py
git commit -m "feat: add method signature generation from OpenAPI params"
```

---

## Task 6: Implement full connector code generation

**Covers:** [S2, S5]

**Files:**
- Modify: `soar/tools/openapi.py`
- Modify: `tests/soar/tools/test_openapi.py`

**Interfaces:**
- Consumes: parsed spec, connector name
- Produces: `_generate_class(name) -> str` with complete connector Python code

- [ ] **Step 1: Write failing tests for code generation**

Add to `tests/soar/tools/test_openapi.py`:

```python
SPEC_WITH_ENDPOINTS = {
    "openapi": "3.0.0",
    "info": {"title": "Petstore", "version": "1.0.0"},
    "servers": [{"url": "https://api.petstore.com/v1"}],
    "paths": {
        "/pets": {
            "get": {
                "operationId": "listPets",
                "parameters": [
                    {"name": "limit", "in": "query", "required": False, "schema": {"type": "integer"}},
                ],
                "responses": {"200": {"description": "OK"}},
            },
            "post": {
                "operationId": "createPet",
                "requestBody": {
                    "content": {"application/json": {"schema": {"type": "object"}}}
                },
                "responses": {"201": {"description": "Created"}},
            },
        },
        "/pets/{petId}": {
            "get": {
                "operationId": "getPet",
                "parameters": [
                    {"name": "petId", "in": "path", "required": True, "schema": {"type": "string"}},
                ],
                "responses": {"200": {"description": "OK"}},
            },
        },
    },
}


def test_generate_class_has_required_parts():
    gen = OpenAPIGenerator(SPEC_WITH_ENDPOINTS)
    code = gen._generate_class("petstore")
    assert "class PetstoreConnector(BaseConnector):" in code
    assert "def _connect_impl(self):" in code
    assert "def disconnect(self):" in code
    assert "def listPets(self" in code
    assert "def createPet(self" in code
    assert "def getPet(self" in code
    assert "httpx.Client" in code
    assert "self._ensure_connected()" in code
    assert "raise_for_status" in code


def test_generate_class_with_auth():
    gen = OpenAPIGenerator({**SPEC_WITH_ENDPOINTS, **SPEC_API_KEY_HEADER["components"] | {"securitySchemes": SPEC_API_KEY_HEADER["components"]["securitySchemes"]}})
    gen.security_schemes = SPEC_API_KEY_HEADER["components"]["securitySchemes"]
    code = gen._generate_class("secure_api")
    assert "X-API-Key" in code
    assert "api_key" in code
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/soar/tools/test_openapi.py::test_generate_class_has_required_parts -v`
Expected: FAIL — `AttributeError`

- [ ] **Step 3: Implement _generate_class**

Add to `soar/tools/openapi.py`:

```python
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
                path_params = [p["name"] for p in params if p.get("in") == "path"]

                # Build method body
                method_body = f"""    def {method_name}(self{', ' + sig if sig else ''}) -> dict:
        self._ensure_connected()
        assert self._client is not None
        resp = self._client.{method}("{path}"{', params={' + ', '.join(f'"{p}": {p}' for p in query_params) + '}' if query_params else ''}{', json=body' if has_body else ''})
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
```

Add helper method:

```python
    def _has_request_body(self, operation: dict) -> bool:
        """Check if operation has JSON request body."""
        body = operation.get("requestBody", {})
        content = body.get("content", {})
        return "application/json" in content
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/soar/tools/test_openapi.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add soar/tools/openapi.py tests/soar/tools/test_openapi.py
git commit -m "feat: add full connector code generation from OpenAPI spec"
```

---

## Task 7: Implement __init__.py and config generation

**Covers:** [S2, S5, S7]

**Files:**
- Modify: `soar/tools/openapi.py`
- Modify: `tests/soar/tools/test_openapi.py`

**Interfaces:**
- Consumes: connector name, security schemes
- Produces: `_generate_init(name) -> str`, `_generate_config(name) -> str`

- [ ] **Step 1: Write failing tests for init and config generation**

Add to `tests/soar/tools/test_openapi.py`:

```python
def test_generate_init():
    gen = OpenAPIGenerator(MINIMAL_SPEC)
    init_code = gen._generate_init("my_api")
    assert "from soar.connectors.my_api.my_api import MyApiConnector" in init_code
    assert "__all__" in init_code


def test_generate_config():
    gen = OpenAPIGenerator(MINIMAL_SPEC)
    config = gen._generate_config("my_api")
    assert "instances:" in config
    assert "my_api:" in config


def test_generate_config_with_auth():
    gen = OpenAPIGenerator(SPEC_API_KEY_HEADER)
    config = gen._generate_config("secure_api")
    assert "api_key:" in config or "X-API-Key:" in config
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/soar/tools/test_openapi.py::test_generate_init -v`
Expected: FAIL — `AttributeError`

- [ ] **Step 3: Implement _generate_init and _generate_config**

Add to `soar/tools/openapi.py`:

```python
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

        for scheme_name, scheme in self.security_schemes.items():
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/soar/tools/test_openapi.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add soar/tools/openapi.py tests/soar/tools/test_openapi.py
git commit -m "feat: add __init__.py and config generation for OpenAPI connectors"
```

---

## Task 8: Implement file writing in generate()

**Covers:** [S2, S6, S7]

**Files:**
- Modify: `soar/tools/openapi.py`
- Modify: `tests/soar/tools/test_openapi.py`

**Interfaces:**
- Consumes: connector name, output directory
- Produces: `generate(name, output_dir) -> dict` with files and warnings

- [ ] **Step 1: Write failing test for generate()**

Add to `tests/soar/tools/test_openapi.py`:

```python
def test_generate_creates_files(tmp_path):
    gen = OpenAPIGenerator(SPEC_WITH_ENDPOINTS)
    result = gen.generate("petstore", tmp_path)
    assert "files" in result
    assert "warnings" in result
    assert len(result["files"]) == 3
    assert (tmp_path / "petstore" / "petstore.py").exists()
    assert (tmp_path / "petstore" / "__init__.py").exists()
    assert (tmp_path / "petstore" / "petstore.example.yml").exists()


def test_generate_validates_name():
    gen = OpenAPIGenerator(MINIMAL_SPEC)
    with pytest.raises(ValueError, match="Invalid name"):
        gen.generate("invalid name!", tmp_path)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/soar/tools/test_openapi.py::test_generate_creates_files -v`
Expected: FAIL — `NotImplementedError`

- [ ] **Step 3: Implement generate()**

Replace the `generate` method in `soar/tools/openapi.py`:

```python
    def generate(self, name: str, output_dir: Path) -> dict:
        """Generate connector files. Returns dict with 'files' and 'warnings'."""
        import re

        if not re.match(r"^[a-z][a-z0-9_]*$", name):
            raise ValueError(f"Invalid name '{name}': must be snake_case")

        warnings = []
        for scheme in self.security_schemes.values():
            if scheme.get("type") == "oauth2":
                warnings.append(f"OAuth2 auth detected — generated stub, requires manual implementation")

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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/soar/tools/test_openapi.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add soar/tools/openapi.py tests/soar/tools/test_openapi.py
git commit -m "feat: implement full generate() with file writing"
```

---

## Task 9: Add API endpoint POST /connectors/generate

**Covers:** [S6, S8]

**Files:**
- Modify: `orchestrator/api/connectors.py`
- Modify: `tests/orchestrator/api/test_connectors_api.py`

**Interfaces:**
- Consumes: request body with `spec`, `name`, `overwrite`
- Produces: JSON response with files and warnings

- [ ] **Step 1: Write failing test for generate endpoint**

Add to `tests/orchestrator/api/test_connectors_api.py`:

```python
import json
import yaml


SAMPLE_SPEC = {
    "openapi": "3.0.0",
    "info": {"title": "Test Generated API", "version": "1.0.0"},
    "servers": [{"url": "https://api.test.com"}],
    "paths": {
        "/items": {
            "get": {
                "operationId": "listItems",
                "responses": {"200": {"description": "OK"}},
            }
        }
    },
}


@pytest.mark.asyncio
async def test_generate_connector():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post(
            "/connectors/generate",
            json={"spec": json.dumps(SAMPLE_SPEC), "name": "gen_test"},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["name"] == "gen_test"
        assert len(data["files"]) == 3


@pytest.mark.asyncio
async def test_generate_connector_invalid_spec():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post(
            "/connectors/generate",
            json={"spec": "not valid yaml or json {{{", "name": "bad"},
        )
        assert r.status_code == 400


@pytest.mark.asyncio
async def test_generate_connector_invalid_name():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post(
            "/connectors/generate",
            json={"spec": json.dumps(SAMPLE_SPEC), "name": "Invalid Name!"},
        )
        assert r.status_code == 400
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/orchestrator/api/test_connectors_api.py::test_generate_connector -v`
Expected: FAIL — 404 or 405 (endpoint doesn't exist)

- [ ] **Step 3: Add endpoint to connectors.py**

Add to `orchestrator/api/connectors.py`:

```python
import json
import yaml as pyyaml
from pydantic import BaseModel
from soar.tools.openapi import OpenAPIGenerator


class GenerateRequest(BaseModel):
    spec: str
    name: str
    overwrite: bool = False


@router.post("/generate")
async def generate_connector(request: Request, body: GenerateRequest):
    config = request.app.state.config
    connectors_dir = Path(config.soar.connectors_dir)

    # Parse spec (try JSON first, then YAML)
    try:
        spec = json.loads(body.spec)
    except json.JSONDecodeError:
        try:
            spec = pyyaml.safe_load(body.spec)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid spec format: not valid JSON or YAML")

    if not isinstance(spec, dict):
        raise HTTPException(status_code=400, detail="Invalid spec format: must be a mapping")

    # Validate and generate
    try:
        generator = OpenAPIGenerator(spec)
        result = generator.generate(body.name, connectors_dir)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Git auto-commit
    git = request.app.state.git
    try:
        for f in result["files"]:
            await git.commit(f, f"Generated connector: {body.name}")
    except RuntimeError:
        pass

    return {"name": body.name, **result}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/orchestrator/api/test_connectors_api.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add orchestrator/api/connectors.py tests/orchestrator/api/test_connectors_api.py
git commit -m "feat: add POST /connectors/generate endpoint"
```

---

## Task 10: Add error handling and edge cases

**Covers:** [S8]

**Files:**
- Modify: `soar/tools/openapi.py`
- Modify: `tests/soar/tools/test_openapi.py`

**Interfaces:**
- Consumes: edge case specs
- Produces: proper error messages and warnings

- [ ] **Step 1: Write tests for edge cases**

Add to `tests/soar/tools/test_openapi.py`:

```python
def test_generate_with_oauth2_warning(tmp_path):
    spec = {
        "openapi": "3.0.0",
        "info": {"title": "OAuth API", "version": "1.0.0"},
        "paths": {},
        "components": {
            "securitySchemes": {
                "OAuth2": {
                    "type": "oauth2",
                    "flows": {"authorizationCode": {"authorizationUrl": "...", "tokenUrl": "..."}},
                }
            }
        },
    }
    gen = OpenAPIGenerator(spec)
    result = gen.generate("oauth_api", tmp_path)
    assert any("OAuth2" in w for w in result["warnings"])


def test_generate_with_no_paths(tmp_path):
    spec = {"openapi": "3.0.0", "info": {"title": "Empty", "version": "1.0.0"}, "paths": {}}
    gen = OpenAPIGenerator(spec)
    result = gen.generate("empty_api", tmp_path)
    assert len(result["files"]) == 3
    # Generated class should have 'pass' since no methods
    py_content = (tmp_path / "empty_api" / "empty_api.py").read_text()
    assert "pass" in py_content
```

- [ ] **Step 2: Run tests to verify they fail or pass (adjust as needed)**

Run: `python -m pytest tests/soar/tools/test_openapi.py -v`
Expected: Some tests may fail if edge cases aren't handled

- [ ] **Step 3: Fix any edge case issues in generator**

Review and fix issues found in step 2.

- [ ] **Step 4: Run all tests**

Run: `python -m pytest tests/soar/tools/test_openapi.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add soar/tools/openapi.py tests/soar/tools/test_openapi.py
git commit -m "feat: handle edge cases and OAuth2 warnings in OpenAPI generator"
```

---

## Task 11: Run full test suite and verify

**Covers:** [S9]

**Files:**
- None (verification only)

- [ ] **Step 1: Run all OpenAPI generator tests**

Run: `python -m pytest tests/soar/tools/test_openapi.py -v`
Expected: All tests PASS

- [ ] **Step 2: Run all connector API tests**

Run: `python -m pytest tests/orchestrator/api/test_connectors_api.py -v`
Expected: All tests PASS

- [ ] **Step 3: Run linter**

Run: `ruff check soar/tools/ orchestrator/api/connectors.py`
Expected: No errors

- [ ] **Step 4: Run type checker**

Run: `mypy soar/tools/ orchestrator/api/connectors.py --ignore-missing-imports`
Expected: No errors

- [ ] **Step 5: Final commit if needed**

If any fixes were needed:
```bash
git add -A
git commit -m "fix: lint and type check fixes for OpenAPI generator"
```
