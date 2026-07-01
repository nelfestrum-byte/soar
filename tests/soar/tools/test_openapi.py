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
    assert "X-API-Key" in sec["params"]
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
