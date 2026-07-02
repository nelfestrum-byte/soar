from unittest.mock import MagicMock, patch

from soar.connectors.kaspersky_opentip.kaspersky_opentip import KasperskyOpenTipConnector


def test_kaspersky_opentip_init():
    conn = KasperskyOpenTipConnector(instance_name="test_kot", api_key="key123")
    assert conn.instance_name == "test_kot"
    assert conn.api_key == "key123"
    assert conn._session is None
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


def test_kaspersky_opentip_connect_impl():
    conn = KasperskyOpenTipConnector(instance_name="test_kot", api_key="key123")
    with patch("soar.connectors.kaspersky_opentip.kaspersky_opentip.requests.Session") as mock_cls:
        conn._connect_impl()
        mock_cls.assert_called_once()
        assert conn._session is mock_cls.return_value


def test_kaspersky_opentip_disconnect():
    conn = KasperskyOpenTipConnector(instance_name="test_kot", api_key="key123")
    mock_session = MagicMock()
    conn._session = mock_session
    conn._connected = True
    conn.disconnect()
    assert conn.is_connected is False
    assert conn._session is None
    mock_session.close.assert_called_once()


def test_kaspersky_opentip_check_ip():
    conn = KasperskyOpenTipConnector(instance_name="test_kot", api_key="key123")
    mock_session = MagicMock()
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"ip": "1.2.3.4", "verdict": {" malicious": False }}
    mock_session.get.return_value = mock_resp
    conn._session = mock_session
    conn._connected = True

    result = conn.check_ip("1.2.3.4")
    assert result["ip"] == "1.2.3.4"
    mock_session.get.assert_called_once_with(
        "https://opentip.kaspersky.com/api/v1/ip/1.2.3.4", verify=True, timeout=30
    )


def test_kaspersky_opentip_check_domain():
    conn = KasperskyOpenTipConnector(instance_name="test_kot", api_key="key123")
    mock_session = MagicMock()
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"domain": "example.com"}
    mock_session.get.return_value = mock_resp
    conn._session = mock_session
    conn._connected = True

    result = conn.check_domain("example.com")
    assert result["domain"] == "example.com"


def test_kaspersky_opentip_check_url():
    conn = KasperskyOpenTipConnector(instance_name="test_kot", api_key="key123")
    mock_session = MagicMock()
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"url": "http://evil.com"}
    mock_session.get.return_value = mock_resp
    conn._session = mock_session
    conn._connected = True

    result = conn.check_url("http://evil.com")
    assert result["url"] == "http://evil.com"
    mock_session.get.assert_called_once_with(
        "https://opentip.kaspersky.com/api/v1/url",
        params={"url": "http://evil.com"},
        verify=True,
        timeout=30,
    )


def test_kaspersky_opentip_check_hash():
    conn = KasperskyOpenTipConnector(instance_name="test_kot", api_key="key123")
    mock_session = MagicMock()
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"sha256": "abc123"}
    mock_session.get.return_value = mock_resp
    conn._session = mock_session
    conn._connected = True

    result = conn.check_hash("abc123")
    assert result["sha256"] == "abc123"
