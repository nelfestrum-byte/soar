import json
from unittest.mock import patch

import pytest

from soar import runner
from soar.tools.http_client import InMemoryCache, RedisCache


def test_main_missing_workflow_prints_traceback_and_exits(monkeypatch, capsys):
    monkeypatch.setenv("SOAR_WORKFLOW_NAME", "nonexistent_workflow_xyz")
    monkeypatch.setenv("SOAR_CONTEXT", "{}")

    with pytest.raises(SystemExit) as exc_info:
        runner.main()

    assert exc_info.value.code == 1
    output = json.loads(capsys.readouterr().out.strip())
    assert output["success"] is False
    assert output["workflow_name"] == "nonexistent_workflow_xyz"
    assert output["data"] is None
    assert "ValueError" in output["error"]
    assert "nonexistent_workflow_xyz" in output["error"]


def test_main_workflow_run_failure_includes_full_traceback(monkeypatch, capsys):
    from soar.workflows import workflows as wf_registry
    from soar.workflows.base import ManualWorkflow

    class FailingWorkflow(ManualWorkflow):
        def run(self, context):
            raise ValueError("kaboom")

    wf_registry._workflows["failing_test_workflow"] = FailingWorkflow
    try:
        monkeypatch.setenv("SOAR_WORKFLOW_NAME", "failing_test_workflow")
        monkeypatch.setenv("SOAR_CONTEXT", "{}")

        with pytest.raises(SystemExit) as exc_info:
            runner.main()

        assert exc_info.value.code == 1
        output = json.loads(capsys.readouterr().out.strip())
        assert output["success"] is False
        assert "ValueError" in output["error"]
        assert "kaboom" in output["error"]
        assert "test_runner.py" in output["error"]
    finally:
        wf_registry._workflows.pop("failing_test_workflow", None)


def test_build_http_client_defaults_to_memory_cache():
    client = runner._build_http_client({})
    assert isinstance(client._cache, InMemoryCache)
    assert client._default_ttl == 3600


def test_build_http_client_none_backend_has_no_cache():
    client = runner._build_http_client({"http_client": {"cache_backend": "none"}})
    assert client._cache is None


def test_build_http_client_reads_ttl_and_domain_ttl():
    client = runner._build_http_client({
        "http_client": {
            "cache_backend": "memory",
            "default_ttl": 60,
            "domain_ttl": {"api.virustotal.com": 86400},
        }
    })
    assert client._default_ttl == 60
    assert client._domain_ttl == {"api.virustotal.com": 86400}


def test_build_http_client_redis_backend_uses_queue_redis_url():
    with patch("redis.from_url") as mock_from_url:
        client = runner._build_http_client({
            "http_client": {"cache_backend": "redis"},
            "queue": {"redis_url": "redis://localhost:6379/2"},
        })
        assert isinstance(client._cache, RedisCache)
        mock_from_url.assert_called_once_with("redis://localhost:6379/2")


def test_build_http_client_redis_backend_without_redis_url_raises():
    with pytest.raises(ValueError, match="redis_url"):
        runner._build_http_client({
            "http_client": {"cache_backend": "redis"},
            "queue": {"redis_url": ""},
        })


def test_build_http_client_unknown_backend_raises():
    with pytest.raises(ValueError, match="Unknown"):
        runner._build_http_client({"http_client": {"cache_backend": "bogus"}})


def test_build_http_client_sync_shares_cache_with_async_client():
    http_client = runner._build_http_client({
        "http_client": {
            "cache_backend": "memory",
            "default_ttl": 60,
            "domain_ttl": {"api.virustotal.com": 86400},
        }
    })
    sync_client = runner._build_http_client_sync(http_client)

    assert sync_client._cache is http_client._cache
    assert sync_client._default_ttl == http_client._default_ttl == 60
    assert sync_client._domain_ttl == http_client._domain_ttl == {"api.virustotal.com": 86400}
