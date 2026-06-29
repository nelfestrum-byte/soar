import os
from fastapi import APIRouter, HTTPException, Request, UploadFile, File
from fastapi.responses import PlainTextResponse

router = APIRouter(prefix="/files", tags=["files"])


@router.get("")
async def list_files(request: Request):
    config = request.app.state.config
    dirs = [config.soar.workflows_dir, config.soar.connectors_dir, config.soar.actions_dir]
    tree = {}
    for d in dirs:
        if os.path.exists(d):
            tree[os.path.basename(d)] = _scan_dir(d)
    return tree


@router.get("/{path:path}")
async def get_file(path: str, request: Request):
    full_path = _resolve_path(path, request.app.state.config)
    if not os.path.exists(full_path):
        raise HTTPException(status_code=404, detail="File not found")
    with open(full_path) as f:
        content = f.read()
    return PlainTextResponse(content)


@router.put("/{path:path}")
async def save_file(path: str, request: Request):
    full_path = _resolve_path(path, request.app.state.config)
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    body = await request.body()
    with open(full_path, "wb") as f:
        f.write(body)

    git = request.app.state.git
    commit_hash = await git.commit(path, f"Update {path}")
    return {"status": "saved", "commit": commit_hash}


@router.post("/upload")
async def upload_file(request: Request, file: UploadFile = File(...), path: str = ""):
    config = request.app.state.config
    allowed_bases = [
        config.soar.workflows_dir,
        config.soar.connectors_dir,
        config.soar.actions_dir,
    ]
    target = None
    for base in allowed_bases:
        candidate = os.path.join(base, path, file.filename)
        if candidate.startswith(os.path.normpath(base)):
            target = candidate
            break
    if target is None:
        raise HTTPException(status_code=400, detail="Invalid path")

    os.makedirs(os.path.dirname(target), exist_ok=True)
    content = await file.read()
    with open(target, "wb") as f:
        f.write(content)

    git = request.app.state.git
    rel_path = os.path.relpath(target, config.git.workflows_repo)
    commit_hash = await git.commit(rel_path, f"Upload {file.filename}")
    return {"status": "uploaded", "commit": commit_hash}


@router.delete("/{path:path}")
async def delete_file(path: str, request: Request):
    full_path = _resolve_path(path, request.app.state.config)
    if not os.path.exists(full_path):
        raise HTTPException(status_code=404, detail="File not found")
    os.remove(full_path)

    git = request.app.state.git
    commit_hash = await git.commit(path, f"Delete {path}")
    return {"status": "deleted", "commit": commit_hash}


@router.get("/{path:path}/history")
async def file_history(path: str, request: Request, limit: int = 20):
    git = request.app.state.git
    commits = await git.history(path, limit=limit)
    return [{"hash": c.hash, "message": c.message, "author": c.author, "timestamp": c.timestamp} for c in commits]


@router.get("/{path:path}/history/{commit}")
async def file_at_commit(path: str, commit: str, request: Request):
    git = request.app.state.git
    try:
        content = await git.get_content(path, commit)
    except RuntimeError:
        raise HTTPException(status_code=404, detail="Commit or file not found")
    return PlainTextResponse(content)


@router.post("/{path:path}/restore/{commit}")
async def restore_file(path: str, commit: str, request: Request):
    git = request.app.state.git
    await git.restore(path, commit)
    return {"status": "restored", "commit": commit}


def _resolve_path(path: str, config) -> str:
    allowed_bases = [
        config.soar.workflows_dir,
        config.soar.connectors_dir,
        config.soar.actions_dir,
    ]
    for base in allowed_bases:
        full = os.path.normpath(os.path.join(base, path))
        if full.startswith(os.path.normpath(base)):
            return full
    full = os.path.normpath(os.path.join(config.git.workflows_repo, path))
    return full


def _scan_dir(dir_path: str) -> dict:
    result = {}
    for entry in os.scandir(dir_path):
        if entry.name.startswith(".") or entry.name == "__pycache__":
            continue
        if entry.is_dir():
            result[entry.name] = _scan_dir(entry.path)
        else:
            result[entry.name] = None
    return result
