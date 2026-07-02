import requests
from requests.auth import HTTPBasicAuth

from soar.connectors.base import BaseConnector


class CensysConnector(BaseConnector):
    DEFAULT_BASE_URL = "https://search.censys.io/api"

    def __init__(self, instance_name: str, api_id: str, api_secret: str, base_url: str = ""):
        super().__init__(instance_name)
        self.api_id = api_id
        self.api_secret = api_secret
        self.base_url = base_url or self.DEFAULT_BASE_URL
        self._session: requests.Session | None = None

    def _connect_impl(self):
        self._session = requests.Session()
        self._session.auth = HTTPBasicAuth(self.api_id, self.api_secret)
        self._session.headers["User-Agent"] = "SOAR-Connector/1.0"

    def disconnect(self):
        if self._session:
            self._session.close()
            self._session = None
            self._connected = False
            self._logger.info(f"Disconnected from {self.instance_name}")

    def _get(self, path: str, params: dict | None = None) -> dict:
        self._ensure_connected()
        assert self._session is not None
        resp = self._session.get(f"{self.base_url}{path}", params=params)
        resp.raise_for_status()
        return resp.json()

    def search_hosts(self, query: str, page: int = 1, per_page: int = 100) -> dict:
        return self._get("/v2/hosts/search", params={"q": query, "page": page, "per_page": per_page})

    def get_host(self, ip: str) -> dict:
        return self._get(f"/v2/hosts/{ip}")

    def search_certificates(self, query: str, page: int = 1, per_page: int = 100) -> dict:
        return self._get("/v2/certificates/search", params={"q": query, "page": page, "per_page": per_page})

    def get_certificate(self, fingerprint: str) -> dict:
        return self._get(f"/v2/certificates/{fingerprint}")
