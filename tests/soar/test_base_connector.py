import pytest

from soar.connectors.base import BaseConnector


def test_base_connector_init():
    conn = BaseConnector(instance_name="test_instance")
    assert conn.instance_name == "test_instance"
    assert conn._connected is False


def test_base_connector_is_connected():
    conn = BaseConnector(instance_name="test")
    assert conn.is_connected is False


def test_base_connector_connect_impl_raises():
    conn = BaseConnector(instance_name="test")
    with pytest.raises(NotImplementedError):
        conn._connect_impl()


def test_base_connector_disconnect_raises():
    conn = BaseConnector(instance_name="test")
    with pytest.raises(NotImplementedError):
        conn.disconnect()
