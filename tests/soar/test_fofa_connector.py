from unittest.mock import patch

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
    assert conn.is_connected is False


def test_fofa_init_custom_base_url():
    conn = FofaConnector(
        instance_name="test_fofa",
        email="test@example.com",
        api_key="key123",
        base_url="https://custom.fofa.info/api/v1",
    )
    assert conn.base_url == "https://custom.fofa.info/api/v1"


def test_fofa_connect_impl_is_noop():
    conn = FofaConnector(instance_name="test_fofa", email="test@example.com", api_key="key123")
    conn._connect_impl()  # must not raise, nothing to set up


def test_fofa_ensure_connected_sets_connected_true():
    conn = FofaConnector(instance_name="test_fofa", email="test@example.com", api_key="key123")
    with patch("soar.connectors.fofa.fofa.http_client_sync.get_json", return_value={}):
        conn.get_user_info()
    assert conn.is_connected is True


def test_fofa_disconnect():
    conn = FofaConnector(instance_name="test_fofa", email="test@example.com", api_key="key123")
    conn._connected = True
    conn.disconnect()
    assert conn.is_connected is False


def test_fofa_search():
    conn = FofaConnector(
        instance_name="test_fofa",
        email="test@example.com",
        api_key="key123",
    )
    with patch(
        "soar.connectors.fofa.fofa.http_client_sync.get_json",
        return_value={"results": [["1.2.3.4", "80", "http", "example.com"]], "size": 1},
    ) as mock_get:
        result = conn.search('title="test"', fields="ip,port,protocol,host", size=100, page=1)

    assert "results" in result
    assert result["size"] == 1
    url = mock_get.call_args[0][0]
    assert url.startswith("https://fofa.info/api/v1/search/all?")
    assert "email=test%40example.com" in url
    assert "key=key123" in url
    assert "fields=ip%2Cport%2Cprotocol%2Chost" in url
    assert "size=100" in url
    assert "page=1" in url
    assert "qbase64=" in url


def test_fofa_get_host_info():
    conn = FofaConnector(
        instance_name="test_fofa",
        email="test@example.com",
        api_key="key123",
    )
    with patch(
        "soar.connectors.fofa.fofa.http_client_sync.get_json",
        return_value={"ip": "1.2.3.4", "ports": [80, 443]},
    ) as mock_get:
        result = conn.get_host_info("1.2.3.4")

    assert result["ip"] == "1.2.3.4"
    mock_get.assert_called_once_with(
        "https://fofa.info/api/v1/host/?email=test%40example.com&key=key123&ip=1.2.3.4",
        headers={"User-Agent": "SOAR-Connector/1.0"},
    )


def test_fofa_get_user_info():
    conn = FofaConnector(
        instance_name="test_fofa",
        email="test@example.com",
        api_key="key123",
    )
    with patch(
        "soar.connectors.fofa.fofa.http_client_sync.get_json",
        return_value={"email": "test@example.com", "level": "vip"},
    ) as mock_get:
        result = conn.get_user_info()

    assert result["email"] == "test@example.com"
    mock_get.assert_called_once_with(
        "https://fofa.info/api/v1/info/my?email=test%40example.com&key=key123",
        headers={"User-Agent": "SOAR-Connector/1.0"},
    )
