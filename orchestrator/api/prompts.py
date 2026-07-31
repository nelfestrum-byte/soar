from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.audit import service as audit_service
from orchestrator.auth.dependencies import CurrentUser, require_role
from orchestrator.db.session import get_db

router = APIRouter(prefix="/prompts", tags=["prompts"])
_RO = ("viewer", "analyst", "service", "admin", "agent")
_ADMIN = ("admin",)


class UserPromptRequest(BaseModel):
    content: str


@router.get("/system", dependencies=[Depends(require_role(*_RO))])
async def get_system_prompt(request: Request):
    path = Path(request.app.state.config.soar.system_prompt_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="System prompt not configured")
    return {"content": path.read_text(encoding="utf-8")}


def _user_prompt_path(config) -> Path:
    return Path(config.git.workflows_repo) / "prompts" / "user_prompt.md"


@router.get("/user", dependencies=[Depends(require_role(*_RO))])
async def get_user_prompt(request: Request):
    path = _user_prompt_path(request.app.state.config)
    if not path.exists():
        return {"content": None}
    return {"content": path.read_text(encoding="utf-8")}


@router.put("/user")
async def save_user_prompt(
    request: Request, body: UserPromptRequest,
    user: CurrentUser = Depends(require_role(*_ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    config = request.app.state.config
    path = _user_prompt_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body.content, encoding="utf-8")
    git = request.app.state.git
    author_name, author_email = audit_service.git_author(user)
    try:
        commit_hash = await git.commit(
            "prompts/user_prompt.md", "Update user prompt",
            author_name=author_name, author_email=author_email,
        )
    except RuntimeError as e:
        return {"status": "saved", "commit": "", "warning": str(e)}
    if commit_hash:
        await audit_service.record(
            db, user=user, action="prompt.update_user", resource_type="prompt",
            resource_id="user", request=request, detail={"commit": commit_hash},
        )
    return {"status": "saved", "commit": commit_hash}
