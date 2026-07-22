"""Thin docker compose wrapper scoped to one instance directory.

Every command needs the instance's own docker-compose.yml and .env — never
falls back to a bare `docker compose` invocation that would pick up
whatever's in the caller's cwd.
"""

from pathlib import Path

from .runner import run


class ComposeError(RuntimeError):
    pass


def compose_argv(instance: Path, *args: str) -> list[str]:
    compose_file = instance / "docker-compose.yml"
    env_file = instance / ".env"
    if not compose_file.exists():
        raise ComposeError(f"{compose_file} not found — is {instance} a soarctl instance directory?")
    if not env_file.exists():
        raise ComposeError(f"{env_file} not found — run `soarctl init` first")
    return ["docker", "compose", "-f", str(compose_file), "--env-file", str(env_file), *args]


def up(instance: Path) -> None:
    run(compose_argv(instance, "up", "-d"), stream=True)


def down(instance: Path) -> None:
    run(compose_argv(instance, "down"), stream=True)


def restart(instance: Path) -> None:
    run(compose_argv(instance, "restart"), stream=True)


def ps(instance: Path) -> str:
    return run(compose_argv(instance, "ps")).stdout


def logs(instance: Path, service: str | None = None) -> None:
    args = ["logs", "-f"] + ([service] if service else [])
    run(compose_argv(instance, *args), stream=True, check=False)
