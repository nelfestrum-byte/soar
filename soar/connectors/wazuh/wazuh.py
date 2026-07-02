import requests
import urllib3

from soar.connectors.base import BaseConnector


class WazuhConnector(BaseConnector):
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
        self._session: requests.Session | None = None

    def _connect_impl(self):
        self._session = requests.Session()
        self._session.verify = self.verify_ssl
        resp = self._session.post(
            f"https://{self.host}:{self.port}/security/user/authenticate",
            auth=(self.username, self.password),
            timeout=30,
        )
        resp.raise_for_status()
        self._token = resp.json()["data"]["token"]
        self._session.headers["Authorization"] = f"Bearer {self._token}"

    def disconnect(self):
        if self._session:
            self._session.close()
            self._session = None
            self._connected = False
            self._logger.info(f"Disconnected from {self.instance_name}")

    def _get(self, path: str, params: dict | None = None) -> dict:
        self._ensure_connected()
        assert self._session is not None
        resp = self._session.get(f"https://{self.host}:{self.port}{path}", params=params, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def _put(self, path: str, params: dict | None = None) -> dict:
        self._ensure_connected()
        assert self._session is not None
        resp = self._session.put(f"https://{self.host}:{self.port}{path}", params=params, timeout=30)
        resp.raise_for_status()
        return resp.json()

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
