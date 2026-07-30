import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.api.validation import (
    validate_action_code,
    validate_commit,
    validate_name,
    validate_path_within,
)
from orchestrator.audit import service as audit_service
from orchestrator.auth.dependencies import CurrentUser, require_role
from orchestrator.core import history
from orchestrator.core.introspect import _summary, parse_functions
from orchestrator.db.session import get_db

router = APIRouter(prefix="/actions", tags=["actions"])

_RO = ("viewer", "analyst", "service", "admin", "agent")
_ADMIN = ("admin", "agent")


class RestoreRequest(BaseModel):
    commit: str

# from soar.connectors.<type> import <instance> — concept form (returns a
# ConnectorProxy, see docs/concepts/ENTITY-MODEL.md decision 4). The
# template can't know which connector type/instance this installation has
# configured, so it shows the pattern as a comment; `from soar.connectors
# import connectors` + `connectors.<instance>` (flat lookup, also proxied)
# still works for the same reason.
ACTION_TEMPLATE = '''# from soar.connectors.<type> import <instance>
from soar.connectors import connectors


def {name}({params}):
    """
    Action: {description}
    """
    # TODO: implement
    pass
'''


@router.get("", dependencies=[Depends(require_role(*_RO))])
async def list_actions(request: Request):
    """AST-only — never imports actions_dir content. After Phase 1's runtime
    boundary the orchestrator process is not allowed to import user code at
    all (that's exclusively soar.runner's job, in the content venv); the
    real multi-export ActionsRegistry (soar/actions/__init__.py) is used
    only inside soar.runner. Lists every public top-level function per file
    (E7), not just the one matching the filename — "file" tells the UI
    which file to open to edit it."""
    config = request.app.state.config
    actions_dir = config.soar.actions_dir
    if not os.path.exists(actions_dir):
        return []
    result = []
    for entry in sorted(os.scandir(actions_dir), key=lambda e: e.name):
        if entry.name.startswith(("_", ".")) or not entry.name.endswith(".py"):
            continue
        if not entry.is_file():
            continue
        try:
            fns = parse_functions(Path(actions_dir) / entry.name)
        except (SyntaxError, OSError):
            continue
        for fn in fns:
            result.append({
                "name": fn["name"],
                "file": entry.name[:-3],
                "summary": _summary(fn["docstring"]),
            })
    return result


@router.get("/template", dependencies=[Depends(require_role(*_RO))])
async def get_template(name: str = "my_action", description: str = "TODO", params: str = ""):
    return {"content": ACTION_TEMPLATE.format(name=name, description=description, params=params)}


@router.get("/{name}/code", dependencies=[Depends(require_role(*_RO))])
async def get_action_code(name: str, request: Request):
    validate_name(name)
    config = request.app.state.config
    filepath = os.path.join(config.soar.actions_dir, f"{name}.py")
    validate_path_within(config.soar.actions_dir, filepath)
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="Action not found")
    with open(filepath) as f:
        content = f.read()
    return {"name": name, "content": content}


@router.get("/{name}/describe", dependencies=[Depends(require_role(*_RO))])
async def describe_action(name: str, request: Request):
    validate_name(name)
    config = request.app.state.config
    filepath = os.path.join(config.soar.actions_dir, f"{name}.py")
    validate_path_within(config.soar.actions_dir, filepath)
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="Action not found")
    for fn in parse_functions(Path(filepath)):
        if fn["name"] == name:
            return {**fn, "module": name}
    raise HTTPException(status_code=404, detail=f"No function named '{name}' found in {name}.py")


@router.get("/{name}", dependencies=[Depends(require_role(*_RO))])
async def get_action(name: str, request: Request):
    validate_name(name)
    config = request.app.state.config
    filepath = os.path.join(config.soar.actions_dir, f"{name}.py")
    validate_path_within(config.soar.actions_dir, filepath)
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="Action not found")
    with open(filepath) as f:
        content = f.read()
    return {"name": name, "content": content}


@router.get("/{name}/history", dependencies=[Depends(require_role(*_RO))])
async def get_action_history(name: str, request: Request):
    validate_name(name)
    git = request.app.state.git
    return await history.list_history(git, f"actions/{name}.py")


@router.get("/{name}/history/{commit}", dependencies=[Depends(require_role(*_RO))])
async def get_action_version(name: str, commit: str, request: Request):
    validate_name(name)
    validate_commit(commit)
    git = request.app.state.git
    content = await history.get_version(git, f"actions/{name}.py", commit)
    return {"content": content}


@router.get("/{name}/diff", dependencies=[Depends(require_role(*_RO))])
async def get_action_diff(name: str, request: Request, a: str, b: str):
    validate_name(name)
    validate_commit(a)
    validate_commit(b)
    git = request.app.state.git
    diff = await history.diff_versions(git, f"actions/{name}.py", a, b)
    return {"diff": diff}


@router.post("/{name}/restore")
async def restore_action(
    name: str, request: Request, body: RestoreRequest,
    user: CurrentUser = Depends(require_role(*_ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    validate_name(name)
    validate_commit(body.commit)
    git = request.app.state.git
    author_name, author_email = audit_service.git_author(user)
    await history.restore_version(git, f"actions/{name}.py", body.commit, author_name, author_email)
    await audit_service.record(
        db, user=user, action="action.restore", resource_type="action",
        resource_id=name, request=request, detail={"commit": body.commit},
    )
    return {"status": "restored", "commit": body.commit}


@router.put("/{name}")
async def save_action(
    name: str, request: Request,
    user: CurrentUser = Depends(require_role(*_ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    validate_name(name)
    config = request.app.state.config
    filepath = os.path.join(config.soar.actions_dir, f"{name}.py")
    validate_path_within(config.soar.actions_dir, filepath)
    os.makedirs(os.path.dirname(filepath), exist_ok=True)

    raw = await request.body()
    try:
        import json
        body = json.loads(raw)
        code = body.get("code", "")
    except (json.JSONDecodeError, ValueError):
        code = raw.decode("utf-8")

    if not code.strip():
        raise HTTPException(status_code=422, detail="Code must not be empty")
    validate_action_code(code, name)

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(code)
    git = request.app.state.git
    author_name, author_email = audit_service.git_author(user)
    try:
        commit_hash = await git.commit(
            f"actions/{name}.py", f"Update action {name}",
            author_name=author_name, author_email=author_email,
        )
    except RuntimeError as e:
        return {"status": "saved", "commit": "", "warning": str(e)}
    await audit_service.record(
        db, user=user, action="action.update", resource_type="action",
        resource_id=name, request=request, detail={"commit": commit_hash},
    )
    return {"status": "saved", "commit": commit_hash}


@router.delete("/{name}")
async def delete_action(
    name: str, request: Request,
    user: CurrentUser = Depends(require_role(*_ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    validate_name(name)
    config = request.app.state.config
    filepath = os.path.join(config.soar.actions_dir, f"{name}.py")
    validate_path_within(config.soar.actions_dir, filepath)
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="Action not found")
    os.remove(filepath)
    git = request.app.state.git
    author_name, author_email = audit_service.git_author(user)
    try:
        commit_hash = await git.commit(
            f"actions/{name}.py", f"Delete action {name}",
            author_name=author_name, author_email=author_email,
        )
    except RuntimeError as e:
        return {"status": "deleted", "commit": "", "warning": str(e)}
    await audit_service.record(
        db, user=user, action="action.delete", resource_type="action",
        resource_id=name, request=request, detail={"commit": commit_hash},
    )
    return {"status": "deleted", "commit": commit_hash}
