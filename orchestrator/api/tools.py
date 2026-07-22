from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request

from orchestrator.auth.dependencies import require_role
from orchestrator.core.introspect import _summary, parse_classes

router = APIRouter(prefix="/tools", tags=["tools"])
_RO = ("viewer", "analyst", "service", "admin")


@router.get("", dependencies=[Depends(require_role(*_RO))])
async def list_tools(request: Request):
    tools_dir = Path(request.app.state.config.soar.tools_dir)
    if not tools_dir.exists():
        return []
    result = []
    for py_file in sorted(tools_dir.glob("*.py")):
        if py_file.name.startswith("_"):
            continue
        for cls in parse_classes(py_file):
            result.append({
                "name": cls["name"],
                "module": py_file.stem,
                "summary": _summary(cls["docstring"]),
            })
    return result


@router.get("/{name}", dependencies=[Depends(require_role(*_RO))])
async def get_tool(name: str, request: Request):
    tools_dir = Path(request.app.state.config.soar.tools_dir)
    if tools_dir.exists():
        for py_file in sorted(tools_dir.glob("*.py")):
            if py_file.name.startswith("_"):
                continue
            for cls in parse_classes(py_file):
                if cls["name"] == name:
                    return {**cls, "module": py_file.stem}
    raise HTTPException(status_code=404, detail="Tool not found")
