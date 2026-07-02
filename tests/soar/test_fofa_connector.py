from unittest.mock import MagicMock, patch

from soar.connectors.fofa.fofa import FofaConnector


def test_fofa_init():
    conn = FofaConnector(
        instance_name="test_fofa",
        email="test@example.com",
        api_key="key123",
    )
    assert conn.instance_name == "test_fofa"
    assert conn.email == "test@example.com"
    assert conn.api_key == "key123"
    assert conn.base_url == "https://fofa.info/api/v1"
    assert conn._session is None
    assert conn.is_connected is False


def test_fofa_init_custom_base_url():
    conn = FofaConnector(
        instance_name="test_fofa",
        email="test@example.com",
        api_key="key123",
        base_url="https://custom.fofa.info/api/v1",
    )
    assert conn.base_url == "https://custom.fofa.info/api/v1"


def test_fofa_connect_impl():
    conn = FofaConnector(
        instance_name="test_fofa",
        email="test@example.com",
        api_key="key123",
    )
    with patch("soar.connectors.fofa.fofa.requests.Session") as mock_session_cls:
        conn._connect_impl()
        mock_session_cls.assert_called_once()
        assert conn._session is mock_session_cls.return_value


def test_fofa_disconnect():
    conn = FofaConnector(
        instance_name="test_fofa",
        email="test@example.com",
        api_key="key123",
    )
    with patch("soar.connectors.fofa.fofa.requests.Session"):
        conn._connect_impl()
        conn._connected = True
    conn.disconnect()
    assert conn.is_connected is False
    assert conn._session is None


def test_fofa_search():
    conn = FofaConnector(
        instance_name="test_fofa",
        email="test@example.com",
        api_key="key123",
    )
    mock_session = MagicMock()
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "results": [["1.2.3.4", "80", "http", "example.com"]],
        "size": 1,
    }
    mock_resp.raise_for_status = MagicMock()
    mock_session.get.return_value = mock_resp
    conn._session = mock_session
    conn._connected = True

    result = conn.search('title="test"', fields="ip,port,protocol,host", size=100, page=1)
    assert "results" in result
    assert result["size"] == 1
    call_args = mock_session.get.call_args
    assert call_args[0][0] == "https://fofa.info/api/v1/search/all"
    params = call_args[1]["params"]
    assert params["email"] == "test@example.com"
    assert params["key"] == "key123"
    assert params["fields"] == "ip,port,protocol,host"
    assert params["size"] == 100
    assert params["page"] == 1
    assert "qbase64" in params


def test_fofa_get_host_info():
    conn = FofaConnector(
        instance_name="test_fofa",
        email="test@example.com",
        api_key="key123",
    )
    mock_session = MagicMock()
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"ip": "1.2.3.4", "ports": [80, 443]}
    mock_resp.raise_for_status = MagicMock()
    mock_session.get.return_value = mock_resp
    conn._session = mock_session
    conn._connected = True

    result = conn.get_host_info("1.2.3.4")
    assert result["ip"] == "1.2.3.4"
    mock_session.get.assert_called_once_with(
        "https://fofa.info/api/v1/host/",
        params={"email": "test@example.com", "key": "key123", "ip": "1.2.3.4"},
        timeout=30,
    )


def test_fofa_get_user_info():
    conn = FofaConnector(
        instance_name="test_fofa",
        email="test@example.com",
        api_key="key123",
    )
    mock_session = MagicMock()
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"email": "test@example.com", "level": "vip"}
    mock_resp.raise_for_status = MagicMock()
    mock_session.get.return_value = mock_resp
    conn._session = mock_session
    conn._connected = True

    result = conn.get_user_info()
    assert result["email"] == "test@example.com"
    mock_session.get.assert_called_once_with(
        "https://fofa.info/api/v1/info/my",
        params={"email": "test@example.com", "key": "key123"},
        timeout=30,
    )
