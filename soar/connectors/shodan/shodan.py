import shodan

from soar.connectors.base import BaseConnector


class ShodanConnector(BaseConnector):
    def __init__(self, instance_name: str, api_key: str):
        super().__init__(instance_name)
        self.api_key = api_key
        self._client: shodan.Shodan | None = None

    def _connect_impl(self):
        self._client = shodan.Shodan(self.api_key)

    def disconnect(self):
        if self._client:
            self._client = None
            self._connected = False
            self._logger.info(f"Disconnected from {self.instance_name}")

    def search(self, query: str, page: int = 1, limit: int = 100) -> dict:
        self._ensure_connected()
        assert self._client is not None
        result = self._client.search(query, page=page)
        matches = result.get("matches", [])[:limit]
        return {
            "total": result.get("total", 0),
            "matches": matches,
        }

    def host_info(self, ip: str) -> dict:
        self._ensure_connected()
        assert self._client is not None
        host = self._client.host(ip)
        return dict(host)

    def dns_resolve(self, hostnames: list[str]) -> dict:
        self._ensure_connected()
        assert self._client is not None
        result = self._client.dns.resolve(hostnames)
        return result

    def reverse_dns(self, ips: list[str]) -> dict:
        self._ensure_connected()
        assert self._client is not None
        result = self._client.dns.reverse(ips)
        return result

    def get_my_ip(self) -> dict:
        self._ensure_connected()
        assert self._client is not None
        result = self._client.tools.myip()
        return {"ip": result}
