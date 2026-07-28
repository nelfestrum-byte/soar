import io
import json
import os
import shutil
import zipfile
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.api.connectors import _hidden_fields_for, _redact_yaml
from orchestrator.api.validation import (
    validate_action_code,
    validate_connector_code,
    validate_name,
    validate_workflow_code,
)
from orchestrator.audit import service as audit_service
from orchestrator.auth.dependencies import CurrentUser, require_role
from orchestrator.db.session import get_db

router = APIRouter(prefix="/transfer", tags=["transfer"], dependencies=[Depends(require_role("admin"))])


@router.post("/export")
async def export_entities(
    request: Request,
    user: CurrentUser = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    config = request.app.state.config
    job_manager = request.app.state.job_manager

    buffer = io.BytesIO()
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")

    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        # Collect connectors
        connectors = []
        connectors_dir = config.soar.connectors_dir
        if os.path.exists(connectors_dir):
            for entry in os.scandir(connectors_dir):
                if entry.is_dir() and not entry.name.startswith(("_", ".")):
                    py_file = os.path.join(entry.path, f"{entry.name}.py")
                    yml_file = os.path.join(entry.path, f"{entry.name}.yml")
                    if os.path.exists(py_file):
                        zf.write(py_file, f"connectors/{entry.name}/code.py")
                        connectors.append(entry.name)
                    if os.path.exists(yml_file):
                        # P13 write-only secrets: export is a read path like any other,
                        # so it must mask hidden fields the same as GET /config does.
                        with open(yml_file, encoding="utf-8") as f:
                            yml_content = f.read()
                        hidden = _hidden_fields_for(config, entry.name)
                        zf.writestr(
                            f"connectors/{entry.name}/config.yml",
                            _redact_yaml(yml_content, hidden),
                        )

        # Collect actions
        actions = []
        actions_dir = config.soar.actions_dir
        if os.path.exists(actions_dir):
            for entry in os.scandir(actions_dir):
                if entry.is_file() and entry.name.endswith(".py") and entry.name != "__init__.py":
                    zf.write(entry.path, f"actions/{entry.name}")
                    actions.append(entry.name[:-3])

        # Collect workflows
        workflows = []
        workflows_dir = config.soar.workflows_dir
        if os.path.exists(workflows_dir):
            for entry in os.scandir(workflows_dir):
                if entry.is_file() and entry.name.endswith(".py") and entry.name != "__init__.py":
                    zf.write(entry.path, f"workflows/{entry.name}")
                    workflows.append(entry.name[:-3])

        # Collect state
        state: dict = {"workflows": {}}
        for name, meta in job_manager._metas.items():
            state["workflows"][name] = "enabled" if meta.enabled else "disabled"

        zf.writestr("state.yaml", json.dumps(state, indent=2))

        # Manifest
        manifest = {
            "version": "1.0",
            "created_at": timestamp,
            "connectors": connectors,
            "actions": actions,
            "workflows": workflows,
        }
        zf.writestr("manifest.json", json.dumps(manifest, indent=2))

    buffer.seek(0)
    filename = f"soar-export-{timestamp}.zip"
    await audit_service.record(
        db, user=user, action="transfer.export", resource_type="transfer",
        resource_id=filename, request=request,
        detail={"connectors": connectors, "actions": actions, "workflows": workflows},
    )
    return StreamingResponse(
        buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.post("/import")
async def import_entities(
    request: Request, file: UploadFile,
    user: CurrentUser = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    if not file.filename or not file.filename.endswith(".zip"):
        raise HTTPException(status_code=400, detail="File must be a .zip archive")

    config = request.app.state.config

    content = await file.read()
    buffer = io.BytesIO(content)

    conflicts = []
    imported: dict = {"connectors": [], "actions": [], "workflows": []}
    warnings: list[str] = []

    try:
        zf = zipfile.ZipFile(buffer, "r")
    except zipfile.BadZipFile as exc:
        raise HTTPException(status_code=400, detail="Invalid file: not a valid ZIP archive") from exc

    with zf:
        # Validate zip entries don't contain path traversal
        for entry in zf.namelist():
            if entry.startswith("/") or ".." in entry.split("/"):
                raise HTTPException(status_code=400, detail=f"Invalid archive entry: {entry}")

        # Parse manifest
        if "manifest.json" not in zf.namelist():
            raise HTTPException(status_code=400, detail="Invalid archive: missing manifest.json")

        manifest = json.loads(zf.read("manifest.json"))

        # Validate all names in manifest
        for key in ("connectors", "actions", "workflows"):
            for name in manifest.get(key, []):
                validate_name(name)

        # Check conflicts
        connectors_dir = config.soar.connectors_dir
        actions_dir = config.soar.actions_dir
        workflows_dir = config.soar.workflows_dir

        for name in manifest.get("connectors", []):
            connector_dir = os.path.join(connectors_dir, name)
            if os.path.exists(connector_dir):
                conflicts.append({"type": "connector", "name": name})

        for name in manifest.get("actions", []):
            action_file = os.path.join(actions_dir, f"{name}.py")
            if os.path.exists(action_file):
                conflicts.append({"type": "action", "name": name})

        for name in manifest.get("workflows", []):
            workflow_file = os.path.join(workflows_dir, f"{name}.py")
            if os.path.exists(workflow_file):
                conflicts.append({"type": "workflow", "name": name})

        # If conflicts and not confirmed, return them
        force = request.query_params.get("force", "false").lower() == "true"

        if conflicts and not force:
            return {
                "status": "conflicts",
                "conflicts": conflicts,
                "message": f"Found {len(conflicts)} conflicts. Send force=true to overwrite.",
            }

        # P1: validate every entity before writing anything to disk — one bad
        # file in the archive must not leave a partially-imported tree behind.
        for name in manifest.get("connectors", []):
            code_path = f"connectors/{name}/code.py"
            if code_path in zf.namelist():
                validate_connector_code(zf.read(code_path).decode("utf-8"))

        for name in manifest.get("actions", []):
            action_path = f"actions/{name}.py"
            if action_path in zf.namelist():
                validate_action_code(zf.read(action_path).decode("utf-8"), name)

        for name in manifest.get("workflows", []):
            workflow_path = f"workflows/{name}.py"
            if workflow_path in zf.namelist():
                validate_workflow_code(zf.read(workflow_path).decode("utf-8"))

        git = request.app.state.git
        author_name, author_email = audit_service.git_author(user)

        # Import connectors
        for name in manifest.get("connectors", []):
            connector_dir = os.path.join(connectors_dir, name)
            os.makedirs(connector_dir, exist_ok=True)

            code_path = f"connectors/{name}/code.py"
            if code_path in zf.namelist():
                zf.extract(code_path, str(Path(workflows_dir).parent))
                extracted = os.path.join(str(Path(workflows_dir).parent), code_path)
                target = os.path.join(connector_dir, f"{name}.py")
                shutil.move(extracted, target)
                try:
                    await git.commit(
                        f"connectors/{name}/{name}.py", f"Import connector {name}",
                        author_name=author_name, author_email=author_email,
                    )
                except RuntimeError as e:
                    warnings.append(str(e))

            config_path = f"connectors/{name}/config.yml"
            if config_path in zf.namelist():
                zf.extract(config_path, str(Path(workflows_dir).parent))
                extracted = os.path.join(str(Path(workflows_dir).parent), config_path)
                target = os.path.join(connector_dir, f"{name}.yml")
                shutil.move(extracted, target)
                try:
                    await git.commit(
                        f"connectors/{name}/{name}.yml", f"Import connector {name}",
                        author_name=author_name, author_email=author_email,
                    )
                except RuntimeError as e:
                    warnings.append(str(e))

            imported["connectors"].append(name)

        # Import actions
        for name in manifest.get("actions", []):
            action_path = f"actions/{name}.py"
            if action_path in zf.namelist():
                zf.extract(action_path, str(Path(workflows_dir).parent))
                extracted = os.path.join(str(Path(workflows_dir).parent), action_path)
                target = os.path.join(actions_dir, f"{name}.py")
                os.makedirs(os.path.dirname(target), exist_ok=True)
                shutil.move(extracted, target)
                try:
                    await git.commit(
                        f"actions/{name}.py", f"Import action {name}",
                        author_name=author_name, author_email=author_email,
                    )
                except RuntimeError as e:
                    warnings.append(str(e))
                imported["actions"].append(name)

        # Import workflows
        for name in manifest.get("workflows", []):
            workflow_path = f"workflows/{name}.py"
            if workflow_path in zf.namelist():
                zf.extract(workflow_path, str(Path(workflows_dir).parent))
                extracted = os.path.join(str(Path(workflows_dir).parent), workflow_path)
                target = os.path.join(workflows_dir, f"{name}.py")
                os.makedirs(os.path.dirname(target), exist_ok=True)
                shutil.move(extracted, target)
                try:
                    await git.commit(
                        f"workflows/{name}.py", f"Import workflow {name}",
                        author_name=author_name, author_email=author_email,
                    )
                except RuntimeError as e:
                    warnings.append(str(e))
                imported["workflows"].append(name)

    # Reload workflows
    from orchestrator.main import load_workflow_metas
    job_manager = request.app.state.job_manager
    scheduler = request.app.state.scheduler
    workflows = load_workflow_metas(config)
    job_manager.set_metas(workflows)
    await scheduler.reload(workflows)

    await audit_service.record(
        db, user=user, action="transfer.import", resource_type="transfer",
        resource_id=file.filename or "", request=request,
        detail={"imported": imported, "conflicts_overwritten": len(conflicts) if force else 0},
    )

    result = {
        "status": "imported",
        "imported": imported,
        "conflicts_overwritten": len(conflicts) if force else 0,
    }
    if warnings:
        result["warnings"] = warnings
    return result
