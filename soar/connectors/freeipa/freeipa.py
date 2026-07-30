from typing import ClassVar

import httpx

from soar.connectors.base import BaseConnector
from soar.tools import http_client_sync
from soar.tools.http_client import _validate_external_url


class FreeIPAConnector(BaseConnector):
    HIDDEN_FIELDS: ClassVar[set[str]] = {"password"}
    MUTATING_METHODS: ClassVar[set[str]] = {"user_add", "user_disable", "user_enable"}

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
        self._base_url: str = ""
        self._session_cookie: str = ""

    def _connect_impl(self):
        # FreeIPA's JSON-RPC auth is a session cookie handed out by
        # /session/login_password, not a static header — incompatible with
        # SyncHttpClient's one-httpx.Client-per-call model (no cookie jar
        # persisted across calls). This one login handshake stays on a
        # direct httpx.Client (with the same SSRF guard, called by hand);
        # every subsequent JSON-RPC call goes through http_client_sync with
        # the captured cookie forwarded as a header — see
        # docs/compose/reports/entity-model-in-code.md for the full
        # reasoning (deviation from the abusech/rstcloud/kaspersky_opentip
        # pattern, which is all static-header auth).
        self._base_url = f"https://{self.host}:{self.port}"
        login_url = f"{self._base_url}/ipa/session/login_password"
        _validate_external_url(login_url)
        with httpx.Client(timeout=30, verify=self.verify_ssl) as client:
            resp = client.post(
                login_url,
                data={"user": self.username, "password": self.password},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            resp.raise_for_status()
            self._session_cookie = resp.cookies.get("ipa_session", "")

    def _headers(self) -> dict:
        if self._session_cookie:
            return {"Cookie": f"ipa_session={self._session_cookie}"}
        return {}

    def _api_call(self, method: str, params: list | None = None) -> dict:
        self._ensure_connected()
        payload = {
            "method": method,
            "params": params or [],
            "options": {},
        }
        data = http_client_sync.post_json(
            f"{self._base_url}/ipa/json", payload, headers=self._headers(), verify=self.verify_ssl,
        )
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
