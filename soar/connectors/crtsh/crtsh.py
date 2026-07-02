import requests

from soar.connectors.base import BaseConnector


class CrtshConnector(BaseConnector):
    BASE_URL = "https://crt.sh"

    def __init__(self, instance_name: str):
        super().__init__(instance_name)
        self._session: requests.Session | None = None

    def _connect_impl(self):
        self._session = requests.Session()
        self._session.headers["User-Agent"] = "SOAR-Connector/1.0"
        self._session.headers["Accept"] = "application/json"

    def disconnect(self):
        if self._session:
            self._session.close()
            self._session = None
            self._connected = False
            self._logger.info(f"Disconnected from {self.instance_name}")

    def _get(self, path: str, params: dict | None = None) -> dict | list:
        self._ensure_connected()
        assert self._session is not None
        resp = self._session.get(f"{self.BASE_URL}{path}", params=params, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def search_domain(self, domain: str, include_subdomains: bool = False) -> list[dict]:
        query = f"%.{domain}" if include_subdomains else domain
        result = self._get("/q/", params={"q": query, "output": "json"})
        return result if isinstance(result, list) else []

    def search_identity(self, identity: str) -> list[dict]:
        result = self._get("/q/", params={"identity": identity, "output": "json"})
        return result if isinstance(result, list) else []

    def get_certificate(self, cert_id: int | str) -> dict:
        result = self._get("/d/", params={"id": cert_id, "output": "json"})
        if isinstance(result, list):
            return result[0] if result else {}
        return result if isinstance(result, dict) else {}
