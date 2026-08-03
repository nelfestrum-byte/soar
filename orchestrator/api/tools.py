from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from loguru import logger

from orchestrator.auth.dependencies import require_role
from orchestrator.core.introspect import _summary, parse_classes, parse_functions, parse_tool_registry

router = APIRouter(prefix="/tools", tags=["tools"])
_RO = ("viewer", "analyst", "service", "admin", "agent")


def _resolve(tools_dir: Path, name: str, meta: dict) -> dict:
    """Resolve one TOOL_REGISTRY entry by its declared `kind` — the
    registry covers 100% of public names by construction (docs/compose/
    specs/2026-08-03-tools-redesign-design.md [S2](a)), so "nothing found"
    only happens for a broken tool file/class and must surface as a flagged
    configuration error, never a silent stub."""
    module_file = tools_dir / f"{meta['module']}.py"
    entry = None
    if meta["kind"] == "class":
        cls = next((c for c in parse_classes(module_file) if c["name"] == name), None)
        entry = {**cls, "module": meta["module"]} if cls else None
    elif meta["kind"] == "instance":
        cls = next((c for c in parse_classes(module_file) if c["name"] == meta["of"]), None)
        entry = {**cls, "name": name, "module": meta["module"], "instance_of": meta["of"]} if cls else None
    else:  # factory
        fn = next((f for f in parse_functions(module_file) if f["name"] == name), None)
        entry = {**fn, "module": meta["module"], "kind": "function"} if fn else None
    if entry is not None:
        return entry
    logger.error(f"tool registry entry {name!r} did not resolve (module={meta['module']!r}, kind={meta['kind']!r})")
    return {"name": name, "module": meta["module"], "summary": "", "error": "unresolved"}


@router.get("", dependencies=[Depends(require_role(*_RO))])
async def list_tools(request: Request):
    """soar/tools/__init__.py::TOOL_REGISTRY is the single source of what's
    surfaced here — a literal dict declaring both what's public and how to
    introspect it (class/instance/factory), not a directory glob of every
    top-level class in every file (that used to leak internal mechanics
    like CacheBackend/InMemoryCache/RedisCache)."""
    tools_dir = Path(request.app.state.config.soar.tools_dir)
    if not tools_dir.exists():
        return []
    registry = parse_tool_registry(tools_dir / "__init__.py")
    result = [_resolve(tools_dir, name, meta) for name, meta in registry.items()]
    for entry in result:
        if "summary" not in entry:
            entry["summary"] = _summary(entry.get("docstring", ""))
    return result


@router.get("/{name}", dependencies=[Depends(require_role(*_RO))])
async def get_tool(name: str, request: Request):
    tools_dir = Path(request.app.state.config.soar.tools_dir)
    if tools_dir.exists():
        registry = parse_tool_registry(tools_dir / "__init__.py")
        if name in registry:
            return _resolve(tools_dir, name, registry[name])
    raise HTTPException(status_code=404, detail="Tool not found")
