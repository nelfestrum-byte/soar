import ipaddress
import json
import os
import re
from pathlib import Path
from urllib.parse import urlparse

import yaml as pyyaml
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from orchestrator.api.validation import validate_name, validate_path_within
from soar.tools.openapi import OpenAPIGenerator

router = APIRouter(prefix="/connectors", tags=["connectors"])


class GenerateRequest(BaseModel):
    spec: str
    name: str
    overwrite: bool = False


class PreviewRequest(BaseModel):
    spec: str

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


@router.post("/preview")
async def preview_spec(request: Request, body: PreviewRequest):
    # Parse spec
    try:
        spec = json.loads(body.spec)
    except json.JSONDecodeError:
        try:
            spec = pyyaml.safe_load(body.spec)
        except Exception as exc:
            raise HTTPException(status_code=400, detail="Invalid spec format") from exc

    if not isinstance(spec, dict):
        raise HTTPException(status_code=400, detail="Invalid spec format: must be a mapping")

    if "openapi" not in spec:
        raise HTTPException(status_code=400, detail="Not an OpenAPI spec: missing 'openapi' version")
    if "paths" not in spec:
        raise HTTPException(status_code=400, detail="Not an OpenAPI spec: missing 'paths' section")

    # Extract endpoints
    endpoints = []
    for path, path_item in spec.get("paths", {}).items():
        for method in ["get", "post", "put", "delete", "patch"]:
            if method in path_item:
                op = path_item[method]
                endpoints.append({
                    "method": method.upper(),
                    "path": path,
                    "operationId": op.get("operationId", ""),
                })

    # Extract auth
    auth = []
    security_schemes = spec.get("components", {}).get("securitySchemes", {})
    for name, scheme in security_schemes.items():
        auth.append({"type": scheme.get("type", ""), "name": name})

    # Extract servers
    servers = [s.get("url", "") for s in spec.get("servers", [])]

    return {
        "title": spec.get("info", {}).get("title", ""),
        "version": spec.get("info", {}).get("version", ""),
        "endpoints": endpoints,
        "auth": auth,
        "servers": servers,
    }


def _validate_external_url(url: str) -> None:
    """Block requests to internal/private IP ranges."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(status_code=400, detail="Only HTTP/HTTPS URLs allowed")
    hostname = parsed.hostname or ""
    try:
        ip = ipaddress.ip_address(hostname)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved:
            raise HTTPException(status_code=400, detail="Requests to internal IPs are not allowed")
    except ValueError:
        # hostname is a domain name, not an IP — check common internal names
        if hostname in ("localhost", "metadata.google.internal"):
            raise HTTPException(status_code=400, detail="Requests to internal hosts are not allowed")


@router.get("/preview")
async def preview_spec_url(url: str):
    _validate_external_url(url)
    import httpx
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            spec_text = resp.text
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Failed to fetch spec from URL: {exc}") from exc

    # Reuse POST preview logic
    body = PreviewRequest(spec=spec_text)
    return await preview_spec(Request, body)


@router.post("/generate")
async def generate_connector(request: Request, body: GenerateRequest):
    config = request.app.state.config
    connectors_dir = Path(config.soar.connectors_dir)

    # Parse spec (try JSON first, then YAML)
    try:
        spec = json.loads(body.spec)
    except json.JSONDecodeError:
        try:
            spec = pyyaml.safe_load(body.spec)
        except Exception as exc:
            raise HTTPException(status_code=400, detail="Invalid spec format: not valid JSON or YAML") from exc

    if not isinstance(spec, dict):
        raise HTTPException(status_code=400, detail="Invalid spec format: must be a mapping")

    # Validate and generate
    try:
        generator = OpenAPIGenerator(spec)
        result = generator.generate(body.name, connectors_dir)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Git auto-commit
    git = request.app.state.git
    try:
        for f in result["files"]:
            await git.commit(f, f"Generated connector: {body.name}")
    except RuntimeError:
        pass

    from orchestrator.main import load_workflow_metas
    job_manager = request.app.state.job_manager
    scheduler = request.app.state.scheduler
    workflows = load_workflow_metas(config)
    job_manager.set_metas(workflows)
    await scheduler.reload(workflows)

    return {"name": body.name, **result}


@router.get("/{name}")
async def get_connector(name: str, request: Request):
    validate_name(name)
    config = request.app.state.config
    connectors_dir = config.soar.connectors_dir
    dirpath = os.path.join(connectors_dir, name)
    validate_path_within(connectors_dir, dirpath)
    if not os.path.exists(dirpath) or not os.path.isdir(dirpath):
        raise HTTPException(status_code=404, detail="Connector not found")
    py_file = os.path.join(dirpath, f"{name}.py")
    yml_file = os.path.join(dirpath, f"{name}.yml")
    has_code = os.path.exists(py_file)
    has_config = os.path.exists(yml_file)
    class_name = ""
    if has_code:
        try:
            with open(py_file) as f:
                class_name = _parse_class_name(f.read())
        except Exception:
            pass
    return {
        "name": name,
        "class_name": class_name,
        "has_code": has_code,
        "has_config": has_config,
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
    try:
        content = body.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="Content must be valid UTF-8")
    if "\x00" in content:
        raise HTTPException(status_code=400, detail="Content must not contain null bytes")
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)
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
        # Look for .example.yml in connectors_dir (generated connectors)
        example_in_dir = os.path.join(config.soar.connectors_dir, name, f"{name}.example.yml")
        if os.path.exists(example_in_dir):
            with open(example_in_dir) as f:
                return {"name": name, "content": f.read()}
        # Fall back to builtin example
        builtin_dir = Path(__file__).resolve().parent.parent.parent / "soar" / "connectors"
        example = builtin_dir / name / f"{name}.example.yml"
        if example.exists():
            return {"name": name, "content": example.read_text()}
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
    try:
        content = body.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="Content must be valid UTF-8")
    if "\x00" in content:
        raise HTTPException(status_code=400, detail="Content must not contain null bytes")
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)
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
        class_name = "".join(w.capitalize() for w in name.split("_"))
        if not class_name.endswith("Connector"):
            class_name += "Connector"

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
