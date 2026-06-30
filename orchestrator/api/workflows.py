from fastapi import APIRouter, HTTPException, Request
from orchestrator.models.workflow_meta import WorkflowMeta
from orchestrator.models import ConcurrencyPolicy

router = APIRouter(prefix="/workflows", tags=["workflows"])


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
            "token": m.token,
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
        "token": meta.token,
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


def _save_state(config, metas: dict):
    import yaml
    from pathlib import Path

    state_path = Path(config.soar.workflows_dir).parent / "orchestrator_state.yaml"
    state = {"workflows": {}}
    for name, meta in metas.items():
        state["workflows"][name] = "enabled" if meta.enabled else "disabled"

    state_path.parent.mkdir(parents=True, exist_ok=True)
    with open(state_path, "w") as f:
        yaml.dump(state, f)
