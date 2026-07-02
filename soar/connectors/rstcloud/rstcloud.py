import requests

from soar.connectors.base import BaseConnector


class RstCloudConnector(BaseConnector):
    DEFAULT_BASE_URL = "https://opentip.rstcloud.net"

    def __init__(self, instance_name: str, api_key: str, base_url: str = "", verify_ssl: bool = True):
        super().__init__(instance_name)
        self.api_key = api_key
        self.base_url = base_url or self.DEFAULT_BASE_URL
        self.verify_ssl = verify_ssl
        self._session: requests.Session | None = None

    def _connect_impl(self):
        self._session = requests.Session()
        self._session.headers["User-Agent"] = "SOAR-Connector/1.0"
        self._session.headers["Authorization"] = f"Bearer {self.api_key}"

    def disconnect(self):
        if self._session:
            self._session.close()
            self._session = None
            self._connected = False
            self._logger.info(f"Disconnected from {self.instance_name}")

    def _get(self, path: str) -> dict:
        self._ensure_connected()
        assert self._session is not None
        resp = self._session.get(f"{self.base_url}{path}", verify=self.verify_ssl)
        resp.raise_for_status()
        return resp.json()

    def check_ip(self, ip: str) -> dict:
        return self._get(f"/api/v1/ip/{ip}")

    def check_domain(self, domain: str) -> dict:
        return self._get(f"/api/v1/domain/{domain}")

    def check_hash(self, hash_value: str) -> dict:
        return self._get(f"/api/v1/file/{hash_value}")

    def check_url(self, url: str) -> dict:
        self._ensure_connected()
        assert self._session is not None
        resp = self._session.get(
            f"{self.base_url}/api/v1/url",
            params={"url": url},
            verify=self.verify_ssl,
        )
        resp.raise_for_status()
        return resp.json()
