import io
import json
import os
import shutil
import zipfile
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse

router = APIRouter(prefix="/transfer", tags=["transfer"])


@router.post("/export")
async def export_entities(request: Request):
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
                        zf.write(yml_file, f"connectors/{entry.name}/config.yml")

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
    return StreamingResponse(
        buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.post("/import")
async def import_entities(request: Request, file: UploadFile):
    if not file.filename or not file.filename.endswith(".zip"):
        raise HTTPException(status_code=400, detail="File must be a .zip archive")

    config = request.app.state.config

    content = await file.read()
    buffer = io.BytesIO(content)

    conflicts = []
    imported: dict = {"connectors": [], "actions": [], "workflows": []}

    try:
        zf = zipfile.ZipFile(buffer, "r")
    except zipfile.BadZipFile as exc:
        raise HTTPException(status_code=400, detail="Invalid file: not a valid ZIP archive") from exc

    with zf:
        # Parse manifest
        if "manifest.json" not in zf.namelist():
            raise HTTPException(status_code=400, detail="Invalid archive: missing manifest.json")

        manifest = json.loads(zf.read("manifest.json"))

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

            config_path = f"connectors/{name}/config.yml"
            if config_path in zf.namelist():
                zf.extract(config_path, str(Path(workflows_dir).parent))
                extracted = os.path.join(str(Path(workflows_dir).parent), config_path)
                target = os.path.join(connector_dir, f"{name}.yml")
                shutil.move(extracted, target)

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
                imported["workflows"].append(name)

    # Reload workflows
    from orchestrator.main import load_workflow_metas
    job_manager = request.app.state.job_manager
    scheduler = request.app.state.scheduler
    workflows = load_workflow_metas(config)
    job_manager.set_metas(workflows)
    await scheduler.reload(workflows)

    return {
        "status": "imported",
        "imported": imported,
        "conflicts_overwritten": len(conflicts) if force else 0,
    }
