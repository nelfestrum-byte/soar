from datetime import UTC, datetime, timedelta

import requests

from soar.connectors.base import BaseConnector


class SecurityOnionConnector(BaseConnector):
    def __init__(
        self,
        instance_name: str,
        host: str,
        port: int = 443,
        username: str = "",
        password: str = "",
        verify_ssl: bool = True,
    ):
        super().__init__(instance_name)
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.verify_ssl = verify_ssl
        self._session: requests.Session | None = None
        self._base_url: str = ""

    def _connect_impl(self):
        self._base_url = f"https://{self.host}:{self.port}"
        self._session = requests.Session()
        self._session.verify = self.verify_ssl
        login_url = f"{self._base_url}/api/auth"
        resp = self._session.post(login_url, json={"username": self.username, "password": self.password})
        resp.raise_for_status()
        token = resp.json().get("token")
        if token:
            self._session.headers["Authorization"] = f"Bearer {token}"

    def disconnect(self):
        if self._session:
            self._session.close()
            self._session = None
            self._connected = False
            self._logger.info(f"Disconnected from {self.instance_name}")

    def _search(self, index: str, query: dict, size: int = 100) -> list[dict]:
        self._ensure_connected()
        assert self._session is not None
        url = f"{self._base_url}/api/elastic/{index}/_search"
        payload = {"query": query, "size": size}
        resp = self._session.post(url, json=payload)
        resp.raise_for_status()
        hits = resp.json().get("hits", {}).get("hits", [])
        return [hit["_source"] | {"_id": hit["_id"]} for hit in hits]

    def query(self, index: str, query: str, range_start: str | None = None, range_end: str | None = None, size: int = 100) -> list[dict]:
        if not range_end:
            range_end = datetime.now(UTC).isoformat()
        if not range_start:
            range_start = (datetime.now(UTC) - timedelta(hours=24)).isoformat()
        dsl = {
            "bool": {
                "must": [{"query_string": {"query": query}}],
                "filter": [{"range": {"@timestamp": {"gte": range_start, "lte": range_end}}}],
            }
        }
        return self._search(index, dsl, size)

    def get_alerts(self, index: str = "so-*-alert*", size: int = 100) -> list[dict]:
        return self._search(index, {"match_all": {}}, size)

    def get_events(self, index: str = "so-*-events*", size: int = 100) -> list[dict]:
        return self._search(index, {"match_all": {}}, size)

    def get_agents(self) -> list[dict]:
        self._ensure_connected()
        assert self._session is not None
        resp = self._session.get(f"{self._base_url}/api/agents")
        resp.raise_for_status()
        return resp.json()

    def get_detections(self) -> list[dict]:
        self._ensure_connected()
        assert self._session is not None
        resp = self._session.get(f"{self._base_url}/api/detections")
        resp.raise_for_status()
        return resp.json()

    def get_hunts(self, query: str) -> list[dict]:
        self._ensure_connected()
        assert self._session is not None
        resp = self._session.post(f"{self._base_url}/api/hunts", json={"query": query})
        resp.raise_for_status()
        return resp.json()

    def get_pcap(self, event_id: str) -> bytes:
        self._ensure_connected()
        assert self._session is not None
        resp = self._session.get(f"{self._base_url}/api/pcap/{event_id}")
        resp.raise_for_status()
        return resp.content
