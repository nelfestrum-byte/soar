import vt

from soar.connectors.base import BaseConnector


class VirusTotalConnector(BaseConnector):
    def __init__(self, instance_name: str, api_key: str):
        super().__init__(instance_name)
        self.api_key = api_key
        self._client: vt.Client | None = None

    def _connect_impl(self):
        self._client = vt.Client(self.api_key)

    def disconnect(self):
        if self._client:
            self._client.close()
            self._client = None
            self._connected = False
            self._logger.info(f"Disconnected from {self.instance_name}")

    def get_ip_report(self, ip: str) -> dict:
        self._ensure_connected()
        assert self._client is not None
        obj = self._client.get_object(f"/ip_addresses/{ip}")
        return dict(obj)

    def get_domain_report(self, domain: str) -> dict:
        self._ensure_connected()
        assert self._client is not None
        obj = self._client.get_object(f"/domains/{domain}")
        return dict(obj)

    def get_file_report(self, hash_value: str) -> dict:
        self._ensure_connected()
        assert self._client is not None
        obj = self._client.get_object(f"/files/{hash_value}")
        return dict(obj)

    def get_url_report(self, url: str) -> dict:
        self._ensure_connected()
        assert self._client is not None
        url_id = vt.url_id(url)
        obj = self._client.get_object(f"/urls/{url_id}")
        return dict(obj)

    def upload_file(self, file_path: str) -> dict:
        self._ensure_connected()
        assert self._client is not None
        with open(file_path, "rb") as f:
            analysis = self._client.scan_file(f, wait_for_completion=True)
        return dict(analysis)

    def get_file_behaviour(self, hash_value: str) -> dict:
        self._ensure_connected()
        assert self._client is not None
        obj = self._client.get_object(f"/files/{hash_value}/behaviours")
        return dict(obj)

    def get_file_sandbox(self, hash_value: str) -> dict:
        self._ensure_connected()
        assert self._client is not None
        obj = self._client.get_object(f"/files/{hash_value}/behaviours")
        return dict(obj)
