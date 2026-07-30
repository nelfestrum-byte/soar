import base64
from typing import ClassVar
from urllib.parse import urlencode

from soar.connectors.base import BaseConnector
from soar.tools import http_client_sync


class WazuhConnector(BaseConnector):
    HIDDEN_FIELDS: ClassVar[set[str]] = {"password"}
    MUTATING_METHODS: ClassVar[set[str]] = {"restart_agent"}

    def __init__(
        self,
        instance_name: str,
        host: str,
        port: int = 55000,
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

    def _connect_impl(self):
        # HTTPBasicAuth-equivalent header, built by hand — SyncHttpClient
        # takes headers, not a requests.auth tuple.
        basic = base64.b64encode(f"{self.username}:{self.password}".encode()).decode()
        data = http_client_sync.post_json(
            f"https://{self.host}:{self.port}/security/user/authenticate",
            {},
            headers={"Authorization": f"Basic {basic}"},
            verify=self.verify_ssl,
        )
        self._token = data["data"]["token"]

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._token}"}

    def _get(self, path: str, params: dict | None = None) -> dict:
        self._ensure_connected()
        url = f"https://{self.host}:{self.port}{path}"
        if params:
            url += f"?{urlencode(params)}"
        return http_client_sync.get_json(url, headers=self._headers(), verify=self.verify_ssl)

    def _put(self, path: str, params: dict | None = None) -> dict:
        self._ensure_connected()
        url = f"https://{self.host}:{self.port}{path}"
        if params:
            url += f"?{urlencode(params)}"
        return http_client_sync.put_json(url, headers=self._headers(), verify=self.verify_ssl)

    def get_agents(self, status: str = "active") -> list[dict]:
        data = self._get("/agents", params={"status": status, "limit": 500})
        return data.get("data", {}).get("affected_items", [])

    def get_agent(self, agent_id: str) -> dict:
        data = self._get(f"/agents/{agent_id}")
        items = data.get("data", {}).get("affected_items", [])
        return items[0] if items else {}

    def get_alerts(self, rule_id: int | None = None, limit: int = 100) -> list[dict]:
        params: dict = {"limit": limit}
        if rule_id:
            params["rule_id"] = rule_id
        data = self._get("/alerts", params=params)
        return data.get("data", {}).get("affected_items", [])

    def get_sca(self, agent_id: str) -> list[dict]:
        data = self._get(f"/sca/{agent_id}")
        return data.get("data", {}).get("affected_items", [])

    def get_vulnerabilities(self, agent_id: str) -> list[dict]:
        data = self._get(f"/vulnerability/{agent_id}")
        return data.get("data", {}).get("affected_items", [])

    def get_syscheck(self, agent_id: str) -> list[dict]:
        data = self._get(f"/syscheck/{agent_id}")
        return data.get("data", {}).get("affected_items", [])

    def get_rootcheck(self, agent_id: str) -> list[dict]:
        data = self._get(f"/rootcheck/{agent_id}")
        return data.get("data", {}).get("affected_items", [])

    def get_rules(self) -> list[dict]:
        data = self._get("/rules")
        return data.get("data", {}).get("affected_items", [])

    def get_decoders(self) -> list[dict]:
        data = self._get("/decoders")
        return data.get("data", {}).get("affected_items", [])

    def restart_agent(self, agent_id: str) -> dict:
        return self._put(f"/agents/{agent_id}/restart")
