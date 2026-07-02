import os

from fastapi import APIRouter, HTTPException, Request

from orchestrator.api.validation import validate_name, validate_path_within

router = APIRouter(prefix="/actions", tags=["actions"])

ACTION_TEMPLATE = '''from soar.connectors import connectors


def {name}({params}):
    """
    Action: {description}
    """
    # TODO: implement
    pass
'''


@router.get("")
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


@router.get("/template")
async def get_template(name: str = "my_action", description: str = "TODO", params: str = ""):
    return {"content": ACTION_TEMPLATE.format(name=name, description=description, params=params)}


@router.get("/{name}/code")
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


@router.get("/{name}")
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
async def save_action(name: str, request: Request):
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
    try:
        commit_hash = await git.commit(f"actions/{name}.py", f"Update action {name}")
    except RuntimeError as e:
        return {"status": "saved", "commit": "", "warning": str(e)}
    return {"status": "saved", "commit": commit_hash}


@router.delete("/{name}")
async def delete_action(name: str, request: Request):
    validate_name(name)
    config = request.app.state.config
    filepath = os.path.join(config.soar.actions_dir, f"{name}.py")
    validate_path_within(config.soar.actions_dir, filepath)
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="Action not found")
    os.remove(filepath)
    git = request.app.state.git
    try:
        commit_hash = await git.commit(f"actions/{name}.py", f"Delete action {name}")
    except RuntimeError as e:
        return {"status": "deleted", "commit": "", "warning": str(e)}
    return {"status": "deleted", "commit": commit_hash}
