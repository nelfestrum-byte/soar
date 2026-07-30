from typing import ClassVar

from soar.connectors.base import BaseConnector
from soar.tools import http_client_sync


class UrlhausConnector(BaseConnector):
    HIDDEN_FIELDS: ClassVar[set[str]] = set()
    MUTATING_METHODS: ClassVar[set[str]] = {"tag_url"}

    BASE_URL = "https://urlhaus-api.abuse.ch/v1"

    def _connect_impl(self):
        pass  # http_client_sync opens a connection per request, nothing to hold open

    def _post(self, data: dict) -> dict:
        self._ensure_connected()
        return http_client_sync.post_json(
            f"{self.BASE_URL}/url/", data, headers={"User-Agent": "SOAR-Connector/1.0"}
        )

    def get_url_info(self, url: str) -> list[dict]:
        data = self._post({"url": url})
        if data.get("query_status") == "no_results":
            return []
        return data.get("urls", [])

    def get_host_info(self, host: str) -> list[dict]:
        data = self._post({"host": host})
        if data.get("query_status") == "no_results":
            return []
        return data.get("urls", [])

    def get_payload_info(self, hash_value: str) -> dict:
        data = self._post({"query": "get_payload", "hash": hash_value})
        if data.get("query_status") == "no_results":
            return {}
        return data

    def get_recent_urls(self, limit: int = 100) -> list[dict]:
        data = self._post({"limit": str(limit)})
        if data.get("query_status") == "no_results":
            return []
        return data.get("urls", [])

    def url_exists(self, url: str) -> bool:
        data = self._post({"url": url})
        return data.get("query_status") != "no_results"

    def tag_url(self, url: str, tag: str, threat: str = "malware_download") -> dict:
        self._ensure_connected()
        return http_client_sync.post_json(
            f"{self.BASE_URL}/url/",
            {"url": url, "threat": threat, "tags": tag},
            headers={"User-Agent": "SOAR-Connector/1.0"},
        )
