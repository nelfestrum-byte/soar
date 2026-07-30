import base64
from unittest.mock import patch

from soar.connectors.censys.censys import CensysConnector


def _auth_header(api_id: str, api_secret: str) -> str:
    token = base64.b64encode(f"{api_id}:{api_secret}".encode()).decode()
    return f"Basic {token}"


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
    assert conn.is_connected is False


def test_censys_init_custom_base_url():
    conn = CensysConnector(
        instance_name="test_censys",
        api_id="id123",
        api_secret="secret456",
        base_url="https://custom.censys.io/api",
    )
    assert conn.base_url == "https://custom.censys.io/api"


def test_censys_connect_impl_is_noop():
    conn = CensysConnector(instance_name="test_censys", api_id="id123", api_secret="secret456")
    conn._connect_impl()  # must not raise, nothing to set up


def test_censys_ensure_connected_sets_connected_true():
    conn = CensysConnector(instance_name="test_censys", api_id="id123", api_secret="secret456")
    with patch("soar.connectors.censys.censys.http_client_sync.get_json", return_value={}):
        conn.get_host("1.2.3.4")
    assert conn.is_connected is True


def test_censys_disconnect():
    conn = CensysConnector(instance_name="test_censys", api_id="id123", api_secret="secret456")
    conn._connected = True
    conn.disconnect()
    assert conn.is_connected is False


def test_censys_search_hosts():
    conn = CensysConnector(
        instance_name="test_censys",
        api_id="id123",
        api_secret="secret456",
    )
    with patch(
        "soar.connectors.censys.censys.http_client_sync.get_json",
        return_value={"result": {"hits": [{"ip": "1.2.3.4"}], "total": 1}},
    ) as mock_get:
        result = conn.search_hosts("services.port=443", page=1, per_page=50)

    assert "result" in result
    assert result["result"]["total"] == 1
    mock_get.assert_called_once_with(
        "https://search.censys.io/api/v2/hosts/search?q=services.port%3D443&page=1&per_page=50",
        headers={"Authorization": _auth_header("id123", "secret456"), "User-Agent": "SOAR-Connector/1.0"},
    )


def test_censys_get_host():
    conn = CensysConnector(
        instance_name="test_censys",
        api_id="id123",
        api_secret="secret456",
    )
    with patch(
        "soar.connectors.censys.censys.http_client_sync.get_json",
        return_value={"ip": "1.2.3.4", "services": []},
    ) as mock_get:
        result = conn.get_host("1.2.3.4")

    assert result["ip"] == "1.2.3.4"
    mock_get.assert_called_once_with(
        "https://search.censys.io/api/v2/hosts/1.2.3.4",
        headers={"Authorization": _auth_header("id123", "secret456"), "User-Agent": "SOAR-Connector/1.0"},
    )


def test_censys_search_certificates():
    conn = CensysConnector(
        instance_name="test_censys",
        api_id="id123",
        api_secret="secret456",
    )
    with patch(
        "soar.connectors.censys.censys.http_client_sync.get_json",
        return_value={"result": {"hits": [{"fingerprint": "abc123"}], "total": 1}},
    ) as mock_get:
        result = conn.search_certificates("names=example.com", page=2, per_page=25)

    assert "result" in result
    assert result["result"]["total"] == 1
    mock_get.assert_called_once_with(
        "https://search.censys.io/api/v2/certificates/search?q=names%3Dexample.com&page=2&per_page=25",
        headers={"Authorization": _auth_header("id123", "secret456"), "User-Agent": "SOAR-Connector/1.0"},
    )


def test_censys_get_certificate():
    conn = CensysConnector(
        instance_name="test_censys",
        api_id="id123",
        api_secret="secret456",
    )
    with patch(
        "soar.connectors.censys.censys.http_client_sync.get_json",
        return_value={"fingerprint": "abc123", "names": ["example.com"]},
    ) as mock_get:
        result = conn.get_certificate("abc123")

    assert result["fingerprint"] == "abc123"
    mock_get.assert_called_once_with(
        "https://search.censys.io/api/v2/certificates/abc123",
        headers={"Authorization": _auth_header("id123", "secret456"), "User-Agent": "SOAR-Connector/1.0"},
    )
