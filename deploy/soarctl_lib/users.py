"""Proxies to the existing orchestrator.auth.cli inside the running
container — no user-lifecycle logic duplicated here, see
docs/compose/specs/2026-07-21-auth-cli-user-lifecycle-design.md for why
that CLI (not an API) is the bootstrap path. No `list` subcommand: the
referenced spec deliberately left listing to /auth/users (API/UI).
"""

from pathlib import Path

from .compose import compose_argv
from .runner import run

_ROLES = ("admin", "analyst", "viewer", "service")
_CLI_ARGV = ["exec", "orchestrator", "python", "-m", "orchestrator.auth.cli"]


def create(instance: Path, username: str, role: str = "analyst") -> None:
    if role not in _ROLES:
        raise ValueError(f"unknown role {role!r} — expected one of {_ROLES}")
    argv = compose_argv(instance, *_CLI_ARGV, "create-user", "--username", username, "--role", role)
    run(argv, stream=True)


def deactivate(instance: Path, username: str) -> None:
    argv = compose_argv(instance, *_CLI_ARGV, "deactivate-user", "--username", username)
    run(argv, stream=True)


def activate(instance: Path, username: str) -> None:
    argv = compose_argv(instance, *_CLI_ARGV, "activate-user", "--username", username)
    run(argv, stream=True)
