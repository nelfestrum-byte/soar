from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request

from orchestrator.auth.dependencies import require_role
from orchestrator.core.introspect import _public_names, _summary, parse_classes

router = APIRouter(prefix="/tools", tags=["tools"])
_RO = ("viewer", "analyst", "service", "admin", "agent")


@router.get("", dependencies=[Depends(require_role(*_RO))])
async def list_tools(request: Request):
    """soar/tools/__init__.py::__all__ (E5) is the single source of what's
    surfaced here — not a directory glob of every top-level class in every
    file (that used to leak internal mechanics like CacheBackend/
    InMemoryCache/RedisCache). Singletons/factories declared in __all__ that
    aren't classes (http_client, watermark_store, ...) get a synthetic entry
    since parse_classes can't see them."""
    tools_dir = Path(request.app.state.config.soar.tools_dir)
    if not tools_dir.exists():
        return []
    public = set(_public_names(tools_dir / "__init__.py"))
    result = []
    for py_file in sorted(tools_dir.glob("*.py")):
        if py_file.name.startswith("_"):
            continue
        for cls in parse_classes(py_file):
            if cls["name"] in public:
                result.append({
                    "name": cls["name"],
                    "module": py_file.stem,
                    "summary": _summary(cls["docstring"]),
                })
    class_names = {r["name"] for r in result}
    for name in sorted(public - class_names):
        result.append({"name": name, "module": "__init__", "summary": ""})
    return result


@router.get("/{name}", dependencies=[Depends(require_role(*_RO))])
async def get_tool(name: str, request: Request):
    tools_dir = Path(request.app.state.config.soar.tools_dir)
    if tools_dir.exists():
        public = set(_public_names(tools_dir / "__init__.py"))
        if name in public:
            for py_file in sorted(tools_dir.glob("*.py")):
                if py_file.name.startswith("_"):
                    continue
                for cls in parse_classes(py_file):
                    if cls["name"] == name:
                        return {**cls, "module": py_file.stem}
    raise HTTPException(status_code=404, detail="Tool not found")
