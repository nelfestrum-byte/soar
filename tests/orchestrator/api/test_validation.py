import os
import pytest
from fastapi import HTTPException
from orchestrator.api.validation import validate_name, validate_path_within, validate_commit


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
