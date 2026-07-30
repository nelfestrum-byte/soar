from unittest.mock import MagicMock, patch

from soar.connectors.security_onion.security_onion import SecurityOnionConnector


def test_security_onion_init():
    conn = SecurityOnionConnector(instance_name="test_so", host="so.example.com", username="admin", password="pw")
    assert conn.instance_name == "test_so"
    assert conn.host == "so.example.com"
    assert conn.port == 443
    assert conn.is_connected is False


def test_security_onion_connect_impl_logs_in_and_stores_token():
    conn = SecurityOnionConnector(instance_name="test_so", host="so.example.com", username="admin", password="pw")
    with patch(
        "soar.connectors.security_onion.security_onion.http_client_sync.post_json",
        return_value={"token": "tok123"},
    ) as mock_post:
        conn._connect_impl()

    assert conn._token == "tok123"
    assert conn._base_url == "https://so.example.com:443"
    mock_post.assert_called_once_with(
        "https://so.example.com:443/api/auth",
        {"username": "admin", "password": "pw"},
        verify=True,
    )


def test_security_onion_ensure_connected_sets_connected_true():
    conn = SecurityOnionConnector(instance_name="test_so", host="so.example.com", username="admin", password="pw")
    with patch(
        "soar.connectors.security_onion.security_onion.http_client_sync.post_json",
        return_value={"token": "tok123"},
    ):
        conn._ensure_connected()
    assert conn.is_connected is True


def test_security_onion_get_alerts():
    conn = SecurityOnionConnector(instance_name="test_so", host="so.example.com", username="admin", password="pw")
    conn._connected = True
    conn._base_url = "https://so.example.com:443"
    conn._token = "tok123"

    with patch(
        "soar.connectors.security_onion.security_onion.http_client_sync.post_json",
        return_value={"hits": {"hits": [{"_id": "1", "_source": {"rule": "x"}}]}},
    ) as mock_post:
        result = conn.get_alerts(size=10)

    assert result == [{"rule": "x", "_id": "1"}]
    mock_post.assert_called_once_with(
        "https://so.example.com:443/api/elastic/so-*-alert*/_search",
        {"query": {"match_all": {}}, "size": 10},
        headers={"Authorization": "Bearer tok123"},
        verify=True,
    )


def test_security_onion_get_events():
    conn = SecurityOnionConnector(instance_name="test_so", host="so.example.com")
    conn._connected = True
    conn._base_url = "https://so.example.com:443"
    conn._token = "tok123"

    with patch(
        "soar.connectors.security_onion.security_onion.http_client_sync.post_json",
        return_value={"hits": {"hits": []}},
    ):
        result = conn.get_events()

    assert result == []


def test_security_onion_query_builds_dsl():
    conn = SecurityOnionConnector(instance_name="test_so", host="so.example.com")
    conn._connected = True
    conn._base_url = "https://so.example.com:443"
    conn._token = "tok123"

    with patch(
        "soar.connectors.security_onion.security_onion.http_client_sync.post_json",
        return_value={"hits": {"hits": []}},
    ) as mock_post:
        conn.query("so-*", "malware", range_start="2026-01-01T00:00:00Z", range_end="2026-01-02T00:00:00Z")

    payload = mock_post.call_args[0][1]
    assert payload["query"]["bool"]["must"] == [{"query_string": {"query": "malware"}}]
    assert payload["query"]["bool"]["filter"][0]["range"]["@timestamp"]["gte"] == "2026-01-01T00:00:00Z"


def test_security_onion_get_agents():
    conn = SecurityOnionConnector(instance_name="test_so", host="so.example.com")
    conn._connected = True
    conn._base_url = "https://so.example.com:443"
    conn._token = "tok123"

    with patch(
        "soar.connectors.security_onion.security_onion.http_client_sync.get_json",
        return_value=[{"id": "agent1"}],
    ) as mock_get:
        result = conn.get_agents()

    assert result == [{"id": "agent1"}]
    mock_get.assert_called_once_with(
        "https://so.example.com:443/api/agents", headers={"Authorization": "Bearer tok123"}, verify=True,
    )


def test_security_onion_get_detections():
    conn = SecurityOnionConnector(instance_name="test_so", host="so.example.com")
    conn._connected = True
    conn._base_url = "https://so.example.com:443"
    conn._token = "tok123"

    with patch(
        "soar.connectors.security_onion.security_onion.http_client_sync.get_json",
        return_value=[{"id": "det1"}],
    ):
        result = conn.get_detections()

    assert result == [{"id": "det1"}]


def test_security_onion_get_hunts():
    conn = SecurityOnionConnector(instance_name="test_so", host="so.example.com")
    conn._connected = True
    conn._base_url = "https://so.example.com:443"
    conn._token = "tok123"

    with patch(
        "soar.connectors.security_onion.security_onion.http_client_sync.post_json",
        return_value=[{"hunt": "x"}],
    ) as mock_post:
        result = conn.get_hunts("suspicious")

    assert result == [{"hunt": "x"}]
    mock_post.assert_called_once_with(
        "https://so.example.com:443/api/hunts",
        {"query": "suspicious"},
        headers={"Authorization": "Bearer tok123"},
        verify=True,
    )


def test_security_onion_get_pcap_uses_direct_httpx_client():
    conn = SecurityOnionConnector(instance_name="test_so", host="so.example.com")
    conn._connected = True
    conn._base_url = "https://so.example.com:443"
    conn._token = "tok123"

    resp = MagicMock()
    resp.content = b"pcap-bytes"
    resp.raise_for_status = MagicMock()
    client = MagicMock()
    client.get.return_value = resp
    ctx = MagicMock()
    ctx.__enter__.return_value = client
    ctx.__exit__.return_value = False

    with patch("soar.connectors.security_onion.security_onion.httpx.Client", return_value=ctx) as mock_cls:
        result = conn.get_pcap("evt1")

    assert result == b"pcap-bytes"
    mock_cls.assert_called_once_with(timeout=30, verify=True)
    client.get.assert_called_once_with(
        "https://so.example.com:443/api/pcap/evt1", headers={"Authorization": "Bearer tok123"}
    )
