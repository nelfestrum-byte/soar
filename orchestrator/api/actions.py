import os

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.api.validation import validate_name, validate_path_within
from orchestrator.audit import service as audit_service
from orchestrator.auth.dependencies import CurrentUser, require_role
from orchestrator.db.session import get_db

router = APIRouter(prefix="/actions", tags=["actions"])

_RO = ("viewer", "analyst", "service", "admin")
_ADMIN = ("admin",)

ACTION_TEMPLATE = '''from soar.connectors import connectors


def {name}({params}):
    """
    Action: {description}
    """
    # TODO: implement
    pass
'''


@router.get("", dependencies=[Depends(require_role(*_RO))])
async def list_actions(request: Request):
    config = request.app.state.config
    actions_dir = config.soar.actions_dir
    if not os.path.exists(actions_dir):
        return []
    result = []
    for entry in os.scandir(actions_dir):
        if entry.name.startswith(("_", ".")):
            continue
        if entry.name == "__init__.py":
            continue
        if entry.is_file() and entry.name.endswith(".py"):
            result.append(entry.name[:-3])
    return sorted(result)


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
