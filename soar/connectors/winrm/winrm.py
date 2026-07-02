import winrm

from soar.connectors.base import BaseConnector


class WinRMConnector(BaseConnector):
    def __init__(
        self,
        instance_name: str,
        host: str,
        port: int = 5985,
        username: str = "",
        password: str = "",
        transport: str = "ntlm",
        verify_ssl: bool = True,
    ):
        super().__init__(instance_name)
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.transport = transport
        self.verify_ssl = verify_ssl
        self._client: winrm.Session | None = None

    def _connect_impl(self):
        scheme = "https" if self.verify_ssl else "http"
        endpoint = f"{scheme}://{self.host}:{self.port}/wsman"
        self._client = winrm.Session(
            endpoint,
            auth=(self.username, self.password),
            transport=self.transport,
            server_cert_validation="validate" if self.verify_ssl else "ignore",
        )

    def disconnect(self):
        if self._client:
            self._client = None
            self._connected = False
            self._logger.info(f"Disconnected from {self.instance_name}")

    def exec_command(self, command: str, timeout: int = 30) -> dict:
        self._ensure_connected()
        assert self._client is not None
        r = self._client.run(command, timeout=timeout)
        return {
            "stdout": r.std_out,
            "stderr": r.std_err,
            "exit_code": r.status_code,
        }

    def upload_file(self, local_path: str, remote_path: str) -> bool:
        self._ensure_connected()
        assert self._client is not None
        self._client.upload(remote_path, local_path)
        return True

    def download_file(self, remote_path: str, local_path: str) -> bool:
        self._ensure_connected()
        assert self._client is not None
        self._client.download(remote_path, local_path)
        return True

    def run_ps(self, script: str) -> dict:
        self._ensure_connected()
        assert self._client is not None
        r = self._client.run_ps(script)
        return {
            "stdout": r.std_out,
            "stderr": r.std_err,
            "exit_code": r.status_code,
        }
