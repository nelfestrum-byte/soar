import ast
import os
import re

from fastapi import HTTPException

SAFE_NAME_RE = re.compile(r"^[a-zA-Z0-9_\-]+$")
MAX_NAME_LEN = 100
MAX_BODY_SIZE = 5 * 1024 * 1024  # 5 MB

_WORKFLOW_BASES = {"BaseWorkflow", "ScheduledWorkflow", "WebhookWorkflow", "ManualWorkflow"}


def validate_name(name: str) -> str:
    if not name or len(name) > MAX_NAME_LEN:
        raise HTTPException(status_code=400, detail="Invalid name")
    if not SAFE_NAME_RE.match(name):
        raise HTTPException(status_code=400, detail="Name contains invalid characters")
    return name


def validate_path_within(base_dir: str, resolved: str) -> str:
    normed = os.path.normpath(resolved)
    base = os.path.normpath(base_dir)
    if not (normed == base or normed.startswith(base + os.sep)):
        raise HTTPException(status_code=403, detail="Access denied")
    return normed


def validate_commit(commit: str) -> str:
    if not re.match(r"^[0-9a-f]{4,40}$", commit):
        raise HTTPException(status_code=400, detail="Invalid commit hash")
    return commit


def _parse_or_422(code: str, filename: str) -> ast.Module:
    try:
        return ast.parse(code, filename=filename)
    except SyntaxError as e:
        raise HTTPException(status_code=422, detail=f"Syntax error: {e}") from e


def validate_workflow_code(code: str) -> None:
    tree = _parse_or_422(code, "workflow.py")
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.ClassDef):
            bases = {b.id for b in node.bases if isinstance(b, ast.Name)}
            if bases & _WORKFLOW_BASES:
                return
    raise HTTPException(
        status_code=422,
        detail="No class inheriting BaseWorkflow/ScheduledWorkflow/WebhookWorkflow/ManualWorkflow found",
    )


def validate_action_code(code: str, name: str) -> None:
    tree = _parse_or_422(code, f"{name}.py")
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return
    raise HTTPException(
        status_code=422,
        detail=f"No function named '{name}' found (ActionsRegistry looks up by filename)",
    )


def validate_connector_code(code: str) -> None:
    tree = _parse_or_422(code, "connector.py")
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.ClassDef):
            bases = {b.id for b in node.bases if isinstance(b, ast.Name)}
            if "BaseConnector" in bases:
                return
    raise HTTPException(status_code=422, detail="No class inheriting BaseConnector found")
