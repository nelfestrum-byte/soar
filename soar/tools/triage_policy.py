"""Triage policies from the SOC Core settings API, with a durable local cache.

Source of truth is SOC Core's config.json (contract §2) — SOAR never duplicates
whitelist/blacklist/thresholds/critical assets, only reads them. Failure modes
(spec Task 2, step load_policy):

  - API up            → fresh policies, cache refreshed on disk
  - API down, cache   → last cached policies + warning (stale is acceptable)
  - API down, no cache → TriagePolicyError; the triage cycle must abort —
    an empty whitelist is more dangerous than a missed cycle.

The exact endpoint is assumption Д-3 of the plan; it is configurable
(``irp.policy_endpoint``) so the confirmed path is a config change, not code.
"""

import json
import os
import time
from collections.abc import Callable

import requests

from soar.logger import get_logger

_log = get_logger("tools.triage_policy")

# Normalized policy keys with safe fallbacks for optional values. Gate values
# follow the legacy behaviour (assumption Д-1): send when sev >= 3 OR
# count >= threshold.
_DEFAULTS = {
    "whitelist": [],
    "blacklist": [],
    "critical_assets": [],
    "count_threshold": 3,
    "severity_gate": 3,
}


class TriagePolicyError(Exception):
    """Policies unavailable and no cache — the triage cycle must not run."""


def policy_fetcher(
    base_url: str,
    api_token: str,
    endpoint: str = "/api/v2/settings/triage",
    verify_ssl: bool = True,
    timeout: int = 15,
) -> Callable[[], dict]:
    """HTTP fetcher for TriagePolicyCache — same M2M token as IRPConnector."""

    url = f"{base_url.rstrip('/')}{endpoint}"

    def fetch() -> dict:
        resp = requests.get(
            url, headers={"X-API-Token": api_token}, verify=verify_ssl, timeout=timeout
        )
        resp.raise_for_status()
        return resp.json()

    return fetch


class TriagePolicyCache:
    def __init__(self, fetch: Callable[[], dict], cache_path: str, ttl: int = 60):
        self._fetch = fetch
        self.cache_path = cache_path
        self.ttl = ttl

    def _read_cache(self) -> tuple[float, dict] | None:
        if not os.path.exists(self.cache_path):
            return None
        try:
            with open(self.cache_path, encoding="utf-8") as f:
                data = json.load(f)
            return float(data["fetched_at"]), data["policies"]
        except (json.JSONDecodeError, OSError, KeyError, TypeError, ValueError) as e:
            _log.warning(f"policy cache {self.cache_path} unreadable ({e})")
            return None

    def _write_cache(self, policies: dict) -> None:
        directory = os.path.dirname(self.cache_path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        tmp = f"{self.cache_path}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"fetched_at": time.time(), "policies": policies}, f, ensure_ascii=False)
        os.replace(tmp, self.cache_path)

    @staticmethod
    def _normalize(raw: dict) -> dict:
        policies = dict(_DEFAULTS)
        for key in policies:
            if key in raw and raw[key] is not None:
                policies[key] = raw[key]
        return policies

    def get(self) -> dict:
        cached = self._read_cache()
        if cached is not None:
            fetched_at, policies = cached
            if time.time() - fetched_at < self.ttl:
                return self._normalize(policies)

        try:
            raw = self._fetch()
        except Exception as e:
            if cached is not None:
                _log.warning(f"policy fetch failed ({e}), using stale cache")
                return self._normalize(cached[1])
            raise TriagePolicyError(
                f"triage policies unavailable and no local cache: {e}"
            ) from e

        policies = self._normalize(raw if isinstance(raw, dict) else {})
        self._write_cache(policies)
        return policies
