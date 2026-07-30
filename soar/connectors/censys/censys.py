import base64
from typing import ClassVar
from urllib.parse import urlencode

from soar.connectors.base import BaseConnector
from soar.tools import http_client_sync


class CensysConnector(BaseConnector):
    HIDDEN_FIELDS: ClassVar[set[str]] = {"api_secret"}
    MUTATING_METHODS: ClassVar[set[str]] = set()  # all methods are read-only lookups

    DEFAULT_BASE_URL = "https://search.censys.io/api"

    def __init__(self, instance_name: str, api_id: str, api_secret: str, base_url: str = ""):
        super().__init__(instance_name)
        self.api_id = api_id
        self.api_secret = api_secret
        self.base_url = base_url or self.DEFAULT_BASE_URL

    def _connect_impl(self):
        pass  # http_client_sync opens a connection per request, nothing to hold open

    def _headers(self) -> dict:
        # HTTPBasicAuth-equivalent header, built by hand — SyncHttpClient
        # takes headers, not a requests.auth.AuthBase.
        token = base64.b64encode(f"{self.api_id}:{self.api_secret}".encode()).decode()
        return {"Authorization": f"Basic {token}", "User-Agent": "SOAR-Connector/1.0"}

    def _get(self, path: str, params: dict | None = None) -> dict:
        self._ensure_connected()
        url = f"{self.base_url}{path}"
        if params:
            url += f"?{urlencode(params)}"
        return http_client_sync.get_json(url, headers=self._headers())

    def search_hosts(self, query: str, page: int = 1, per_page: int = 100) -> dict:
        return self._get("/v2/hosts/search", {"q": query, "page": page, "per_page": per_page})

    def get_host(self, ip: str) -> dict:
        return self._get(f"/v2/hosts/{ip}")

    def search_certificates(self, query: str, page: int = 1, per_page: int = 100) -> dict:
        return self._get("/v2/certificates/search", {"q": query, "page": page, "per_page": per_page})

    def get_certificate(self, fingerprint: str) -> dict:
        return self._get(f"/v2/certificates/{fingerprint}")
