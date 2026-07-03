"""B6: SSRF protection must block domains that resolve to private IPs."""
import socket
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from orchestrator.api.connectors import _validate_external_url


def _make_addrinfo(ip: str):
    """Build a minimal getaddrinfo result for a single IP."""
    return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", (ip, 80))]


def test_ssrf_direct_private_ip_blocked():
    with pytest.raises(HTTPException) as exc:
        _validate_external_url("http://10.0.0.1/spec")
    assert exc.value.status_code == 400


def test_ssrf_direct_loopback_blocked():
    with pytest.raises(HTTPException):
        _validate_external_url("http://127.0.0.1/spec")


def test_ssrf_domain_resolves_to_private_blocked():
    """B6: a domain that resolves to 10.x.x.x must be blocked."""
    with patch("socket.getaddrinfo", return_value=_make_addrinfo("10.0.0.1")):
        with pytest.raises(HTTPException) as exc:
            _validate_external_url("http://internal.example.com/spec")
        assert exc.value.status_code == 400


def test_ssrf_domain_resolves_to_metadata_blocked():
    """B6: cloud metadata endpoint (169.254.169.254) via domain must be blocked."""
    with patch("socket.getaddrinfo", return_value=_make_addrinfo("169.254.169.254")):
        with pytest.raises(HTTPException):
            _validate_external_url("http://metadata.google.internal/spec")


def test_ssrf_domain_resolves_to_public_allowed():
    """B6: a domain resolving to a public IP must be allowed."""
    with patch("socket.getaddrinfo", return_value=_make_addrinfo("8.8.8.8")):
        _validate_external_url("http://public.example.com/spec")  # should not raise


def test_ssrf_non_http_scheme_blocked():
    with pytest.raises(HTTPException):
        _validate_external_url("ftp://example.com/spec")
