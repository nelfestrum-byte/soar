import ipaddress
import json
import os
import re
import socket
from pathlib import Path
from urllib.parse import urlparse

import yaml as pyyaml
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.api.validation import (
    validate_commit,
    validate_connector_code,
    validate_name,
    validate_path_within,
)
from orchestrator.audit import service as audit_service
from orchestrator.auth.dependencies import CurrentUser, require_role
from orchestrator.core import history
from orchestrator.core.introspect import _summary, parse_classes
from orchestrator.db.session import get_db
from soar.tools.openapi import OpenAPIGenerator

router = APIRouter(prefix="/connectors", tags=["connectors"])

_RO = ("viewer", "analyst", "service", "admin", "agent")
_RW = ("analyst", "admin", "agent")
_ADMIN = ("admin", "agent")

_MASK = "********"
_DIFF_KV_RE = re.compile(r"^([+-])(\s*)([A-Za-z_][A-Za-z0-9_]*):\s*(.*)$")


class GenerateRequest(BaseModel):
    spec: str
    name: str
    overwrite: bool = False


class PreviewRequest(BaseModel):
    spec: str


class RestoreRequest(BaseModel):
    commit: str

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


def _describe_connector_summary(py_file: str, class_name: str) -> str:
    try:
        for cls in parse_classes(Path(py_file)):
            if cls["name"] == class_name:
                return _summary(cls["docstring"])
    except (SyntaxError, OSError):
        pass
    return ""


def _connector_py_path(config, name: str) -> Path:
    return Path(os.path.join(config.soar.connectors_dir, name, f"{name}.py"))


def _hidden_fields_for(config, name: str) -> set[str]:
    """Hidden field names declared on a connector's class, via AST — no import."""
    filepath = _connector_py_path(config, name)
    if not filepath.exists():
        return set()
    try:
        classes = parse_classes(filepath)
    except SyntaxError:
        return set()
    if not classes:
        return set()
    cls = next((c for c in classes if not c["name"].startswith("Base")), classes[0])
    return cls["hidden_fields"]


def _redact_yaml(content: str, hidden: set[str]) -> str:
    if not hidden or not content:
        return content
    try:
        data = pyyaml.safe_load(content)
    except pyyaml.YAMLError:
        return content
    if not isinstance(data, dict) or not isinstance(data.get("instances"), dict):
        return content
    for instance in data["instances"].values():
        if not isinstance(instance, dict):
            continue
        for key in hidden:
            if key in instance:
                instance[key] = _MASK
    return pyyaml.safe_dump(data, sort_keys=False)


def _redact_diff(diff: str, hidden: set[str]) -> str:
    """Line-by-line redaction: mask the value of a `key: value` diff line
    when `key` is hidden — the fact of the change stays visible, the value doesn't."""
    if not hidden or not diff:
        return diff
    out_lines = []
    for line in diff.split("\n"):
        if line.startswith("+++") or line.startswith("---"):
            out_lines.append(line)
            continue
        match = _DIFF_KV_RE.match(line)
        if match and match.group(3) in hidden:
            out_lines.append(f"{match.group(1)}{match.group(2)}{match.group(3)}: {_MASK}")
        else:
            out_lines.append(line)
    return "\n".join(out_lines)


def _merge_hidden_fields(filepath: str, content: str, hidden: set[str], user: CurrentUser) -> str:
    """Merge-on-write: a submitted `********` keeps the on-disk value; a real change
    to a hidden field requires the literal `admin` role (write-only secrets, field-level
    RBAC split, not endpoint-level — non-hidden fields are unaffected by this function)."""
    try:
        new_data = pyyaml.safe_load(content)
    except pyyaml.YAMLError:
        return content
    if not isinstance(new_data, dict) or not isinstance(new_data.get("instances"), dict):
        return content

    old_instances: dict = {}
    if os.path.exists(filepath):
        try:
            with open(filepath, encoding="utf-8") as f:
                old_data = pyyaml.safe_load(f.read())
            if isinstance(old_data, dict) and isinstance(old_data.get("instances"), dict):
                old_instances = old_data["instances"]
        except pyyaml.YAMLError:
            old_instances = {}

    changed = False
    for instance_id, instance in new_data["instances"].items():
        if not isinstance(instance, dict):
            continue
        old_instance = old_instances.get(instance_id)
        if not isinstance(old_instance, dict):
            old_instance = {}
        for key in hidden:
            if key not in instance:
                continue
            new_value = instance[key]
            if new_value == _MASK:
                changed = True
                if key in old_instance:
                    instance[key] = old_instance[key]
                else:
                    del instance[key]
            elif new_value != old_instance.get(key) and user.role != "admin":
                raise HTTPException(
                    status_code=403, detail="Only admin may set connector secret fields",
                )
    if not changed:
        return content
    return pyyaml.safe_dump(new_data, sort_keys=False)


@router.get("", dependencies=[Depends(require_role(*_RO))])
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
            summary = ""
            if has_code:
                try:
                    with open(py_file) as f:
                        class_name = _parse_class_name(f.read())
                except Exception:
                    pass
                summary = _describe_connector_summary(py_file, class_name)
            result.append({
                "name": entry.name,
                "class_name": class_name,
                "has_code": has_code,
                "has_config": has_config,
                "summary": summary,
            })
    return sorted(result, key=lambda x: x["name"])


@router.get("/template", dependencies=[Depends(require_role(*_RO))])
async def get_template(name: str = "my_connector", class_name: str = "MyConnector"):
    if not class_name.endswith("Connector"):
        class_name = class_name + "Connector"
    return {
        "code": CONNECTOR_TEMPLATE.format(class_name=class_name),
        "config": CONFIG_TEMPLATE.format(name=name),
    }


@router.post("/preview", dependencies=[Depends(require_role(*_RW))])
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


def _is_private_ip(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
        return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved
    except ValueError:
        return False


def _validate_external_url(url: str) -> None:
    """Block requests to internal/private IP ranges, including via DNS."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(status_code=400, detail="Only HTTP/HTTPS URLs allowed")
    hostname = parsed.hostname or ""
    try:
        # Direct IP literal: check immediately
        ip = ipaddress.ip_address(hostname)
        if _is_private_ip(str(ip)):
            raise HTTPException(status_code=400, detail="Requests to internal IPs are not allowed")
        return
    except ValueError:
        pass

    # B6: resolve hostname and check each returned address
    try:
        results = socket.getaddrinfo(hostname, None)
        for result in results:
            addr_ip = result[4][0]
            if _is_private_ip(addr_ip):
                raise HTTPException(status_code=400, detail="Requests to internal IPs are not allowed")
    except HTTPException:
        raise
    except OSError as e:
        raise HTTPException(status_code=400, detail="Could not resolve hostname") from e


@router.get("/preview", dependencies=[Depends(require_role(*_RW))])
async def preview_spec_url(url: str):
    _validate_external_url(url)
    import httpx
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=False) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            spec_text = resp.text
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Failed to fetch spec from URL: {exc}") from exc

    # Reuse POST preview logic
    body = PreviewRequest(spec=spec_text)
    return await preview_spec(Request, body)


@router.post("/generate")
async def generate_connector(
    request: Request, body: GenerateRequest,
    user: CurrentUser = Depends(require_role(*_ADMIN)),
    db: AsyncSession = Depends(get_db),
):
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
    author_name, author_email = audit_service.git_author(user)
    try:
        for f in result["files"]:
            await git.commit(
                f, f"Generated connector: {body.name}",
                author_name=author_name, author_email=author_email,
            )
    except RuntimeError:
        pass

    from orchestrator.main import load_workflow_metas
    job_manager = request.app.state.job_manager
    scheduler = request.app.state.scheduler
    workflows = load_workflow_metas(config)
    job_manager.set_metas(workflows)
    await scheduler.reload(workflows)

    await audit_service.record(
        db, user=user, action="connector.generate", resource_type="connector",
        resource_id=body.name, request=request, detail={"files": result["files"]},
    )

    return {"name": body.name, **result}


@router.get("/{name}/describe", dependencies=[Depends(require_role(*_RO))])
async def describe_connector(name: str, request: Request):
    validate_name(name)
    config = request.app.state.config
    filepath = os.path.join(config.soar.connectors_dir, name, f"{name}.py")
    validate_path_within(config.soar.connectors_dir, filepath)
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="Connector not found")
    classes = parse_classes(Path(filepath))
    class_name = _parse_class_name(Path(filepath).read_text(encoding="utf-8"))
    for cls in classes:
        if cls["name"] == class_name:
            return {**cls, "module": name}
    raise HTTPException(status_code=404, detail=f"No class '{class_name}' found in {name}.py")


@router.get("/{name}/schema", dependencies=[Depends(require_role(*_RO))])
async def get_connector_schema(name: str, request: Request):
    validate_name(name)
    config = request.app.state.config
    filepath = _connector_py_path(config, name)
    validate_path_within(config.soar.connectors_dir, str(filepath))
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="Connector not found")
    classes = parse_classes(filepath)
    if not classes:
        return {"fields": []}
    cls = next((c for c in classes if not c["name"].startswith("Base")), classes[0])
    hidden = cls["hidden_fields"]
    return {"fields": [{**f, "hidden": f["name"] in hidden} for f in cls["fields"]]}


@router.get("/{name}", dependencies=[Depends(require_role(*_RO))])
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
    summary = ""
    if has_code:
        try:
            with open(py_file) as f:
                class_name = _parse_class_name(f.read())
        except Exception:
            pass
        summary = _describe_connector_summary(py_file, class_name)
    return {
        "name": name,
        "class_name": class_name,
        "has_code": has_code,
        "has_config": has_config,
        "summary": summary,
    }


@router.get("/{name}/code", dependencies=[Depends(require_role(*_RO))])
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


@router.get("/{name}/code/history", dependencies=[Depends(require_role(*_RO))])
async def get_connector_code_history(name: str, request: Request):
    validate_name(name)
    git = request.app.state.git
    return await history.list_history(git, f"connectors/{name}/{name}.py")


@router.get("/{name}/code/history/{commit}", dependencies=[Depends(require_role(*_RO))])
async def get_connector_code_version(name: str, commit: str, request: Request):
    validate_name(name)
    validate_commit(commit)
    git = request.app.state.git
    content = await history.get_version(git, f"connectors/{name}/{name}.py", commit)
    return {"content": content}


@router.get("/{name}/code/diff", dependencies=[Depends(require_role(*_RO))])
async def get_connector_code_diff(name: str, request: Request, a: str, b: str):
    validate_name(name)
    validate_commit(a)
    validate_commit(b)
    git = request.app.state.git
    diff = await history.diff_versions(git, f"connectors/{name}/{name}.py", a, b)
    return {"diff": diff}


@router.post("/{name}/code/restore")
async def restore_connector_code(
    name: str, request: Request, body: RestoreRequest,
    user: CurrentUser = Depends(require_role(*_ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    validate_name(name)
    validate_commit(body.commit)
    git = request.app.state.git
    author_name, author_email = audit_service.git_author(user)
    await history.restore_version(
        git, f"connectors/{name}/{name}.py", body.commit, author_name, author_email,
    )
    await audit_service.record(
        db, user=user, action="connector.restore_code", resource_type="connector",
        resource_id=name, request=request, detail={"commit": body.commit},
    )
    return {"status": "restored", "commit": body.commit}


@router.put("/{name}/code")
async def save_connector_code(
    name: str, request: Request,
    user: CurrentUser = Depends(require_role(*_ADMIN)),
    db: AsyncSession = Depends(get_db),
):
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
    validate_connector_code(content)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)
    git = request.app.state.git
    author_name, author_email = audit_service.git_author(user)
    try:
        commit_hash = await git.commit(
            f"connectors/{name}/{name}.py", f"Update connector {name}",
            author_name=author_name, author_email=author_email,
        )
    except RuntimeError as e:
        return {"status": "saved", "commit": "", "warning": str(e)}
    await audit_service.record(
        db, user=user, action="connector.update_code", resource_type="connector",
        resource_id=name, request=request, detail={"commit": commit_hash},
    )
    return {"status": "saved", "commit": commit_hash}


@router.get("/{name}/config", dependencies=[Depends(require_role(*_RO))])
async def get_connector_config(name: str, request: Request):
    validate_name(name)
    config = request.app.state.config
    filepath = os.path.join(config.soar.connectors_dir, name, f"{name}.yml")
    validate_path_within(config.soar.connectors_dir, filepath)
    hidden = _hidden_fields_for(config, name)
    if not os.path.exists(filepath):
        # Look for .example.yml in connectors_dir (generated connectors)
        example_in_dir = os.path.join(config.soar.connectors_dir, name, f"{name}.example.yml")
        if os.path.exists(example_in_dir):
            with open(example_in_dir) as f:
                return {"name": name, "content": _redact_yaml(f.read(), hidden)}
        # Fall back to builtin example
        builtin_dir = Path(__file__).resolve().parent.parent.parent / "soar" / "connectors"
        example = builtin_dir / name / f"{name}.example.yml"
        if example.exists():
            return {"name": name, "content": _redact_yaml(example.read_text(), hidden)}
        return {"name": name, "content": ""}
    with open(filepath) as f:
        content = f.read()
    return {"name": name, "content": _redact_yaml(content, hidden)}


@router.get("/{name}/config/history", dependencies=[Depends(require_role(*_RO))])
async def get_connector_config_history(name: str, request: Request):
    validate_name(name)
    git = request.app.state.git
    return await history.list_history(git, f"connectors/{name}/{name}.yml")


@router.get("/{name}/config/history/{commit}", dependencies=[Depends(require_role(*_RO))])
async def get_connector_config_version(name: str, commit: str, request: Request):
    validate_name(name)
    validate_commit(commit)
    config = request.app.state.config
    git = request.app.state.git
    content = await history.get_version(git, f"connectors/{name}/{name}.yml", commit)
    hidden = _hidden_fields_for(config, name)
    return {"content": _redact_yaml(content, hidden)}


@router.get("/{name}/config/diff", dependencies=[Depends(require_role(*_RO))])
async def get_connector_config_diff(name: str, request: Request, a: str, b: str):
    validate_name(name)
    validate_commit(a)
    validate_commit(b)
    config = request.app.state.config
    git = request.app.state.git
    diff = await history.diff_versions(git, f"connectors/{name}/{name}.yml", a, b)
    hidden = _hidden_fields_for(config, name)
    return {"diff": _redact_diff(diff, hidden)}


@router.post("/{name}/config/restore")
async def restore_connector_config(
    name: str, request: Request, body: RestoreRequest,
    user: CurrentUser = Depends(require_role(*_ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    validate_name(name)
    validate_commit(body.commit)
    git = request.app.state.git
    author_name, author_email = audit_service.git_author(user)
    await history.restore_version(
        git, f"connectors/{name}/{name}.yml", body.commit, author_name, author_email,
    )
    await audit_service.record(
        db, user=user, action="connector.restore_config", resource_type="connector",
        resource_id=name, request=request, detail={"commit": body.commit},
    )
    return {"status": "restored", "commit": body.commit}


@router.put("/{name}/config")
async def save_connector_config(
    name: str, request: Request,
    user: CurrentUser = Depends(require_role(*_ADMIN)),
    db: AsyncSession = Depends(get_db),
):
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
    hidden = _hidden_fields_for(config, name)
    if hidden:
        content = _merge_hidden_fields(filepath, content, hidden, user)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)
    git = request.app.state.git
    author_name, author_email = audit_service.git_author(user)
    try:
        commit_hash = await git.commit(
            f"connectors/{name}/{name}.yml", f"Update config {name}",
            author_name=author_name, author_email=author_email,
        )
    except RuntimeError as e:
        return {"status": "saved", "commit": "", "warning": str(e)}
    await audit_service.record(
        db, user=user, action="connector.update_config", resource_type="connector",
        resource_id=name, request=request, detail={"commit": commit_hash},
    )
    return {"status": "saved", "commit": commit_hash}


@router.post("/{name}")
async def create_connector(
    name: str, request: Request, class_name: str = "",
    user: CurrentUser = Depends(require_role(*_ADMIN)),
    db: AsyncSession = Depends(get_db),
):
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
    author_name, author_email = audit_service.git_author(user)
    try:
        commit_hash = await git.commit(
            f"connectors/{name}/", f"Create connector {name}",
            author_name=author_name, author_email=author_email,
        )
    except RuntimeError as e:
        return {"status": "created", "commit": "", "warning": str(e)}
    await audit_service.record(
        db, user=user, action="connector.create", resource_type="connector",
        resource_id=name, request=request, detail={"commit": commit_hash},
    )
    return {"status": "created", "commit": commit_hash}


@router.delete("/{name}")
async def delete_connector(
    name: str, request: Request,
    user: CurrentUser = Depends(require_role(*_ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    validate_name(name)
    config = request.app.state.config
    dirpath = os.path.join(config.soar.connectors_dir, name)
    validate_path_within(config.soar.connectors_dir, dirpath)
    if not os.path.exists(dirpath):
        raise HTTPException(status_code=404, detail="Connector not found")
    import shutil
    shutil.rmtree(dirpath)
    git = request.app.state.git
    author_name, author_email = audit_service.git_author(user)
    try:
        commit_hash = await git.commit(
            f"connectors/{name}/", f"Delete connector {name}",
            author_name=author_name, author_email=author_email,
        )
    except RuntimeError as e:
        return {"status": "deleted", "commit": "", "warning": str(e)}
    await audit_service.record(
        db, user=user, action="connector.delete", resource_type="connector",
        resource_id=name, request=request, detail={"commit": commit_hash},
    )
    return {"status": "deleted", "commit": commit_hash}
