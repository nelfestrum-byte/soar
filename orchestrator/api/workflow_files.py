import os
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse
from orchestrator.api.validation import validate_name, validate_path_within

router = APIRouter(prefix="/workflow-files", tags=["workflow-files"])

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
    config = request.app.state.config
    workflows_dir = config.soar.workflows_dir
    if not os.path.exists(workflows_dir):
        return []
    result = []
    for entry in os.scandir(workflows_dir):
        if entry.name.startswith(("_", ".")):
            continue
        if entry.name in ("base.py", "__init__.py"):
            continue
        if entry.is_file() and entry.name.endswith(".py"):
            name = entry.name[:-3]
            try:
                with open(entry.path) as f:
                    content = f.read()
                wf_type = "manual"
                if "ScheduledWorkflow" in content:
                    wf_type = "scheduled"
                elif "WebhookWorkflow" in content:
                    wf_type = "webhook"
                class_name = ""
                for line in content.split("\n"):
                    if line.startswith("class ") and "(ScheduledWorkflow)" in line or "(WebhookWorkflow)" in line or "(ManualWorkflow)" in line:
                        class_name = line.split("class ")[1].split("(")[0].strip()
                        break
                result.append({"name": name, "type": wf_type, "class_name": class_name})
            except Exception:
                result.append({"name": name, "type": wf_type, "class_name": ""})
    return sorted(result, key=lambda x: x["name"])


@router.get("/template")
async def get_template(name: str = "MyWorkflow", wf_type: str = "scheduled", path: str = "my-endpoint"):
    template = TEMPLATES.get(wf_type, SCHEDULED_TEMPLATE)
    return {"content": template.format(name=name, path=path)}


@router.get("/{name}")
async def get_workflow_file(name: str, request: Request):
    validate_name(name)
    config = request.app.state.config
    filepath = os.path.join(config.soar.workflows_dir, f"{name}.py")
    validate_path_within(config.soar.workflows_dir, filepath)
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="Workflow not found")
    with open(filepath) as f:
        content = f.read()
    return {"name": name, "content": content}


@router.put("/{name}")
async def save_workflow_file(name: str, request: Request):
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


@router.delete("/{name}")
async def delete_workflow_file(name: str, request: Request):
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
