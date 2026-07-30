from datetime import UTC, datetime, timedelta
from typing import ClassVar

import httpx

from soar.connectors.base import BaseConnector
from soar.tools import http_client_sync


class SecurityOnionConnector(BaseConnector):
    HIDDEN_FIELDS: ClassVar[set[str]] = {"password"}
    MUTATING_METHODS: ClassVar[set[str]] = set()  # all methods are read-only lookups

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
        self._token: str = ""
        self._base_url: str = ""

    def _connect_impl(self):
        self._base_url = f"https://{self.host}:{self.port}"
        data = http_client_sync.post_json(
            f"{self._base_url}/api/auth",
            {"username": self.username, "password": self.password},
            verify=self.verify_ssl,
        )
        self._token = data.get("token", "")

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._token}"} if self._token else {}

    def _search(self, index: str, query: dict, size: int = 100) -> list[dict]:
        self._ensure_connected()
        url = f"{self._base_url}/api/elastic/{index}/_search"
        payload = {"query": query, "size": size}
        data = http_client_sync.post_json(url, payload, headers=self._headers(), verify=self.verify_ssl)
        hits = data.get("hits", {}).get("hits", [])
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
        return http_client_sync.get_json(
            f"{self._base_url}/api/agents", headers=self._headers(), verify=self.verify_ssl
        )

    def get_detections(self) -> list[dict]:
        self._ensure_connected()
        return http_client_sync.get_json(
            f"{self._base_url}/api/detections", headers=self._headers(), verify=self.verify_ssl
        )

    def get_hunts(self, query: str) -> list[dict]:
        self._ensure_connected()
        return http_client_sync.post_json(
            f"{self._base_url}/api/hunts", {"query": query}, headers=self._headers(), verify=self.verify_ssl
        )

    def get_pcap(self, event_id: str) -> bytes:
        # Binary response — SyncHttpClient.get_json always parses JSON, so
        # this one call stays on a direct httpx.Client rather than the
        # shared facade (see docs/compose/reports/entity-model-in-code.md
        # for why). self._base_url is operator config, not per-call input,
        # so it carries the same trust level as the rest of this
        # connector's host/port — no SSRF guard gap introduced.
        self._ensure_connected()
        with httpx.Client(timeout=30, verify=self.verify_ssl) as client:
            resp = client.get(f"{self._base_url}/api/pcap/{event_id}", headers=self._headers())
            resp.raise_for_status()
            return resp.content
