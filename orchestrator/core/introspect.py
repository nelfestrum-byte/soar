import ast
from pathlib import Path


def _signature(fn: ast.FunctionDef) -> str:
    args = [a.arg for a in fn.args.args if a.arg != "self"]
    return f"({', '.join(args)})"


def _summary(docstring: str) -> str:
    return docstring.splitlines()[0] if docstring else ""


def _fields(fn: ast.FunctionDef) -> list[dict]:
    """Extract typed constructor fields (name/type/default) via AST — no import."""
    args = [a for a in fn.args.args if a.arg != "self"]
    defaults = fn.args.defaults
    pad = len(args) - len(defaults)
    out = []
    for i, a in enumerate(args):
        default = None
        if i >= pad:
            d = defaults[i - pad]
            default = ast.literal_eval(d) if isinstance(d, ast.Constant) else None
        out.append({
            "name": a.arg,
            "type": ast.unparse(a.annotation) if a.annotation else "str",
            "default": default,
        })
    return out


def _target_name(item: ast.stmt) -> str | None:
    if isinstance(item, ast.AnnAssign):
        return item.target.id if isinstance(item.target, ast.Name) else None
    if isinstance(item, ast.Assign) and len(item.targets) == 1:
        target = item.targets[0]
        return target.id if isinstance(target, ast.Name) else None
    return None


def _hidden_fields(node: ast.ClassDef) -> set[str]:
    """Read the class-level HIDDEN_FIELDS declaration via AST — no import."""
    for item in node.body:
        if isinstance(item, (ast.AnnAssign, ast.Assign)) and _target_name(item) == "HIDDEN_FIELDS":
            value = item.value
            if isinstance(value, (ast.Set, ast.List, ast.Tuple)):
                return {el.value for el in value.elts if isinstance(el, ast.Constant)}
    return set()


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
            "fields": _fields(init) if init else [],
            "hidden_fields": _hidden_fields(node),
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


_TYPE_BY_BASE = {
    "ScheduledWorkflow": "scheduled",
    "WebhookWorkflow": "webhook",
    "ManualWorkflow": "manual",
    "BaseWorkflow": "manual",
}
_WORKFLOW_META_FIELDS = ("schedule", "interval", "path", "token")


def _base_name(base: ast.expr) -> str | None:
    if isinstance(base, ast.Name):
        return base.id
    if isinstance(base, ast.Attribute):
        return base.attr
    return None


def parse_workflow_meta(path: Path) -> dict | None:
    """Static AST parse of a workflow module's class-level metadata
    (type/schedule/interval/path/token/docstring) — never imports it.
    Returns None if the module doesn't define a BaseWorkflow subclass."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.iter_child_nodes(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        base_names = {n for b in node.bases if (n := _base_name(b))}
        wf_type = next((_TYPE_BY_BASE[b] for b in base_names if b in _TYPE_BY_BASE), None)
        if wf_type is None:
            continue
        meta: dict[str, object] = {"type": wf_type, "docstring": ast.get_docstring(node) or ""}
        for item in node.body:
            if not isinstance(item, (ast.AnnAssign, ast.Assign)):
                continue
            name = _target_name(item)
            if name in _WORKFLOW_META_FIELDS and isinstance(item.value, ast.Constant):
                meta[name] = item.value.value
        return meta
    return None
