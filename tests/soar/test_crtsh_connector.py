from unittest.mock import MagicMock, patch

from soar.connectors.crtsh.crtsh import CrtshConnector


def test_crtsh_init():
    conn = CrtshConnector(instance_name="test_crtsh")
    assert conn.instance_name == "test_crtsh"
    assert conn._session is None
    assert conn.is_connected is False


def test_crtsh_connect_impl():
    conn = CrtshConnector(instance_name="test_crtsh")
    with patch("soar.connectors.crtsh.crtsh.requests.Session") as mock_cls:
        conn._connect_impl()
        mock_cls.assert_called_once()
        assert conn._session is mock_cls.return_value


def test_crtsh_disconnect():
    conn = CrtshConnector(instance_name="test_crtsh")
    mock_session = MagicMock()
    conn._session = mock_session
    conn._connected = True
    conn.disconnect()
    assert conn.is_connected is False
    assert conn._session is None
    mock_session.close.assert_called_once()


def test_crtsh_search_domain():
    conn = CrtshConnector(instance_name="test_crtsh")
    mock_session = MagicMock()
    mock_resp = MagicMock()
    mock_resp.json.return_value = [
        {"id": 1, "name_value": "example.com", "issuer_ca_id": 100},
        {"id": 2, "name_value": "example.com", "issuer_ca_id": 200},
    ]
    mock_session.get.return_value = mock_resp
    conn._session = mock_session
    conn._connected = True

    result = conn.search_domain("example.com")
    assert len(result) == 2
    mock_session.get.assert_called_once_with(
        "https://crt.sh/q/", params={"q": "example.com", "output": "json"}, timeout=30
    )


def test_crtsh_search_domain_with_subdomains():
    conn = CrtshConnector(instance_name="test_crtsh")
    mock_session = MagicMock()
    mock_resp = MagicMock()
    mock_resp.json.return_value = [{"id": 1, "name_value": "*.example.com"}]
    mock_session.get.return_value = mock_resp
    conn._session = mock_session
    conn._connected = True

    result = conn.search_domain("example.com", include_subdomains=True)
    assert len(result) == 1
    mock_session.get.assert_called_once_with(
        "https://crt.sh/q/", params={"q": "%.example.com", "output": "json"}, timeout=30
    )


def test_crtsh_search_identity():
    conn = CrtshConnector(instance_name="test_crtsh")
    mock_session = MagicMock()
    mock_resp = MagicMock()
    mock_resp.json.return_value = [{"id": 1, "common_name": "John Doe"}]
    mock_session.get.return_value = mock_resp
    conn._session = mock_session
    conn._connected = True

    result = conn.search_identity("John Doe")
    assert len(result) == 1
    mock_session.get.assert_called_once_with(
        "https://crt.sh/q/", params={"identity": "John Doe", "output": "json"}, timeout=30
    )


def test_crtsh_get_certificate():
    conn = CrtshConnector(instance_name="test_crtsh")
    mock_session = MagicMock()
    mock_resp = MagicMock()
    mock_resp.json.return_value = [{"id": 12345, "common_name": "example.com", "not_after": "2025-01-01"}]
    mock_session.get.return_value = mock_resp
    conn._session = mock_session
    conn._connected = True

    result = conn.get_certificate(12345)
    assert result["id"] == 12345
    mock_session.get.assert_called_once_with(
        "https://crt.sh/d/", params={"id": 12345, "output": "json"}, timeout=30
    )


def test_crtsh_get_certificate_empty():
    conn = CrtshConnector(instance_name="test_crtsh")
    mock_session = MagicMock()
    mock_resp = MagicMock()
    mock_resp.json.return_value = []
    mock_session.get.return_value = mock_resp
    conn._session = mock_session
    conn._connected = True

    result = conn.get_certificate(99999)
    assert result == {}


def test_crtsh_search_domain_no_results():
    conn = CrtshConnector(instance_name="test_crtsh")
    mock_session = MagicMock()
    mock_resp = MagicMock()
    mock_resp.json.return_value = []
    mock_session.get.return_value = mock_resp
    conn._session = mock_session
    conn._connected = True

    result = conn.search_domain("nonexistent.xyz")
    assert result == []
