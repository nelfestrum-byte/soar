"""B4: resolve_client_ip() exact-match trust — not tied to 127.0.0.1.

Existing coverage (test_rate_limiter.py, test_access_log_middleware.py) only
ever exercises trusted_proxies=["127.0.0.1"], because httpx.ASGITransport
always presents that as request.client.host. These tests call
resolve_client_ip() directly with a mocked Request so an arbitrary peer IP
(e.g. the docker-network address of the `ui` container, see
deploy/prod/docker-compose.yml) can be asserted as trusted.
"""
from types import SimpleNamespace

from orchestrator.config import OrchestratorConfig, ServerConfig
from orchestrator.core.net import resolve_client_ip


def _make_request(client_host: str, trusted_proxies: list[str], headers: dict | None = None):
    config = OrchestratorConfig(server=ServerConfig(trusted_proxies=trusted_proxies))
    return SimpleNamespace(
        client=SimpleNamespace(host=client_host),
        headers=headers or {},
        app=SimpleNamespace(state=SimpleNamespace(config=config)),
    )


def test_resolve_client_ip_trusts_exact_non_loopback_match():
    request = _make_request(
        client_host="172.28.0.10",
        trusted_proxies=["172.28.0.10"],
        headers={"X-Real-IP": "203.0.113.5"},
    )
    assert resolve_client_ip(request) == "203.0.113.5"


def test_resolve_client_ip_ignores_forwarded_ip_on_mismatch():
    request = _make_request(
        client_host="172.28.0.10",
        trusted_proxies=["10.0.0.1"],
        headers={"X-Real-IP": "203.0.113.5"},
    )
    assert resolve_client_ip(request) == "172.28.0.10"
