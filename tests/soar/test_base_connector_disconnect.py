from soar.connectors.base import BaseConnector


class SimpleConnector(BaseConnector):
    def _connect_impl(self):
        pass


def test_disconnect_is_noop_by_default():
    c = SimpleConnector("test")
    c._connected = True
    c.disconnect()
    assert c.is_connected is False
