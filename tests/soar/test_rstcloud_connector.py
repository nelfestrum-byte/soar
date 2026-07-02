from unittest.mock import MagicMock, patch

from soar.connectors.rstcloud.rstcloud import RstCloudConnector


def test_rstcloud_init():
    conn = RstCloudConnector(instance_name="test_rst", api_key="key123")
    assert conn.instance_name == "test_rst"
    assert conn.api_key == "key123"
    assert conn.base_url == "https://opentip.rstcloud.net"
    assert conn._session is None
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


def test_rstcloud_connect_impl():
    conn = RstCloudConnector(instance_name="test_rst", api_key="key123")
    with patch("soar.connectors.rstcloud.rstcloud.requests.Session") as mock_cls:
        conn._connect_impl()
        mock_cls.assert_called_once()
        assert conn._session is mock_cls.return_value


def test_rstcloud_disconnect():
    conn = RstCloudConnector(instance_name="test_rst", api_key="key123")
    mock_session = MagicMock()
    conn._session = mock_session
    conn._connected = True
    conn.disconnect()
    assert conn.is_connected is False
    assert conn._session is None
    mock_session.close.assert_called_once()


def test_rstcloud_check_ip():
    conn = RstCloudConnector(instance_name="test_rst", api_key="key123")
    mock_session = MagicMock()
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"ip": "1.2.3.4", "verdict": "clean"}
    mock_session.get.return_value = mock_resp
    conn._session = mock_session
    conn._connected = True

    result = conn.check_ip("1.2.3.4")
    assert result["ip"] == "1.2.3.4"
    mock_session.get.assert_called_once_with(
        "https://opentip.rstcloud.net/api/v1/ip/1.2.3.4", verify=True
    )


def test_rstcloud_check_domain():
    conn = RstCloudConnector(instance_name="test_rst", api_key="key123")
    mock_session = MagicMock()
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"domain": "example.com"}
    mock_session.get.return_value = mock_resp
    conn._session = mock_session
    conn._connected = True

    result = conn.check_domain("example.com")
    assert result["domain"] == "example.com"
    mock_session.get.assert_called_once_with(
        "https://opentip.rstcloud.net/api/v1/domain/example.com", verify=True
    )


def test_rstcloud_check_hash():
    conn = RstCloudConnector(instance_name="test_rst", api_key="key123")
    mock_session = MagicMock()
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"sha256": "abc123"}
    mock_session.get.return_value = mock_resp
    conn._session = mock_session
    conn._connected = True

    result = conn.check_hash("abc123")
    assert result["sha256"] == "abc123"
    mock_session.get.assert_called_once_with(
        "https://opentip.rstcloud.net/api/v1/file/abc123", verify=True
    )


def test_rstcloud_check_url():
    conn = RstCloudConnector(instance_name="test_rst", api_key="key123")
    mock_session = MagicMock()
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"url": "http://evil.com"}
    mock_session.get.return_value = mock_resp
    conn._session = mock_session
    conn._connected = True

    result = conn.check_url("http://evil.com")
    assert result["url"] == "http://evil.com"
    mock_session.get.assert_called_once_with(
        "https://opentip.rstcloud.net/api/v1/url",
        params={"url": "http://evil.com"},
        verify=True,
    )
