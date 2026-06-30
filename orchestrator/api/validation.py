import os
import re

from fastapi import HTTPException

SAFE_NAME_RE = re.compile(r"^[a-zA-Z0-9_\-]+$")
MAX_NAME_LEN = 100
MAX_BODY_SIZE = 5 * 1024 * 1024  # 5 MB


def validate_name(name: str) -> str:
    if not name or len(name) > MAX_NAME_LEN:
        raise HTTPException(status_code=400, detail="Invalid name")
    if not SAFE_NAME_RE.match(name):
        raise HTTPException(status_code=400, detail="Name contains invalid characters")
    return name


def validate_path_within(base_dir: str, resolved: str) -> str:
    normed = os.path.normpath(resolved)
    base = os.path.normpath(base_dir)
    if not (normed == base or normed.startswith(base + os.sep)):
        raise HTTPException(status_code=403, detail="Access denied")
    return normed


def validate_commit(commit: str) -> str:
    if not re.match(r"^[0-9a-f]{4,40}$", commit):
        raise HTTPException(status_code=400, detail="Invalid commit hash")
    return commit
