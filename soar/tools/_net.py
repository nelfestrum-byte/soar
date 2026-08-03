"""Internal SSRF-guard/logging helpers for soar/tools/http_client.py — not
part of the public tool surface (soar/tools/__init__.py::TOOL_REGISTRY),
per the `_*.py` internal-mechanics convention (CLAUDE.md, docs/compose/
specs/2026-08-03-tools-redesign-design.md [S2](b))."""

import ipaddress
import socket
from urllib.parse import urlparse


def _is_private_ip(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
        return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved
    except ValueError:
        return False


def _validate_external_url(url: str) -> None:
    """Block requests to internal/private IP ranges, including via DNS.

    M4 (docs/concepts/BAGFIX_PLAN.md): this resolves the hostname to validate
    it, then httpx resolves it *again* when it actually connects — a DNS
    answer that changes between the two lookups (rebinding) could still slip
    an internal IP through. `follow_redirects=False` closes the more
    practical redirect-based variant of this; the two-lookup TOCTOU window
    itself is accepted as residual risk rather than fixed via IP pinning
    (would require overriding httpx's connection target, e.g. a custom
    transport, and is judged not worth that complexity/fragility for a
    same-process trusted-workflow caller — see accepted-risk precedent for
    P5/P6/P10/P11/P15 in docs/concepts/UPGRADE-v2.md)."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("Only HTTP/HTTPS URLs allowed")
    hostname = parsed.hostname or ""
    try:
        ip = ipaddress.ip_address(hostname)
    except ValueError:
        ip = None

    if ip is not None:
        # Direct IP literal: check immediately
        if _is_private_ip(str(ip)):
            raise ValueError("Requests to internal IPs are not allowed")
        return

    # Resolve hostname and check each returned address
    try:
        results = socket.getaddrinfo(hostname, None)
    except OSError as e:
        raise ValueError("Could not resolve hostname") from e
    for result in results:
        addr_ip = result[4][0]
        if _is_private_ip(addr_ip):
            raise ValueError("Requests to internal IPs are not allowed")


def _log_safe_url(url: str) -> str:
    """Strip query string before logging — TI APIs commonly pass API keys
    as `?apikey=...`/`?token=...` query params (M1)."""
    return urlparse(url)._replace(query="", fragment="").geturl()
