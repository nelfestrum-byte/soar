from soar.logger import get_logger


class BaseConnector:
    def __init__(self, instance_name: str, **params):
        self.instance_name = instance_name
        self._connected = False
        self._logger = get_logger(f"connector.{instance_name}")

    def _connect_impl(self) -> None:
        raise NotImplementedError

    def _ensure_connected(self) -> None:
        if not self._connected:
            self._connect_impl()
            self._connected = True
            self._logger.info(f"Connected to {self.instance_name}")

    def disconnect(self) -> None:
        self._connected = False
        self._logger.info(f"Disconnected from {self.instance_name}")

    @property
    def is_connected(self) -> bool:
        return self._connected
