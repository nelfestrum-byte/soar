from typing import ClassVar
from urllib.parse import urlencode

from soar.connectors.base import BaseConnector
from soar.tools import http_client_sync


class RstCloudConnector(BaseConnector):
    HIDDEN_FIELDS: ClassVar[set[str]] = {"api_key"}

    DEFAULT_BASE_URL = "https://opentip.rstcloud.net"

    def __init__(self, instance_name: str, api_key: str, base_url: str = "", verify_ssl: bool = True):
        super().__init__(instance_name)
        self.api_key = api_key
        self.base_url = base_url or self.DEFAULT_BASE_URL
        self.verify_ssl = verify_ssl

    def _connect_impl(self):
        pass  # http_client_sync opens a connection per request, nothing to hold open

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.api_key}", "User-Agent": "SOAR-Connector/1.0"}

    def _get(self, path: str) -> dict:
        self._ensure_connected()
        return http_client_sync.get_json(
            f"{self.base_url}{path}", headers=self._headers(), verify=self.verify_ssl
        )

    def check_ip(self, ip: str) -> dict:
        return self._get(f"/api/v1/ip/{ip}")

    def check_domain(self, domain: str) -> dict:
        return self._get(f"/api/v1/domain/{domain}")

    def check_hash(self, hash_value: str) -> dict:
        return self._get(f"/api/v1/file/{hash_value}")

    def check_url(self, url: str) -> dict:
        self._ensure_connected()
        query = urlencode({"url": url})
        return http_client_sync.get_json(
            f"{self.base_url}/api/v1/url?{query}",
            headers=self._headers(),
            verify=self.verify_ssl,
        )
