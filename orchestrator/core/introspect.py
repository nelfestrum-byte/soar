import ast
from pathlib import Path


def _signature(fn: ast.FunctionDef) -> str:
    args = [a.arg for a in fn.args.args if a.arg != "self"]
    return f"({', '.join(args)})"


def _summary(docstring: str) -> str:
    return docstring.splitlines()[0] if docstring else ""


def parse_classes(path: Path) -> list[dict]:
    """Static AST parse of a module's top-level classes — never imports it.
    Moved from orchestrator/api/tools.py without behavior change."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    classes = []
    for node in ast.iter_child_nodes(tree):
        if not isinstance(node, ast.ClassDef) or node.name.startswith("_"):
            continue
        methods = [
            {"name": item.name, "signature": _signature(item), "docstring": ast.get_docstring(item) or ""}
            for item in node.body
            if isinstance(item, ast.FunctionDef) and not item.name.startswith("_")
        ]
        init = next(
            (n for n in node.body if isinstance(n, ast.FunctionDef) and n.name == "__init__"), None,
        )
        classes.append({
            "name": node.name,
            "docstring": ast.get_docstring(node) or "",
            "constructor": _signature(init) if init else "()",
            "methods": methods,
        })
    return classes


def parse_functions(path: Path) -> list[dict]:
    """Static AST parse of a module's top-level functions — never imports it."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [
        {"name": node.name, "signature": _signature(node), "docstring": ast.get_docstring(node) or ""}
        for node in ast.iter_child_nodes(tree)
        if isinstance(node, ast.FunctionDef) and not node.name.startswith("_")
    ]
