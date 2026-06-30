import sys
from unittest.mock import MagicMock

import pytest


@pytest.fixture(autouse=True)
def mock_vt():
    mock_vt_mod = MagicMock()
    mock_client = MagicMock()
    mock_vt_mod.Client.return_value = mock_client
    sys.modules["vt"] = mock_vt_mod
    yield
    sys.modules.pop("vt", None)


def test_vt_connector_init():
    from soar.connectors.virus_total.virus_total import VirusTotalConnector
    conn = VirusTotalConnector(instance_name="vt_main", api_key="abc123")
    assert conn.instance_name == "vt_main"
    assert conn.api_key == "abc123"
    assert conn._connected is False


def test_vt_connector_connect():
    import vt

    from soar.connectors.virus_total.virus_total import VirusTotalConnector
    conn = VirusTotalConnector(instance_name="vt_main", api_key="abc123")
    conn._connect_impl()
    vt.Client.assert_called_once_with("abc123")


def test_vt_connector_lookup_ip():
    import vt

    from soar.connectors.virus_total.virus_total import VirusTotalConnector
    mock_client = vt.Client.return_value
    mock_client.get_object.return_value = {"ip": "8.8.8.8", "country": "US"}

    conn = VirusTotalConnector(instance_name="vt_main", api_key="abc123")
    conn._ensure_connected()
    result = conn.lookup_ip("8.8.8.8")

    assert result == {"ip": "8.8.8.8", "country": "US"}
    mock_client.get_object.assert_called_once_with("/ip_addresses/8.8.8.8")


def test_vt_connector_disconnect():
    from soar.connectors.virus_total.virus_total import VirusTotalConnector
    conn = VirusTotalConnector(instance_name="vt_main", api_key="abc123")
    conn._ensure_connected()
    conn.disconnect()
    assert conn._connected is False
    assert conn._client is None
