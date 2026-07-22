"""Preflight checks — each a standalone (ok, message) function so `soarctl
doctor` can report all of them instead of stopping at the first failure.
"""

import shutil
import socket
from pathlib import Path

from .runner import CommandError, run

_DEFAULT_PORTS = (8000, 3000)
_MIN_FREE_GB = 2


def check_docker_present() -> tuple[bool, str]:
    path = shutil.which("docker")
    if path:
        return True, f"docker found at {path}"
    return False, "docker not found on PATH"


def check_docker_compose() -> tuple[bool, str]:
    try:
        result = run(["docker", "compose", "version"])
        return True, result.stdout.strip()
    except CommandError as e:
        return False, str(e)


def check_ports_free(ports=_DEFAULT_PORTS) -> tuple[bool, str]:
    busy = []
    for port in ports:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.2)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                busy.append(port)
    if busy:
        return False, f"port(s) already in use: {', '.join(str(p) for p in busy)}"
    return True, f"port(s) free: {', '.join(str(p) for p in ports)}"


def check_env_file(instance: Path) -> tuple[bool, str]:
    env_path = instance / ".env"
    if not env_path.exists():
        return False, f"{env_path} missing — run `soarctl init` first"
    return True, f"{env_path} present"


def check_disk_space(instance: Path, min_free_gb: int = _MIN_FREE_GB) -> tuple[bool, str]:
    usage = shutil.disk_usage(instance)
    free_gb = usage.free / (1024**3)
    if free_gb < min_free_gb:
        return False, f"only {free_gb:.1f}GB free, need at least {min_free_gb}GB"
    return True, f"{free_gb:.1f}GB free"


def run_checks(instance: Path) -> list[tuple[str, bool, str]]:
    checks = [
        ("docker", check_docker_present),
        ("docker compose", check_docker_compose),
        ("ports", lambda: check_ports_free()),
        ("env", lambda: check_env_file(instance)),
        ("disk space", lambda: check_disk_space(instance)),
    ]
    results = []
    for name, check in checks:
        ok, message = check()
        results.append((name, ok, message))
    return results
