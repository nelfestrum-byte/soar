import requests

from soar.connectors.base import BaseConnector


class FreeIPAConnector(BaseConnector):
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
        login_url = f"{self._base_url}/ipa/session/login_password"
        resp = self._session.post(
            login_url,
            data={"user": self.username, "password": self.password},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=30,
        )
        resp.raise_for_status()

    def disconnect(self):
        if self._session:
            self._session.close()
            self._session = None
            self._connected = False
            self._logger.info(f"Disconnected from {self.instance_name}")

    def _api_call(self, method: str, params: dict | None = None) -> dict:
        self._ensure_connected()
        assert self._session is not None
        url = f"{self._base_url}/ipa/json"
        payload = {
            "method": method,
            "params": params or [],
            "options": {},
        }
        resp = self._session.post(url, json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if data.get("error"):
            raise Exception(f"FreeIPA error: {data['error']}")
        return data.get("result", {})

    def user_find(self, criteria: str = "") -> list[dict]:
        params = [["user_find"], {"criteria": criteria}]
        result = self._api_call("user_find", params)
        return result.get("result", [])

    def user_show(self, uid: str) -> dict:
        params = [["user_show"], {"uid": uid}]
        return self._api_call("user_show", params)

    def user_add(self, uid: str, given_name: str, sn: str, **kwargs) -> dict:
        params = [["user_add"], {"uid": uid, "givenname": given_name, "sn": sn, **kwargs}]
        return self._api_call("user_add", params)

    def user_disable(self, uid: str) -> dict:
        params = [["user_disable"], {"uid": uid}]
        return self._api_call("user_disable", params)

    def user_enable(self, uid: str) -> dict:
        params = [["user_enable"], {"uid": uid}]
        return self._api_call("user_enable", params)

    def group_find(self, criteria: str = "") -> list[dict]:
        params = [["group_find"], {"criteria": criteria}]
        result = self._api_call("group_find", params)
        return result.get("result", [])

    def group_show(self, cn: str) -> dict:
        params = [["group_show"], {"cn": cn}]
        return self._api_call("group_show", params)

    def host_find(self, criteria: str = "") -> list[dict]:
        params = [["host_find"], {"criteria": criteria}]
        result = self._api_call("host_find", params)
        return result.get("result", [])

    def host_show(self, fqdn: str) -> dict:
        params = [["host_show"], {"fqdn": fqdn}]
        return self._api_call("host_show", params)

    def hbac_rule_find(self) -> list[dict]:
        params = [["hbac_rule_find"], {}]
        result = self._api_call("hbac_rule_find", params)
        return result.get("result", [])

    def cert_find(self) -> list[dict]:
        params = [["cert_find"], {}]
        result = self._api_call("cert_find", params)
        return result.get("result", [])
