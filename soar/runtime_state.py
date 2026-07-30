"""Process-wide state for the current job — one soar.runner subprocess is
always exactly one job (see Runner contract, AGENTS.md), so a module-level
flag is the whole job's dry_run status, not per-call context threading."""

_dry_run = False


def set_dry_run(value: bool) -> None:
    global _dry_run
    _dry_run = value


def is_dry_run() -> bool:
    return _dry_run
