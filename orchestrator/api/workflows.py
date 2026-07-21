import os

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.api.validation import validate_name, validate_path_within
from orchestrator.audit import service as audit_service
from orchestrator.auth.dependencies import CurrentUser, require_role
from orchestrator.db.session import get_db

_RO = ("viewer", "analyst", "service", "admin")
_RW = ("analyst", "admin")
_ADMIN = ("admin",)

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


@router.get("", dependencies=[Depends(require_role(*_RO))])
async def list_workflows(request: Request):
    job_manager = request.app.state.job_manager
    metas = job_manager.list_metas()
    result = []
    for m in metas:
        item = {
            "name": m.name,
            "type": m.type,
            "enabled": m.enabled,
            "schedule": m.schedule,
            "interval": m.interval,
            "path": m.path,
            "timeout": m.timeout,
            "concurrency": m.concurrency.value,
        }
        if hasattr(m, "token") and m.token:
            item["token"] = m.token
        result.append(item)
    return result


@router.get("/{name}", dependencies=[Depends(require_role(*_RO))])
async def get_workflow(name: str, request: Request):
    job_manager = request.app.state.job_manager
    meta = job_manager.get_meta(name)
    if not meta:
        raise HTTPException(status_code=404, detail=f"Workflow '{name}' not found")
    result = {
        "name": meta.name,
        "type": meta.type,
        "enabled": meta.enabled,
        "schedule": meta.schedule,
        "interval": meta.interval,
        "path": meta.path,
        "timeout": meta.timeout,
        "concurrency": meta.concurrency.value,
    }
    if hasattr(meta, "token") and meta.token:
        result["token"] = meta.token
    return result


@router.post("/{name}/enable")
async def enable_workflow(
    name: str, request: Request,
    user: CurrentUser = Depends(require_role(*_RW)),
    db: AsyncSession = Depends(get_db),
):
    job_manager = request.app.state.job_manager
    meta = job_manager.get_meta(name)
    if not meta:
        raise HTTPException(status_code=404, detail=f"Workflow '{name}' not found")
    meta.enabled = True
    _save_state(request.app.state.config, job_manager.list_metas())
    scheduler = request.app.state.scheduler
    await scheduler.reload(job_manager.list_metas())
    await audit_service.record(
        db, user=user, action="workflow.enable",
        resource_type="workflow", resource_id=name, request=request,
    )
    return {"status": "enabled", "name": name}


@router.post("/{name}/disable")
async def disable_workflow(
    name: str, request: Request,
    user: CurrentUser = Depends(require_role(*_RW)),
    db: AsyncSession = Depends(get_db),
):
    job_manager = request.app.state.job_manager
    meta = job_manager.get_meta(name)
    if not meta:
        raise HTTPException(status_code=404, detail=f"Workflow '{name}' not found")
    meta.enabled = False
    _save_state(request.app.state.config, job_manager.list_metas())
    scheduler = request.app.state.scheduler
    await scheduler.reload(job_manager.list_metas())
    await audit_service.record(
        db, user=user, action="workflow.disable",
        resource_type="workflow", resource_id=name, request=request,
    )
    return {"status": "disabled", "name": name}


@router.post("/reload", dependencies=[Depends(require_role(*_RW))])
async def reload_workflows(request: Request):
    from orchestrator.main import load_workflow_metas
    config = request.app.state.config
    job_manager = request.app.state.job_manager
    scheduler = request.app.state.scheduler

    workflows = load_workflow_metas(config)
    job_manager.set_metas(workflows)
    await scheduler.reload(workflows)

    return {"status": "reloaded", "count": len(workflows)}


@router.post("/scheduler/reload", dependencies=[Depends(require_role(*_RW))])
async def reload_scheduler(request: Request):
    scheduler = request.app.state.scheduler
    job_manager = request.app.state.job_manager
    await scheduler.reload(job_manager.list_metas())
    return {"status": "reloaded"}


@router.get("/code/template", dependencies=[Depends(require_role(*_RO))])
async def get_workflow_template(name: str = "MyWorkflow", wf_type: str = "scheduled", path: str = "my-endpoint"):
    template = TEMPLATES.get(wf_type, SCHEDULED_TEMPLATE)
    result = {"content": template.format(name=name, path=path)}
    if wf_type != "webhook" and path != "my-endpoint":
        result["warning"] = "path parameter is only used for webhook workflows"
    return result


@router.get("/{name}/code", dependencies=[Depends(require_role(*_RO))])
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
async def save_workflow_code(
    name: str, request: Request,
    user: CurrentUser = Depends(require_role(*_ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    validate_name(name)
    config = request.app.state.config
    filepath = os.path.join(config.soar.workflows_dir, f"{name}.py")
    validate_path_within(config.soar.workflows_dir, filepath)
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
            f"workflows/{name}.py", f"Update workflow {name}",
            author_name=author_name, author_email=author_email,
        )
    except RuntimeError as e:
        return {"status": "saved", "commit": "", "warning": str(e)}

    from orchestrator.main import load_workflow_metas
    job_manager = request.app.state.job_manager
    scheduler = request.app.state.scheduler
    workflows = load_workflow_metas(config)
    job_manager.set_metas(workflows)
    await scheduler.reload(workflows)

    await audit_service.record(
        db, user=user, action="workflow.update", resource_type="workflow",
        resource_id=name, request=request, detail={"commit": commit_hash},
    )

    return {"status": "saved", "commit": commit_hash}


@router.delete("/{name}/code")
async def delete_workflow_code(
    name: str, request: Request,
    user: CurrentUser = Depends(require_role(*_ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    validate_name(name)
    config = request.app.state.config
    filepath = os.path.join(config.soar.workflows_dir, f"{name}.py")
    validate_path_within(config.soar.workflows_dir, filepath)
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="Workflow not found")
    os.remove(filepath)

    _remove_from_state(config, name)

    git = request.app.state.git
    author_name, author_email = audit_service.git_author(user)
    try:
        commit_hash = await git.commit(
            f"workflows/{name}.py", f"Delete workflow {name}",
            author_name=author_name, author_email=author_email,
        )
    except RuntimeError as e:
        return {"status": "deleted", "commit": "", "warning": str(e)}

    from orchestrator.main import load_workflow_metas
    job_manager = request.app.state.job_manager
    scheduler = request.app.state.scheduler
    workflows = load_workflow_metas(config)
    job_manager.set_metas(workflows)
    await scheduler.reload(workflows)

    await audit_service.record(
        db, user=user, action="workflow.delete", resource_type="workflow",
        resource_id=name, request=request, detail={"commit": commit_hash},
    )

    return {"status": "deleted", "commit": commit_hash}


def _remove_from_state(config, name: str):
    from pathlib import Path

    import yaml

    state_path = Path(config.soar.workflows_dir).parent / "orchestrator_state.yaml"
    if not state_path.exists():
        return
    with open(state_path) as f:
        state = yaml.safe_load(f) or {}
    workflows = state.get("workflows", {})
    if name in workflows:
        del workflows[name]
        state["workflows"] = workflows
        with open(state_path, "w") as f:
            yaml.dump(state, f)


def _save_state(config, metas: list):
    from pathlib import Path

    import yaml

    state_path = Path(config.soar.workflows_dir).parent / "orchestrator_state.yaml"
    state: dict = {"workflows": {}}
    for meta in metas:
        state["workflows"][meta.name] = "enabled" if meta.enabled else "disabled"

    state_path.parent.mkdir(parents=True, exist_ok=True)
    with open(state_path, "w") as f:
        yaml.dump(state, f)
