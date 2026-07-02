from unittest.mock import MagicMock, patch

from soar.connectors.censys.censys import CensysConnector


def test_censys_init():
    conn = CensysConnector(
        instance_name="test_censys",
        api_id="id123",
        api_secret="secret456",
    )
    assert conn.instance_name == "test_censys"
    assert conn.api_id == "id123"
    assert conn.api_secret == "secret456"
    assert conn.base_url == "https://search.censys.io/api"
    assert conn._session is None
    assert conn.is_connected is False


def test_censys_init_custom_base_url():
    conn = CensysConnector(
        instance_name="test_censys",
        api_id="id123",
        api_secret="secret456",
        base_url="https://custom.censys.io/api",
    )
    assert conn.base_url == "https://custom.censys.io/api"


def test_censys_connect_impl():
    conn = CensysConnector(
        instance_name="test_censys",
        api_id="id123",
        api_secret="secret456",
    )
    with patch("soar.connectors.censys.censys.requests.Session") as mock_session_cls:
        conn._connect_impl()
        mock_session_cls.assert_called_once()
        assert conn._session is mock_session_cls.return_value
        assert conn._session.auth.username == "id123"
        assert conn._session.auth.password == "secret456"


def test_censys_disconnect():
    conn = CensysConnector(
        instance_name="test_censys",
        api_id="id123",
        api_secret="secret456",
    )
    with patch("soar.connectors.censys.censys.requests.Session"):
        conn._connect_impl()
        conn._connected = True
    conn.disconnect()
    assert conn.is_connected is False
    assert conn._session is None


def test_censys_search_hosts():
    conn = CensysConnector(
        instance_name="test_censys",
        api_id="id123",
        api_secret="secret456",
    )
    mock_session = MagicMock()
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "result": {"hits": [{"ip": "1.2.3.4"}], "total": 1},
    }
    mock_resp.raise_for_status = MagicMock()
    mock_session.get.return_value = mock_resp
    conn._session = mock_session
    conn._connected = True

    result = conn.search_hosts("services.port=443", page=1, per_page=50)
    assert "result" in result
    assert result["result"]["total"] == 1
    mock_session.get.assert_called_once_with(
        "https://search.censys.io/api/v2/hosts/search",
        params={"q": "services.port=443", "page": 1, "per_page": 50},
        timeout=30,
    )


def test_censys_get_host():
    conn = CensysConnector(
        instance_name="test_censys",
        api_id="id123",
        api_secret="secret456",
    )
    mock_session = MagicMock()
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"ip": "1.2.3.4", "services": []}
    mock_resp.raise_for_status = MagicMock()
    mock_session.get.return_value = mock_resp
    conn._session = mock_session
    conn._connected = True

    result = conn.get_host("1.2.3.4")
    assert result["ip"] == "1.2.3.4"
    mock_session.get.assert_called_once_with(
        "https://search.censys.io/api/v2/hosts/1.2.3.4",
        params=None,
        timeout=30,
    )


def test_censys_search_certificates():
    conn = CensysConnector(
        instance_name="test_censys",
        api_id="id123",
        api_secret="secret456",
    )
    mock_session = MagicMock()
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "result": {"hits": [{"fingerprint": "abc123"}], "total": 1},
    }
    mock_resp.raise_for_status = MagicMock()
    mock_session.get.return_value = mock_resp
    conn._session = mock_session
    conn._connected = True

    result = conn.search_certificates("names=example.com", page=2, per_page=25)
    assert "result" in result
    assert result["result"]["total"] == 1
    mock_session.get.assert_called_once_with(
        "https://search.censys.io/api/v2/certificates/search",
        params={"q": "names=example.com", "page": 2, "per_page": 25},
        timeout=30,
    )


def test_censys_get_certificate():
    conn = CensysConnector(
        instance_name="test_censys",
        api_id="id123",
        api_secret="secret456",
    )
    mock_session = MagicMock()
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"fingerprint": "abc123", "names": ["example.com"]}
    mock_resp.raise_for_status = MagicMock()
    mock_session.get.return_value = mock_resp
    conn._session = mock_session
    conn._connected = True

    result = conn.get_certificate("abc123")
    assert result["fingerprint"] == "abc123"
    mock_session.get.assert_called_once_with(
        "https://search.censys.io/api/v2/certificates/abc123",
        params=None,
        timeout=30,
    )
