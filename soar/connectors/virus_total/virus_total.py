from soar.connectors.base import BaseConnector


class VirusTotalConnector(BaseConnector):
    def __init__(self, instance_name: str, api_key: str):
        super().__init__(instance_name)
        self.api_key = api_key
        self._client = None

    def _connect_impl(self):
        import vt

        self._client = vt.Client(self.api_key)

    def disconnect(self):
        if self._client:
            self._client.close()
            self._client = None
            self._connected = False
            self._logger.info(f"Disconnected from {self.instance_name}")

    def lookup_ip(self, ip: str) -> dict:
        self._ensure_connected()
        obj = self._client.get_object(f"/ip_addresses/{ip}")  # type: ignore[attr-defined]
        return dict(obj)

    def lookup_domain(self, domain: str) -> dict:
        self._ensure_connected()
        obj = self._client.get_object(f"/domains/{domain}")  # type: ignore[attr-defined]
        return dict(obj)

    def lookup_file(self, file_hash: str) -> dict:
        self._ensure_connected()
        obj = self._client.get_object(f"/files/{file_hash}")  # type: ignore[attr-defined]
        return dict(obj)
