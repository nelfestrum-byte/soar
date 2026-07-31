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


def _public_names(init_path: Path) -> list[str]:
    """Read a module's `__all__ = [...]` declaration via AST — no import.
    Used by GET /tools (soar/tools/__init__.py::__all__, E5) to filter what
    the API surfaces down to the deliberately-public names, same pattern as
    _hidden_fields above."""
    if not init_path.is_file():
        return []
    tree = ast.parse(init_path.read_text(encoding="utf-8"))
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name) and target.id == "__all__":
                if isinstance(node.value, (ast.List, ast.Tuple, ast.Set)):
                    return [el.value for el in node.value.elts if isinstance(el, ast.Constant)]
    return []


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


def parse_connector_usage(
    path: Path,
    actions_dir: str | Path | None = None,
    _visited: set[Path] | None = None,
) -> list[tuple[str, str]]:
    """Static AST scan for `from soar.connectors.<type> import <instance>`,
    resolved directly at the given module's top level, or transitively
    through any `from soar.actions.<module> import ...` it uses (recursing
    into `actions_dir/<module>.py`, itself scanned the same way) — the only
    forms the platform can resolve to a concrete (type, instance) pair
    without importing the module (E6, docs/concepts/ENTITY-MODEL.md Фаза 2).
    Used by orchestrator/core/subprocess_runner.py::build_scoped_config to
    narrow the connector credentials a job's subprocess receives down to
    what the workflow actually references, directly or via the documented
    "workflow -> actions -> connector" pattern (AGENTS.md "движок vs
    поведение"). Never imports the module.

    `actions_dir` is optional and defaults to None — without it, `soar.
    actions.*` imports are recorded but not followed (backward-compatible
    with callers that only care about direct connector imports). A missing
    or unreadable action file is skipped, not fatal to the rest of the scan
    (a broken/absent action must not blank out other valid imports of the
    same workflow); `_visited` guards against import cycles between action
    modules.

    Returns [(type_name, instance_name), ...]. `instance_name` is always
    `alias.name` (the attribute actually fetched off the `soar.connectors.
    <type>` shim module, per PEP 562 module __getattr__ in
    soar/connectors/__init__.py::_install_shims) — NOT `alias.asname`. An
    `as`-aliased import (`from soar.connectors.ssh import prod as
    ssh_prod`) still resolves the registry instance named "prod"; "ssh_prod"
    is only the local variable name inside the workflow and never reaches
    the registry lookup. Scoping on asname would exclude the real instance
    from the job's config slice and break the workflow at runtime. Same
    rule applies symmetrically to connector imports found inside action
    files."""
    if _visited is None:
        _visited = set()
    resolved = path.resolve()
    if resolved in _visited:
        return []
    _visited.add(resolved)

    tree = ast.parse(path.read_text(encoding="utf-8"))
    result: list[tuple[str, str]] = []
    action_modules: list[str] = []
    for node in ast.iter_child_nodes(tree):
        if not isinstance(node, ast.ImportFrom) or not node.module:
            continue
        parts = node.module.split(".")
        if len(parts) == 3 and parts[0] == "soar" and parts[1] == "connectors":
            type_name = parts[2]
            result.extend((type_name, alias.name) for alias in node.names)
        elif len(parts) == 3 and parts[0] == "soar" and parts[1] == "actions":
            action_modules.append(parts[2])

    if actions_dir:
        actions_root = Path(actions_dir)
        for module_name in action_modules:
            action_path = actions_root / f"{module_name}.py"
            if not action_path.is_file():
                continue
            try:
                result.extend(parse_connector_usage(action_path, actions_dir, _visited))
            except (OSError, SyntaxError, UnicodeDecodeError):
                continue  # broken action file must not blank out the rest of the scan
    return result


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
