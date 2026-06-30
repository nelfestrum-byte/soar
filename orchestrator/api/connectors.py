import os
import re
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse
from orchestrator.api.validation import validate_name, validate_path_within

router = APIRouter(prefix="/connectors", tags=["connectors"])

CONNECTOR_TEMPLATE = '''from soar.connectors.base import BaseConnector


class {class_name}(BaseConnector):
    def __init__(self, instance_name: str, **kwargs):
        super().__init__(instance_name)
        # TODO: add parameters

    def _connect_impl(self):
        # TODO: implement connection
        self._connected = True

    def disconnect(self):
        self._connected = False
'''

CONFIG_TEMPLATE = '''instances:
  {name}:
    # TODO: add configuration
'''


def _parse_class_name(content: str) -> str:
    match = re.search(r"class\s+(\w+)\s*\(\s*BaseConnector\s*\)", content)
    return match.group(1) if match else "Unknown"


@router.get("")
async def list_connectors(request: Request):
    config = request.app.state.config
    connectors_dir = config.soar.connectors_dir
    if not os.path.exists(connectors_dir):
        return []
    result = []
    for entry in os.scandir(connectors_dir):
        if entry.name.startswith(("_", ".")):
            continue
        if entry.is_dir():
            py_file = os.path.join(entry.path, f"{entry.name}.py")
            yml_file = os.path.join(entry.path, f"{entry.name}.yml")
            has_code = os.path.exists(py_file)
            has_config = os.path.exists(yml_file)
            class_name = ""
            if has_code:
                try:
                    with open(py_file) as f:
                        class_name = _parse_class_name(f.read())
                except Exception:
                    pass
            result.append({
                "name": entry.name,
                "class_name": class_name,
                "has_code": has_code,
                "has_config": has_config,
            })
    return sorted(result, key=lambda x: x["name"])


@router.get("/template")
async def get_template(name: str = "my_connector", class_name: str = "MyConnector"):
    if not class_name.endswith("Connector"):
        class_name = class_name + "Connector"
    return {
        "code": CONNECTOR_TEMPLATE.format(class_name=class_name),
        "config": CONFIG_TEMPLATE.format(name=name),
    }


@router.get("/{name}/code")
async def get_connector_code(name: str, request: Request):
    validate_name(name)
    config = request.app.state.config
    filepath = os.path.join(config.soar.connectors_dir, name, f"{name}.py")
    validate_path_within(config.soar.connectors_dir, filepath)
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="Connector not found")
    with open(filepath) as f:
        content = f.read()
    return {"name": name, "content": content}


@router.put("/{name}/code")
async def save_connector_code(name: str, request: Request):
    validate_name(name)
    config = request.app.state.config
    dirpath = os.path.join(config.soar.connectors_dir, name)
    validate_path_within(config.soar.connectors_dir, dirpath)
    os.makedirs(dirpath, exist_ok=True)
    filepath = os.path.join(dirpath, f"{name}.py")
    body = await request.body()
    with open(filepath, "wb") as f:
        f.write(body)
    git = request.app.state.git
    try:
        commit_hash = await git.commit(f"connectors/{name}/{name}.py", f"Update connector {name}")
    except RuntimeError as e:
        return {"status": "saved", "commit": "", "warning": str(e)}
    return {"status": "saved", "commit": commit_hash}


@router.get("/{name}/config")
async def get_connector_config(name: str, request: Request):
    validate_name(name)
    config = request.app.state.config
    filepath = os.path.join(config.soar.connectors_dir, name, f"{name}.yml")
    validate_path_within(config.soar.connectors_dir, filepath)
    if not os.path.exists(filepath):
        return {"name": name, "content": ""}
    with open(filepath) as f:
        content = f.read()
    return {"name": name, "content": content}


@router.put("/{name}/config")
async def save_connector_config(name: str, request: Request):
    validate_name(name)
    config = request.app.state.config
    dirpath = os.path.join(config.soar.connectors_dir, name)
    validate_path_within(config.soar.connectors_dir, dirpath)
    os.makedirs(dirpath, exist_ok=True)
    filepath = os.path.join(dirpath, f"{name}.yml")
    body = await request.body()
    with open(filepath, "wb") as f:
        f.write(body)
    git = request.app.state.git
    try:
        commit_hash = await git.commit(f"connectors/{name}/{name}.yml", f"Update config {name}")
    except RuntimeError as e:
        return {"status": "saved", "commit": "", "warning": str(e)}
    return {"status": "saved", "commit": commit_hash}


@router.post("/{name}")
async def create_connector(name: str, request: Request, class_name: str = ""):
    validate_name(name)
    config = request.app.state.config
    dirpath = os.path.join(config.soar.connectors_dir, name)
    validate_path_within(config.soar.connectors_dir, dirpath)
    if os.path.exists(dirpath):
        raise HTTPException(status_code=409, detail="Connector already exists")
    os.makedirs(dirpath, exist_ok=True)

    if not class_name:
        class_name = "".join(w.capitalize() for w in name.split("_")) + "Connector"

    py_content = CONNECTOR_TEMPLATE.format(class_name=class_name)
    py_file = os.path.join(dirpath, f"{name}.py")
    with open(py_file, "w") as f:
        f.write(py_content)

    yml_content = CONFIG_TEMPLATE.format(name=name)
    yml_file = os.path.join(dirpath, f"{name}.yml")
    with open(yml_file, "w") as f:
        f.write(yml_content)

    init_file = os.path.join(dirpath, "__init__.py")
    with open(init_file, "w") as f:
        f.write("")

    git = request.app.state.git
    try:
        commit_hash = await git.commit(f"connectors/{name}/", f"Create connector {name}")
    except RuntimeError as e:
        return {"status": "created", "commit": "", "warning": str(e)}
    return {"status": "created", "commit": commit_hash}


@router.delete("/{name}")
async def delete_connector(name: str, request: Request):
    validate_name(name)
    config = request.app.state.config
    dirpath = os.path.join(config.soar.connectors_dir, name)
    validate_path_within(config.soar.connectors_dir, dirpath)
    if not os.path.exists(dirpath):
        raise HTTPException(status_code=404, detail="Connector not found")
    import shutil
    shutil.rmtree(dirpath)
    git = request.app.state.git
    try:
        commit_hash = await git.commit(f"connectors/{name}/", f"Delete connector {name}")
    except RuntimeError as e:
        return {"status": "deleted", "commit": "", "warning": str(e)}
    return {"status": "deleted", "commit": commit_hash}
