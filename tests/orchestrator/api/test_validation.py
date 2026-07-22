import os

import pytest
from fastapi import HTTPException

from orchestrator.api.validation import (
    validate_action_code,
    validate_commit,
    validate_connector_code,
    validate_name,
    validate_path_within,
    validate_workflow_code,
)


def test_validate_name_valid():
    assert validate_name("my-workflow") == "my-workflow"
    assert validate_name("test_123") == "test_123"
    assert validate_name("a") == "a"


def test_validate_name_empty():
    with pytest.raises(HTTPException) as exc_info:
        validate_name("")
    assert exc_info.value.status_code == 400


def test_validate_name_too_long():
    with pytest.raises(HTTPException):
        validate_name("a" * 101)


def test_validate_name_special_chars():
    with pytest.raises(HTTPException):
        validate_name("../etc/passwd")
    with pytest.raises(HTTPException):
        validate_name("name with spaces")
    with pytest.raises(HTTPException):
        validate_name("name\x00null")


def test_validate_path_within_ok():
    result = validate_path_within("/app/workflows", "/app/workflows/test.py")
    assert result == os.path.normpath("/app/workflows/test.py")


def test_validate_path_within_subdir():
    result = validate_path_within("/app/workflows", "/app/workflows/sub/dir/file.py")
    assert result == os.path.normpath("/app/workflows/sub/dir/file.py")


def test_validate_path_within_traversal():
    with pytest.raises(HTTPException) as exc_info:
        validate_path_within("/app/workflows", "/etc/passwd")
    assert exc_info.value.status_code == 403


def test_validate_path_within_dotdot():
    with pytest.raises(HTTPException):
        validate_path_within("/app/workflows", "/app/workflows/../etc/passwd")


def test_validate_commit_valid():
    assert validate_commit("abc1234") == "abc1234"
    assert validate_commit("0" * 40) == "0" * 40


def test_validate_commit_invalid():
    with pytest.raises(HTTPException):
        validate_commit("--all")
    with pytest.raises(HTTPException):
        validate_commit("xyz")
    with pytest.raises(HTTPException):
        validate_commit("abc")


def test_validate_workflow_code_syntax_error():
    with pytest.raises(HTTPException) as exc_info:
        validate_workflow_code("def broken(:\n    pass")
    assert exc_info.value.status_code == 422
    assert "Syntax error" in exc_info.value.detail


def test_validate_workflow_code_valid():
    validate_workflow_code(
        "from soar.workflows.base import ScheduledWorkflow\n\n\n"
        "class MyWorkflow(ScheduledWorkflow):\n"
        "    def run(self, context):\n        return {}\n"
    )


def test_validate_workflow_code_missing_base():
    with pytest.raises(HTTPException) as exc_info:
        validate_workflow_code("class NotAWorkflow:\n    pass\n")
    assert exc_info.value.status_code == 422


def test_validate_action_code_syntax_error():
    with pytest.raises(HTTPException) as exc_info:
        validate_action_code("def broken(:\n    pass", "my_action")
    assert exc_info.value.status_code == 422
    assert "Syntax error" in exc_info.value.detail


def test_validate_action_code_valid():
    validate_action_code("def my_action(context):\n    return {}\n", "my_action")


def test_validate_action_code_missing_function():
    with pytest.raises(HTTPException) as exc_info:
        validate_action_code("def other_name():\n    pass\n", "my_action")
    assert exc_info.value.status_code == 422


def test_validate_connector_code_syntax_error():
    with pytest.raises(HTTPException) as exc_info:
        validate_connector_code("def broken(:\n    pass")
    assert exc_info.value.status_code == 422
    assert "Syntax error" in exc_info.value.detail


def test_validate_connector_code_valid():
    validate_connector_code(
        "from soar.connectors.base import BaseConnector\n\n\n"
        "class MyConnector(BaseConnector):\n    pass\n"
    )


def test_validate_connector_code_missing_base():
    with pytest.raises(HTTPException) as exc_info:
        validate_connector_code("class NotAConnector:\n    pass\n")
    assert exc_info.value.status_code == 422
