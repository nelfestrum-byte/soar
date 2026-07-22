"""GET /health check + human-readable status summary. Uses urllib (stdlib)
— no new HTTP dependency for a one-endpoint, unauthenticated liveness check.
"""

from urllib.error import URLError
from urllib.request import urlopen


def check_health(base_url: str) -> tuple[bool, str]:
    try:
        with urlopen(f"{base_url.rstrip('/')}/health", timeout=5) as resp:
            body = resp.read().decode()
            return True, body
    except URLError as e:
        return False, str(e.reason)
    except OSError as e:
        return False, str(e)


def summarize(ps_output: str, health: tuple[bool, str]) -> str:
    ok, message = health
    health_line = f"health: {'ok' if ok else 'FAIL'} ({message})"
    return f"{ps_output}\n\n{health_line}"
