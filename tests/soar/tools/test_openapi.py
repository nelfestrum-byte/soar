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
