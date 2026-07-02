import requests

from soar.connectors.base import BaseConnector


class UrlhausConnector(BaseConnector):
    BASE_URL = "https://urlhaus-api.abuse.ch/v1"

    def __init__(self, instance_name: str):
        super().__init__(instance_name)
        self._session: requests.Session | None = None

    def _connect_impl(self):
        self._session = requests.Session()
        self._session.headers["User-Agent"] = "SOAR-Connector/1.0"
        self._session.headers["Content-Type"] = "application/x-www-form-urlencoded"

    def disconnect(self):
        if self._session:
            self._session.close()
            self._session = None
            self._connected = False
            self._logger.info(f"Disconnected from {self.instance_name}")

    def _post(self, data: dict) -> dict:
        self._ensure_connected()
        assert self._session is not None
        resp = self._session.post(f"{self.BASE_URL}/url/", data=data, timeout=30)
        resp.raise_for_status()
        return resp.json()

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
        assert self._session is not None
        resp = self._session.post(
            f"{self.BASE_URL}/url/",
            data={"url": url, "threat": threat, "tags": tag},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()
