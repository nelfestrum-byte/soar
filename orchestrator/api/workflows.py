import os

from fastapi import APIRouter, HTTPException, Request

from orchestrator.api.validation import validate_name, validate_path_within

router = APIRouter(prefix="/workflows", tags=["workflows"])

SCHEDULED_TEMPLATE = '''from soar.workflows.base import ScheduledWorkflow
from soar.connectors import connectors


class {name}(ScheduledWorkflow):
    schedule = "*/10 * * * *"  # every 10 minutes

    def run(self, context):
        # TODO: implement
        return {{"status": "ok"}}
'''

WEBHOOK_TEMPLATE = '''from soar.workflows.base import WebhookWorkflow
from soar.connectors import connectors
from soar.logger import get_logger
import secrets

_log = get_logger("workflow.{name}")


class {name}(WebhookWorkflow):
    path = "/webhook/{path}"
    token = secrets.token_urlsafe(32)

    def run(self, context):
        payload = context.get("payload", {{}})
        _log.info(f"Received webhook: {{payload}}")
        # TODO: implement
        return {{"status": "ok", "payload": payload}}
'''

MANUAL_TEMPLATE = '''from soar.workflows.base import ManualWorkflow
from soar.connectors import connectors
from soar.logger import get_logger

_log = get_logger("workflow.{name}")


class {name}(ManualWorkflow):
    def run(self, context):
        _log.info(f"Running with context: {{context}}")
        # TODO: implement
        return {{"status": "ok"}}
'''

TEMPLATES = {
    "scheduled": SCHEDULED_TEMPLATE,
    "webhook": WEBHOOK_TEMPLATE,
    "manual": MANUAL_TEMPLATE,
}


@router.get("")
async def list_workflows(request: Request):
    job_manager = request.app.state.job_manager
    metas = job_manager._metas.values()
    return [
        {
            "name": m.name,
            "type": m.type,
            "enabled": m.enabled,
            "schedule": m.schedule,
            "interval": m.interval,
            "path": m.path,
            "timeout": m.timeout,
            "concurrency": m.concurrency.value,
        }
        for m in metas
    ]


@router.get("/{name}")
async def get_workflow(name: str, request: Request):
    job_manager = request.app.state.job_manager
    meta = job_manager._metas.get(name)
    if not meta:
        raise HTTPException(status_code=404, detail=f"Workflow '{name}' not found")
    return {
        "name": meta.name,
        "type": meta.type,
        "enabled": meta.enabled,
        "schedule": meta.schedule,
        "interval": meta.interval,
        "path": meta.path,
        "timeout": meta.timeout,
        "concurrency": meta.concurrency.value,
    }


@router.post("/{name}/enable")
async def enable_workflow(name: str, request: Request):
    job_manager = request.app.state.job_manager
    meta = job_manager._metas.get(name)
    if not meta:
        raise HTTPException(status_code=404, detail=f"Workflow '{name}' not found")
    meta.enabled = True
    _save_state(request.app.state.config, job_manager._metas)
    scheduler = request.app.state.scheduler
    await scheduler.reload(list(job_manager._metas.values()))
    return {"status": "enabled", "name": name}


@router.post("/{name}/disable")
async def disable_workflow(name: str, request: Request):
    job_manager = request.app.state.job_manager
    meta = job_manager._metas.get(name)
    if not meta:
        raise HTTPException(status_code=404, detail=f"Workflow '{name}' not found")
    meta.enabled = False
    _save_state(request.app.state.config, job_manager._metas)
    scheduler = request.app.state.scheduler
    await scheduler.reload(list(job_manager._metas.values()))
    return {"status": "disabled", "name": name}


@router.post("/reload")
async def reload_workflows(request: Request):
    from orchestrator.main import load_workflow_metas
    config = request.app.state.config
    job_manager = request.app.state.job_manager
    scheduler = request.app.state.scheduler

    workflows = load_workflow_metas(config)
    job_manager.set_metas(workflows)
    await scheduler.reload(workflows)

    return {"status": "reloaded", "count": len(workflows)}


@router.post("/scheduler/reload")
async def reload_scheduler(request: Request):
    scheduler = request.app.state.scheduler
    job_manager = request.app.state.job_manager
    await scheduler.reload(list(job_manager._metas.values()))
    return {"status": "reloaded"}


@router.get("/code/template")
async def get_workflow_template(name: str = "MyWorkflow", wf_type: str = "scheduled", path: str = "my-endpoint"):
    template = TEMPLATES.get(wf_type, SCHEDULED_TEMPLATE)
    return {"content": template.format(name=name, path=path)}


@router.get("/{name}/code")
async def get_workflow_code(name: str, request: Request):
    validate_name(name)
    config = request.app.state.config
    filepath = os.path.join(config.soar.workflows_dir, f"{name}.py")
    validate_path_within(config.soar.workflows_dir, filepath)
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="Workflow not found")
    with open(filepath) as f:
        content = f.read()
    return {"name": name, "content": content}


@router.put("/{name}/code")
async def save_workflow_code(name: str, request: Request):
    validate_name(name)
    config = request.app.state.config
    filepath = os.path.join(config.soar.workflows_dir, f"{name}.py")
    validate_path_within(config.soar.workflows_dir, filepath)
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    body = await request.body()
    with open(filepath, "wb") as f:
        f.write(body)
    git = request.app.state.git
    try:
        commit_hash = await git.commit(f"workflows/{name}.py", f"Update workflow {name}")
    except RuntimeError as e:
        return {"status": "saved", "commit": "", "warning": str(e)}
    return {"status": "saved", "commit": commit_hash}


@router.delete("/{name}/code")
async def delete_workflow_code(name: str, request: Request):
    validate_name(name)
    config = request.app.state.config
    filepath = os.path.join(config.soar.workflows_dir, f"{name}.py")
    validate_path_within(config.soar.workflows_dir, filepath)
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="Workflow not found")
    os.remove(filepath)
    git = request.app.state.git
    try:
        commit_hash = await git.commit(f"workflows/{name}.py", f"Delete workflow {name}")
    except RuntimeError as e:
        return {"status": "deleted", "commit": "", "warning": str(e)}
    return {"status": "deleted", "commit": commit_hash}


def _save_state(config, metas: dict):
    from pathlib import Path

    import yaml

    state_path = Path(config.soar.workflows_dir).parent / "orchestrator_state.yaml"
    state: dict = {"workflows": {}}
    for name, meta in metas.items():
        state["workflows"][name] = "enabled" if meta.enabled else "disabled"

    state_path.parent.mkdir(parents=True, exist_ok=True)
    with open(state_path, "w") as f:
        yaml.dump(state, f)
