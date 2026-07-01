import paramiko

from soar.connectors.base import BaseConnector


class SSHConnector(BaseConnector):
    def __init__(
        self,
        instance_name: str,
        host: str,
        port: int = 22,
        username: str = "",
        password: str = "",
        key_filename: str = "",
        timeout: int = 10,
    ):
        super().__init__(instance_name)
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.key_filename = key_filename
        self.timeout = timeout
        self._client: paramiko.SSHClient | None = None

    def _connect_impl(self):
        self._client = paramiko.SSHClient()
        self._client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        connect_kwargs = {
            "hostname": self.host,
            "port": self.port,
            "username": self.username,
            "timeout": self.timeout,
        }
        if self.key_filename:
            connect_kwargs["key_filename"] = self.key_filename
        elif self.password:
            connect_kwargs["password"] = self.password
        self._client.connect(**connect_kwargs)

    def disconnect(self):
        if self._client:
            self._client.close()
            self._client = None
            self._connected = False
            self._logger.info(f"Disconnected from {self.instance_name}")

    def exec_command(self, command: str, timeout: int = 30) -> dict:
        self._ensure_connected()
        assert self._client is not None
        stdin, stdout, stderr = self._client.exec_command(command, timeout=timeout)
        exit_code = stdout.channel.recv_exit_status()
        return {
            "stdout": stdout.read().decode("utf-8", errors="replace"),
            "stderr": stderr.read().decode("utf-8", errors="replace"),
            "exit_code": exit_code,
        }

    def put_file(self, local_path: str, remote_path: str) -> bool:
        self._ensure_connected()
        assert self._client is not None
        sftp = self._client.open_sftp()
        try:
            sftp.put(local_path, remote_path)
            return True
        finally:
            sftp.close()

    def get_file(self, remote_path: str, local_path: str) -> bool:
        self._ensure_connected()
        assert self._client is not None
        sftp = self._client.open_sftp()
        try:
            sftp.get(remote_path, local_path)
            return True
        finally:
            sftp.close()

    def list_dir(self, path: str = "/") -> list[str]:
        self._ensure_connected()
        assert self._client is not None
        sftp = self._client.open_sftp()
        try:
            return sftp.listdir(path)
        finally:
            sftp.close()
