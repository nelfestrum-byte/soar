# OpenAPI Connector Generator — Design Spec

> [!NOTE]
> This document may not reflect the current implementation.
> See the final report for up-to-date state:
> [Final Report](../reports/openapi-connector-generator.md)

## [S1] Problem

SOAR requires manual implementation of each connector (class, methods, config). Shuffle SOAR offers OpenAPI spec import to auto-generate integrations. We need the same capability: import an OpenAPI 3.x spec and generate a working connector with minimal manual intervention.

## [S2] Solution Overview

Two components:

1. **Generator module** (`soar/tools/openapi.py`) — parses OpenAPI spec, generates connector code
2. **API endpoint** (`POST /connectors/generate`) — accepts spec, writes files, returns result

Generated artifacts per connector:
- `soar/connectors/<name>/<name>.py` — connector class
- `soar/connectors/<name>/__init__.py` — re-export
- `soar/connectors/<name>/<name>.example.yml` — config template

## [S3] Scope — MVP Features

### Supported
- HTTP methods: GET, POST, PUT, DELETE, PATCH
- Parameters: path, query, header, cookie
- Request body: JSON (application/json)
- Response parsing: JSON responses → dict
- Auth schemes (MVP):
  - `apiKey` — header or query parameter
  - `http` — Bearer token
  - `http` — Basic auth
- Schema types: object, array, string, integer, number, boolean, enum
- Nested objects (flattened to dot notation or kept as dicts)

### Not in MVP (extension points for future)
- OAuth2 / OpenID Connect
- Multipart / file uploads
- Pagination helpers
- Rate limiting
- Webhook generation
- Non-JSON content types

## [S4] Architecture

```
POST /connectors/generate
       │
       ▼
┌─────────────────────────┐
│  openapi_generator()    │
│                         │
│  1. Parse spec (YAML/   │
│     JSON)               │
│  2. Extract: servers,   │
│     paths, security     │
│  3. Resolve $ref        │
│  4. Generate code:      │
│     - Connector class   │
│     - __init__.py       │
│     - .example.yml      │
│  5. Write files         │
└─────────────────────────┘
       │
       ▼
  Files written to:
  soar/connectors/<name>/
```

## [S5] Generator Module Design

### `soar/tools/openapi.py`

```python
class OpenAPIGenerator:
    def __init__(self, spec: dict):
        self.spec = spec
        self.servers = spec.get("servers", [])
        self.paths = spec.get("paths", {})
        self.components = spec.get("components", {})
        self.security_schemes = self.components.get("securitySchemes", {})

    def generate(self, name: str, output_dir: Path) -> dict:
        """Generate connector files. Returns {files: [...], warnings: [...]}"""
        ...

    def _resolve_ref(self, ref: str) -> dict:
        """Resolve $ref pointer (e.g., #/components/schemas/User)"""
        ...

    def _extract_security(self) -> list[dict]:
        """Parse securitySchemes into auth config for __init__"""
        ...

    def _generate_class(self, name: str) -> str:
        """Generate connector .py source code"""
        ...

    def _generate_init(self, name: str) -> str:
        """Generate __init__.py"""
        ...

    def _generate_config(self, name: str) -> str:
        """Generate .example.yml from securitySchemes + servers"""
        ...

    def _method_name(self, path: str, method: str, operation: dict) -> str:
        """Derive method name from path + operationId or fallback"""
        ...

    def _param_signature(self, params: list[dict]) -> str:
        """Generate Python method signature from OpenAPI params"""
        ...
```

### Code Generation Strategy

Use f-strings (no Jinja2 dependency). Template is embedded in the generator:

```python
CONNECTOR_TEMPLATE = '''"""Auto-generated from OpenAPI spec: {title}"""
from __future__ import annotations
import httpx
from soar.connectors.base import BaseConnector


class {class_name}Connector(BaseConnector):
    """Connector for {title}"""

    def __init__(
        self,
        instance_name: str,
        base_url: str = "{base_url}",
        {security_params}**kwargs,
    ):
        super().__init__(instance_name, **kwargs)
        self.base_url = base_url
        {security_fields}
        self._client: httpx.Client | None = None

    def _connect_impl(self):
        headers = {{}}
        {auth_header_setup}
        self._client = httpx.Client(
            base_url=self.base_url,
            headers=headers,
            timeout=30.0,
        )

    def disconnect(self):
        if self._client:
            self._client.close()
            self._client = None
            self._connected = False

    {methods}
'''
```

### Auth Mapping

| OpenAPI `type` | `in` | Generated `__init__` param | Header setup |
|---|---|---|---|
| `apiKey` | `header` | `api_key: str = ""` | `headers["{name}"] = self.api_key` |
| `apiKey` | `query` | `api_key: str = ""` | Pass as query param per request |
| `http` | `bearer` | `token: str = ""` | `headers["Authorization"] = f"Bearer {{self.token}}"` |
| `http` | `basic` | `username: str = ""` / `password: str = ""` | `httpx.BasicAuth(self.username, self.password)` |

### Method Generation

For each `path` + `method` in the spec:

1. **Name**: Use `operationId` if present, else derive from `{method}_{path}` (e.g., `get_users_by_id`)
2. **Signature**: Path params first, then query params, then body
3. **Body**: If `requestBody` with `application/json`, add `body: dict | None = None`
4. **Implementation**: `self._client.{method}("{path}", params={query}, json=body)`
5. **Return**: `resp.raise_for_status(); return resp.json()`

### Method Name Derivation

```python
def _method_name(self, path: str, method: str, operation: dict) -> str:
    if "operationId" in operation:
        return operation["operationId"]
    # /users/{id}/posts -> get_users_by_id_posts
    parts = [p for p in path.split("/") if p]
    sanitized = []
    for p in parts:
        if p.startswith("{"):
            sanitized.append("by_" + p[1:-1])
        else:
            sanitized.append(p)
    return method.lower() + "_" + "_".join(sanitized)
```

## [S6] API Endpoint Design

### `POST /connectors/generate`

**Request:**
```json
{
  "spec": "<raw OpenAPI spec as JSON/YAML string>",
  "name": "my_api",
  "overwrite": false
}
```

**Response (success):**
```json
{
  "name": "my_api",
  "files": [
    "soar/connectors/my_api/my_api.py",
    "soar/connectors/my_api/__init__.py",
    "soar/connectors/my_api/my_api.example.yml"
  ],
  "warnings": [
    "OAuth2 auth detected — generated stub, requires manual implementation"
  ]
}
```

**Response (error):**
```json
{
  "detail": "Invalid OpenAPI spec: missing 'paths' section"
}
```

**Implementation in `orchestrator/api/connectors.py`:**

```python
@router.post("/connectors/generate")
async def generate_connector(request: Request, body: GenerateRequest):
    git_manager = request.app.state.git_manager
    spec = _parse_spec(body.spec)  # JSON or YAML
    generator = OpenAPIGenerator(spec)
    result = generator.generate(body.name, CONNECTORS_DIR)
    # git auto-commit
    for f in result["files"]:
        git_manager.add(str(f))
    git_manager.commit(f"Generated connector: {body.name}")
    return result
```

## [S7] File Layout

```
soar/
├── tools/
│   ├── __init__.py
│   └── openapi.py          # OpenAPIGenerator class
orchestrator/
├── api/
│   └── connectors.py       # POST /connectors/generate (add endpoint)
```

## [S8] Error Handling

| Error | Response |
|---|---|
| Invalid YAML/JSON | 400 "Invalid spec format" |
| Missing `openapi` version field | 400 "Not an OpenAPI 3.x spec" |
| Missing `paths` | 400 "No paths defined" |
| Directory already exists + `overwrite=false` | 409 "Connector already exists" |
| Unknown auth scheme (OAuth2) | 200 with warning, stub generated |
| $ref resolution failure | 400 "Cannot resolve $ref: {ref}" |

## [S9] Testing Strategy

- Unit tests for `OpenAPIGenerator` with sample specs (Petstore, minimal, complex)
- API integration test for `POST /connectors/generate`
- Generated code validation: import the generated module, check class exists, check method signatures
- Auth mapping tests: each scheme type

## [S10] Future Extension Points

- OAuth2 flow: add `_refresh_token()` method template
- Multipart: detect `multipart/form-data` in spec, generate file upload methods
- Pagination: detect `offset`/`cursor` params, generate iterator methods
- Rate limiting: read `x-rateLimit` extensions, add sleep logic
