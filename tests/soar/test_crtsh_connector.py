from unittest.mock import patch

from soar.connectors.crtsh.crtsh import CrtshConnector


def test_crtsh_init():
    conn = CrtshConnector(instance_name="test_crtsh")
    assert conn.instance_name == "test_crtsh"
    assert conn.is_connected is False


def test_crtsh_connect_impl_is_noop():
    conn = CrtshConnector(instance_name="test_crtsh")
    conn._connect_impl()  # must not raise, nothing to set up


def test_crtsh_ensure_connected_sets_connected_true():
    conn = CrtshConnector(instance_name="test_crtsh")
    with patch("soar.connectors.crtsh.crtsh.http_client_sync.get_json", return_value=[]):
        conn.search_domain("example.com")
    assert conn.is_connected is True


def test_crtsh_disconnect():
    conn = CrtshConnector(instance_name="test_crtsh")
    conn._connected = True
    conn.disconnect()
    assert conn.is_connected is False


def test_crtsh_search_domain():
    conn = CrtshConnector(instance_name="test_crtsh")
    with patch(
        "soar.connectors.crtsh.crtsh.http_client_sync.get_json",
        return_value=[
            {"id": 1, "name_value": "example.com", "issuer_ca_id": 100},
            {"id": 2, "name_value": "example.com", "issuer_ca_id": 200},
        ],
    ) as mock_get:
        result = conn.search_domain("example.com")

    assert len(result) == 2
    mock_get.assert_called_once_with(
        "https://crt.sh/q/?q=example.com&output=json",
        headers={"User-Agent": "SOAR-Connector/1.0", "Accept": "application/json"},
    )


def test_crtsh_search_domain_with_subdomains():
    conn = CrtshConnector(instance_name="test_crtsh")
    with patch(
        "soar.connectors.crtsh.crtsh.http_client_sync.get_json",
        return_value=[{"id": 1, "name_value": "*.example.com"}],
    ) as mock_get:
        result = conn.search_domain("example.com", include_subdomains=True)

    assert len(result) == 1
    mock_get.assert_called_once_with(
        "https://crt.sh/q/?q=%25.example.com&output=json",
        headers={"User-Agent": "SOAR-Connector/1.0", "Accept": "application/json"},
    )


def test_crtsh_search_identity():
    conn = CrtshConnector(instance_name="test_crtsh")
    with patch(
        "soar.connectors.crtsh.crtsh.http_client_sync.get_json",
        return_value=[{"id": 1, "common_name": "John Doe"}],
    ) as mock_get:
        result = conn.search_identity("John Doe")

    assert len(result) == 1
    mock_get.assert_called_once_with(
        "https://crt.sh/q/?identity=John+Doe&output=json",
        headers={"User-Agent": "SOAR-Connector/1.0", "Accept": "application/json"},
    )


def test_crtsh_get_certificate():
    conn = CrtshConnector(instance_name="test_crtsh")
    with patch(
        "soar.connectors.crtsh.crtsh.http_client_sync.get_json",
        return_value=[{"id": 12345, "common_name": "example.com", "not_after": "2025-01-01"}],
    ) as mock_get:
        result = conn.get_certificate(12345)

    assert result["id"] == 12345
    mock_get.assert_called_once_with(
        "https://crt.sh/d/?id=12345&output=json",
        headers={"User-Agent": "SOAR-Connector/1.0", "Accept": "application/json"},
    )


def test_crtsh_get_certificate_empty():
    conn = CrtshConnector(instance_name="test_crtsh")
    with patch("soar.connectors.crtsh.crtsh.http_client_sync.get_json", return_value=[]):
        result = conn.get_certificate(99999)

    assert result == {}


def test_crtsh_search_domain_no_results():
    conn = CrtshConnector(instance_name="test_crtsh")
    with patch("soar.connectors.crtsh.crtsh.http_client_sync.get_json", return_value=[]):
        result = conn.search_domain("nonexistent.xyz")

    assert result == []
