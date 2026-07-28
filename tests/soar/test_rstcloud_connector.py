from unittest.mock import patch

from soar.connectors.rstcloud.rstcloud import RstCloudConnector


def test_rstcloud_init():
    conn = RstCloudConnector(instance_name="test_rst", api_key="key123")
    assert conn.instance_name == "test_rst"
    assert conn.api_key == "key123"
    assert conn.base_url == "https://opentip.rstcloud.net"
    assert conn.is_connected is False


def test_rstcloud_init_with_options():
    conn = RstCloudConnector(
        instance_name="test_rst",
        api_key="key123",
        base_url="https://custom.example.com",
        verify_ssl=False,
    )
    assert conn.base_url == "https://custom.example.com"
    assert conn.verify_ssl is False


def test_rstcloud_connect_impl_is_noop():
    conn = RstCloudConnector(instance_name="test_rst", api_key="key123")
    conn._connect_impl()  # must not raise, nothing to set up


def test_rstcloud_ensure_connected_sets_connected_true():
    conn = RstCloudConnector(instance_name="test_rst", api_key="key123")
    with patch("soar.connectors.rstcloud.rstcloud.http_client_sync.get_json", return_value={}):
        conn.check_ip("1.2.3.4")
    assert conn.is_connected is True


def test_rstcloud_disconnect():
    conn = RstCloudConnector(instance_name="test_rst", api_key="key123")
    conn._connected = True
    conn.disconnect()
    assert conn.is_connected is False


def test_rstcloud_check_ip():
    conn = RstCloudConnector(instance_name="test_rst", api_key="key123")
    with patch(
        "soar.connectors.rstcloud.rstcloud.http_client_sync.get_json",
        return_value={"ip": "1.2.3.4", "verdict": "clean"},
    ) as mock_get:
        result = conn.check_ip("1.2.3.4")

    assert result["ip"] == "1.2.3.4"
    mock_get.assert_called_once_with(
        "https://opentip.rstcloud.net/api/v1/ip/1.2.3.4",
        headers={"Authorization": "Bearer key123", "User-Agent": "SOAR-Connector/1.0"},
        verify=True,
    )


def test_rstcloud_check_domain():
    conn = RstCloudConnector(instance_name="test_rst", api_key="key123")
    with patch(
        "soar.connectors.rstcloud.rstcloud.http_client_sync.get_json",
        return_value={"domain": "example.com"},
    ) as mock_get:
        result = conn.check_domain("example.com")

    assert result["domain"] == "example.com"
    mock_get.assert_called_once_with(
        "https://opentip.rstcloud.net/api/v1/domain/example.com",
        headers={"Authorization": "Bearer key123", "User-Agent": "SOAR-Connector/1.0"},
        verify=True,
    )


def test_rstcloud_check_hash():
    conn = RstCloudConnector(instance_name="test_rst", api_key="key123")
    with patch(
        "soar.connectors.rstcloud.rstcloud.http_client_sync.get_json",
        return_value={"sha256": "abc123"},
    ) as mock_get:
        result = conn.check_hash("abc123")

    assert result["sha256"] == "abc123"
    mock_get.assert_called_once_with(
        "https://opentip.rstcloud.net/api/v1/file/abc123",
        headers={"Authorization": "Bearer key123", "User-Agent": "SOAR-Connector/1.0"},
        verify=True,
    )


def test_rstcloud_check_url():
    conn = RstCloudConnector(instance_name="test_rst", api_key="key123")
    with patch(
        "soar.connectors.rstcloud.rstcloud.http_client_sync.get_json",
        return_value={"url": "http://evil.com"},
    ) as mock_get:
        result = conn.check_url("http://evil.com")

    assert result["url"] == "http://evil.com"
    mock_get.assert_called_once_with(
        "https://opentip.rstcloud.net/api/v1/url?url=http%3A%2F%2Fevil.com",
        headers={"Authorization": "Bearer key123", "User-Agent": "SOAR-Connector/1.0"},
        verify=True,
    )


def test_rstcloud_check_ip_verify_ssl_false():
    conn = RstCloudConnector(instance_name="test_rst", api_key="key123", verify_ssl=False)
    with patch(
        "soar.connectors.rstcloud.rstcloud.http_client_sync.get_json",
        return_value={"ip": "1.2.3.4"},
    ) as mock_get:
        conn.check_ip("1.2.3.4")

    mock_get.assert_called_once_with(
        "https://opentip.rstcloud.net/api/v1/ip/1.2.3.4",
        headers={"Authorization": "Bearer key123", "User-Agent": "SOAR-Connector/1.0"},
        verify=False,
    )
