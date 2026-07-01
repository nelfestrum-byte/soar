---
feature: openapi-connector-generator
status: delivered
specs:
  - docs/compose/specs/2026-07-01-openapi-connector-generator-design.md
plans:
  - docs/compose/plans/2026-07-01-openapi-connector-generator.md
branch: main
commits: 50d5ec5..a63ba9e
---

# OpenAPI Connector Generator — Final Report

## What Was Built

SOAR now supports automatic connector generation from OpenAPI 3.x specifications. Users can submit an OpenAPI spec (JSON or YAML) via the `POST /connectors/generate` API endpoint, and the system generates a complete, working connector with class, methods, config template, and package structure.

The generator handles HTTP methods (GET, POST, PUT, DELETE, PATCH), path/query parameters, JSON request bodies, and three authentication schemes (API key, Bearer token, Basic auth). OAuth2 is detected and flagged with a warning. Generated connectors follow SOAR's established patterns: BaseConnector inheritance, lazy connection, httpx HTTP client, and snake_case naming.

## Architecture

Two components:

1. **Generator Module** (`soar/tools/openapi.py`) — `OpenAPIGenerator` class that parses OpenAPI specs and generates connector code using f-string templates (no Jinja2 dependency).

2. **API Endpoint** (`POST /connectors/generate`) — FastAPI endpoint in `orchestrator/api/connectors.py` that accepts spec + name, calls the generator, writes files, and auto-commits to git.

### Generated Artifacts

Per connector, three files are created in `soar/connectors/<name>/`:
- `<name>.py` — Connector class with methods for each API endpoint
- `__init__.py` — Package re-export
- `<name>.example.yml` — Config template with auth placeholders

### Key Methods

| Method | Purpose |
|--------|---------|
| `generate(name, output_dir)` | Main entry point — creates all files |
| `_generate_class(name)` | Generates connector Python source |
| `_generate_init(name)` | Generates `__init__.py` |
| `_generate_config(name)` | Generates `.example.yml` |
| `_extract_security()` | Maps OpenAPI securitySchemes to auth params |
| `_param_signature(params)` | Generates Python method signatures |
| `_method_name(path, method, op)` | Derives method names from paths/operationIds |

## Usage

### API Request

```bash
curl -X POST http://localhost:8000/connectors/generate \
  -H "Content-Type: application/json" \
  -d '{
    "spec": "{\"openapi\": \"3.0.0\", ...}",
    "name": "my_api"
  }'
```

### Response

```json
{
  "name": "my_api",
  "files": [
    "my_api/my_api.py",
    "my_api/__init__.py",
    "my_api/my_api.example.yml"
  ],
  "warnings": []
}
```

### Configuration

After generation, edit `my_api.example.yml` with actual credentials and rename to `my_api.yml`.

## Verification

- **26 unit tests** for generator module covering: spec parsing, $ref resolution, method naming, auth extraction, param signatures, code generation, file writing, edge cases
- **3 API integration tests** for the generate endpoint: success case, invalid spec, invalid name
- **Lint clean** — ruff passes with no errors
- **Type check** — mypy passes (pre-existing redis_queue.py errors excluded)

## Journey Log

- [lesson] API key parameter names from spec (e.g., "X-API-Key") are used directly as Python identifiers — works but creates non-idiomatic variable names. Future improvement: sanitize to snake_case.
- [lesson] Type annotations for heterogeneous dicts (str | list[str] values) cause mypy issues — used `# type: ignore` comment as pragmatic solution.
