from unittest.mock import patch

from soar.connectors.kaspersky_opentip.kaspersky_opentip import KasperskyOpenTipConnector


def test_kaspersky_opentip_init():
    conn = KasperskyOpenTipConnector(instance_name="test_kot", api_key="key123")
    assert conn.instance_name == "test_kot"
    assert conn.api_key == "key123"
    assert conn.is_connected is False


def test_kaspersky_opentip_init_with_options():
    conn = KasperskyOpenTipConnector(
        instance_name="test_kot",
        api_key="key123",
        base_url="https://custom.example.com",
        verify_ssl=False,
    )
    assert conn.base_url == "https://custom.example.com"
    assert conn.verify_ssl is False


def test_kaspersky_opentip_connect_impl_is_noop():
    conn = KasperskyOpenTipConnector(instance_name="test_kot", api_key="key123")
    conn._connect_impl()  # must not raise, nothing to set up


def test_kaspersky_opentip_ensure_connected_sets_connected_true():
    conn = KasperskyOpenTipConnector(instance_name="test_kot", api_key="key123")
    with patch(
        "soar.connectors.kaspersky_opentip.kaspersky_opentip.http_client_sync.get_json",
        return_value={},
    ):
        conn.check_ip("1.2.3.4")
    assert conn.is_connected is True


def test_kaspersky_opentip_disconnect():
    conn = KasperskyOpenTipConnector(instance_name="test_kot", api_key="key123")
    conn._connected = True
    conn.disconnect()
    assert conn.is_connected is False


def test_kaspersky_opentip_check_ip():
    conn = KasperskyOpenTipConnector(instance_name="test_kot", api_key="key123")
    with patch(
        "soar.connectors.kaspersky_opentip.kaspersky_opentip.http_client_sync.get_json",
        return_value={"ip": "1.2.3.4", "verdict": {" malicious": False}},
    ) as mock_get:
        result = conn.check_ip("1.2.3.4")

    assert result["ip"] == "1.2.3.4"
    mock_get.assert_called_once_with(
        "https://opentip.kaspersky.com/api/v1/ip/1.2.3.4",
        headers={"X-Api-Key": "key123", "User-Agent": "SOAR-Connector/1.0"},
        verify=True,
    )


def test_kaspersky_opentip_check_domain():
    conn = KasperskyOpenTipConnector(instance_name="test_kot", api_key="key123")
    with patch(
        "soar.connectors.kaspersky_opentip.kaspersky_opentip.http_client_sync.get_json",
        return_value={"domain": "example.com"},
    ):
        result = conn.check_domain("example.com")

    assert result["domain"] == "example.com"


def test_kaspersky_opentip_check_url():
    conn = KasperskyOpenTipConnector(instance_name="test_kot", api_key="key123")
    with patch(
        "soar.connectors.kaspersky_opentip.kaspersky_opentip.http_client_sync.get_json",
        return_value={"url": "http://evil.com"},
    ) as mock_get:
        result = conn.check_url("http://evil.com")

    assert result["url"] == "http://evil.com"
    mock_get.assert_called_once_with(
        "https://opentip.kaspersky.com/api/v1/url?url=http%3A%2F%2Fevil.com",
        headers={"X-Api-Key": "key123", "User-Agent": "SOAR-Connector/1.0"},
        verify=True,
    )


def test_kaspersky_opentip_check_hash():
    conn = KasperskyOpenTipConnector(instance_name="test_kot", api_key="key123")
    with patch(
        "soar.connectors.kaspersky_opentip.kaspersky_opentip.http_client_sync.get_json",
        return_value={"sha256": "abc123"},
    ):
        result = conn.check_hash("abc123")

    assert result["sha256"] == "abc123"


def test_kaspersky_opentip_check_ip_verify_ssl_false():
    conn = KasperskyOpenTipConnector(instance_name="test_kot", api_key="key123", verify_ssl=False)
    with patch(
        "soar.connectors.kaspersky_opentip.kaspersky_opentip.http_client_sync.get_json",
        return_value={"ip": "1.2.3.4"},
    ) as mock_get:
        conn.check_ip("1.2.3.4")

    mock_get.assert_called_once_with(
        "https://opentip.kaspersky.com/api/v1/ip/1.2.3.4",
        headers={"X-Api-Key": "key123", "User-Agent": "SOAR-Connector/1.0"},
        verify=False,
    )
