import json
import time

import pytest

from soar.tools.triage_policy import TriagePolicyCache, TriagePolicyError


class Fetcher:
    def __init__(self, result=None, error=None):
        self.result = result if result is not None else {"whitelist": ["a*"], "count_threshold": 5}
        self.error = error
        self.calls = 0

    def __call__(self):
        self.calls += 1
        if self.error:
            raise self.error
        return self.result


def test_fetch_writes_cache_and_normalizes(tmp_path):
    path = str(tmp_path / "policy.json")
    cache = TriagePolicyCache(Fetcher(), path, ttl=60)
    policies = cache.get()
    assert policies["whitelist"] == ["a*"]
    assert policies["count_threshold"] == 5
    # defaults filled for missing keys
    assert policies["blacklist"] == []
    assert policies["severity_gate"] == 3
    assert json.load(open(path, encoding="utf-8"))["policies"]["whitelist"] == ["a*"]


def test_fresh_cache_skips_fetch(tmp_path):
    path = str(tmp_path / "policy.json")
    fetcher = Fetcher()
    cache = TriagePolicyCache(fetcher, path, ttl=60)
    cache.get()
    cache.get()
    assert fetcher.calls == 1


def test_api_down_uses_stale_cache(tmp_path):
    path = str(tmp_path / "policy.json")
    TriagePolicyCache(Fetcher(), path, ttl=60).get()
    # expire the cache
    data = json.load(open(path, encoding="utf-8"))
    data["fetched_at"] = time.time() - 3600
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)

    cache = TriagePolicyCache(Fetcher(error=ConnectionError("down")), path, ttl=60)
    policies = cache.get()
    assert policies["whitelist"] == ["a*"]


def test_api_down_no_cache_raises(tmp_path):
    cache = TriagePolicyCache(
        Fetcher(error=ConnectionError("down")), str(tmp_path / "policy.json"), ttl=60
    )
    with pytest.raises(TriagePolicyError):
        cache.get()
