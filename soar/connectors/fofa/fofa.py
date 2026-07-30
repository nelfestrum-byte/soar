import base64
from typing import ClassVar
from urllib.parse import urlencode

from soar.connectors.base import BaseConnector
from soar.tools import http_client_sync


class FofaConnector(BaseConnector):
    HIDDEN_FIELDS: ClassVar[set[str]] = {"api_key"}
    MUTATING_METHODS: ClassVar[set[str]] = set()  # all methods are read-only lookups

    DEFAULT_BASE_URL = "https://fofa.info/api/v1"

    def __init__(self, instance_name: str, email: str, api_key: str, base_url: str = ""):
        super().__init__(instance_name)
        self.email = email
        self.api_key = api_key
        self.base_url = base_url or self.DEFAULT_BASE_URL

    def _connect_impl(self):
        pass  # http_client_sync opens a connection per request, nothing to hold open

    def _get(self, path: str, params: dict | None = None) -> dict:
        self._ensure_connected()
        base_params = {"email": self.email, "key": self.api_key}
        if params:
            base_params.update(params)
        query = urlencode(base_params)
        return http_client_sync.get_json(
            f"{self.base_url}{path}?{query}", headers={"User-Agent": "SOAR-Connector/1.0"}
        )

    def search(self, query: str, fields: str = "ip,port,protocol,host", size: int = 100, page: int = 1) -> dict:
        qbase64 = base64.b64encode(query.encode()).decode()
        return self._get("/search/all", params={"qbase64": qbase64, "fields": fields, "size": size, "page": page})

    def get_host_info(self, ip: str) -> dict:
        return self._get("/host/", params={"ip": ip})

    def get_user_info(self) -> dict:
        return self._get("/info/my")
