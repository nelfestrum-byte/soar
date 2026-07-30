from typing import ClassVar
from urllib.parse import urlencode

from soar.connectors.base import BaseConnector
from soar.tools import http_client_sync


class CrtshConnector(BaseConnector):
    HIDDEN_FIELDS: ClassVar[set[str]] = set()
    MUTATING_METHODS: ClassVar[set[str]] = set()  # all methods are read-only lookups

    BASE_URL = "https://crt.sh"

    def _connect_impl(self):
        pass  # http_client_sync opens a connection per request, nothing to hold open

    def _headers(self) -> dict:
        return {"User-Agent": "SOAR-Connector/1.0", "Accept": "application/json"}

    def _get(self, path: str, params: dict) -> dict | list:
        self._ensure_connected()
        query = urlencode(params)
        return http_client_sync.get_json(f"{self.BASE_URL}{path}?{query}", headers=self._headers())

    def search_domain(self, domain: str, include_subdomains: bool = False) -> list[dict]:
        query = f"%.{domain}" if include_subdomains else domain
        result = self._get("/q/", {"q": query, "output": "json"})
        return result if isinstance(result, list) else []

    def search_identity(self, identity: str) -> list[dict]:
        result = self._get("/q/", {"identity": identity, "output": "json"})
        return result if isinstance(result, list) else []

    def get_certificate(self, cert_id: int | str) -> dict:
        result = self._get("/d/", {"id": cert_id, "output": "json"})
        if isinstance(result, list):
            return result[0] if result else {}
        return result if isinstance(result, dict) else {}
