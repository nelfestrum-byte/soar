import importlib
from unittest.mock import patch

import httpx

from soar.tools._cache import InMemoryCache
from soar.tools.http_client import CachingHttpClient, LoggingHttpClient, new_client

# `soar.tools.__init__`  rebinds the name `http_client` in the package
# namespace to a LoggingHttpClient instance, so `import soar.tools.http_client
# as x` (an attribute-chain lookup) would resolve to that instance, not the
# submodule — importlib.import_module goes through sys.modules instead.
http_client_module = importlib.import_module("soar.tools.http_client")


def test_new_client_without_shared_cache_returns_logging_client(monkeypatch):
    monkeypatch.setattr(http_client_module, "_shared_cache", None)
    client = new_client()
    assert type(client) is LoggingHttpClient


def test_new_client_with_shared_cache_returns_caching_client_sharing_it(monkeypatch):
    cache = InMemoryCache()
    monkeypatch.setattr(http_client_module, "_shared_cache", cache)
    monkeypatch.setattr(http_client_module, "_shared_default_ttl", 999)
    monkeypatch.setattr(http_client_module, "_shared_domain_ttl", {"example.com": 60})

    client = new_client()

    assert type(client) is CachingHttpClient
    assert client._cache is cache
    assert client._default_ttl == 999
    assert client._domain_ttl == {"example.com": 60}


def test_new_client_verify_false_passed_through_without_cache(monkeypatch):
    monkeypatch.setattr(http_client_module, "_shared_cache", None)
    with patch.object(httpx.Client, "__init__", return_value=None) as mock_init:
        new_client(verify=False)
    assert mock_init.call_args.kwargs["verify"] is False


def test_new_client_verify_false_passed_through_with_cache(monkeypatch):
    monkeypatch.setattr(http_client_module, "_shared_cache", InMemoryCache())
    with patch.object(httpx.Client, "__init__", return_value=None) as mock_init:
        client = new_client(verify=False)
    assert type(client) is CachingHttpClient
    assert mock_init.call_args.kwargs["verify"] is False
