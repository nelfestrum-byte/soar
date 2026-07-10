import ast
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request

from orchestrator.auth.dependencies import require_role

router = APIRouter(prefix="/tools", tags=["tools"])
_RO = ("viewer", "analyst", "service", "admin")


def _signature(fn: ast.FunctionDef) -> str:
    args = [a.arg for a in fn.args.args if a.arg != "self"]
    return f"({', '.join(args)})"


def _summary(docstring: str) -> str:
    return docstring.splitlines()[0] if docstring else ""


def _parse_module(path: Path) -> list[dict]:
    """Static AST parse of a tools module — never imports it, so a tool's
    own (possibly heavy or optional) runtime dependencies can't break
    discovery in the orchestrator process."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    classes = []
    for node in ast.iter_child_nodes(tree):
        if not isinstance(node, ast.ClassDef) or node.name.startswith("_"):
            continue
        methods = [
            {
                "name": item.name,
                "signature": _signature(item),
                "docstring": ast.get_docstring(item) or "",
            }
            for item in node.body
            if isinstance(item, ast.FunctionDef) and not item.name.startswith("_")
        ]
        init = next(
            (n for n in node.body if isinstance(n, ast.FunctionDef) and n.name == "__init__"),
            None,
        )
        classes.append({
            "name": node.name,
            "docstring": ast.get_docstring(node) or "",
            "constructor": _signature(init) if init else "()",
            "methods": methods,
        })
    return classes


@router.get("", dependencies=[Depends(require_role(*_RO))])
async def list_tools(request: Request):
    tools_dir = Path(request.app.state.config.soar.tools_dir)
    if not tools_dir.exists():
        return []
    result = []
    for py_file in sorted(tools_dir.glob("*.py")):
        if py_file.name.startswith("_"):
            continue
        for cls in _parse_module(py_file):
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
            for cls in _parse_module(py_file):
                if cls["name"] == name:
                    return {**cls, "module": py_file.stem}
    raise HTTPException(status_code=404, detail="Tool not found")
