import base64

import requests

from soar.connectors.base import BaseConnector


class FofaConnector(BaseConnector):
    DEFAULT_BASE_URL = "https://fofa.info/api/v1"

    def __init__(self, instance_name: str, email: str, api_key: str, base_url: str = ""):
        super().__init__(instance_name)
        self.email = email
        self.api_key = api_key
        self.base_url = base_url or self.DEFAULT_BASE_URL
        self._session: requests.Session | None = None

    def _connect_impl(self):
        self._session = requests.Session()
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
        base_params = {"email": self.email, "key": self.api_key}
        if params:
            base_params.update(params)
        resp = self._session.get(f"{self.base_url}{path}", params=base_params)
        resp.raise_for_status()
        return resp.json()

    def search(self, query: str, fields: str = "ip,port,protocol,host", size: int = 100, page: int = 1) -> dict:
        qbase64 = base64.b64encode(query.encode()).decode()
        return self._get("/search/all", params={"qbase64": qbase64, "fields": fields, "size": size, "page": page})

    def get_host_info(self, ip: str) -> dict:
        return self._get("/host/", params={"ip": ip})

    def get_user_info(self) -> dict:
        return self._get("/info/my")
