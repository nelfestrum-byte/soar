import base64
from unittest.mock import patch

from soar.connectors.wazuh.wazuh import WazuhConnector


def _basic(username: str, password: str) -> str:
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return f"Basic {token}"


def test_wazuh_init():
    conn = WazuhConnector(instance_name="test_wazuh", host="wazuh.example.com", username="admin", password="pw")
    assert conn.instance_name == "test_wazuh"
    assert conn.host == "wazuh.example.com"
    assert conn.port == 55000
    assert conn.is_connected is False


def test_wazuh_connect_impl_logs_in_and_stores_token():
    conn = WazuhConnector(instance_name="test_wazuh", host="wazuh.example.com", username="admin", password="pw")
    with patch(
        "soar.connectors.wazuh.wazuh.http_client_sync.post_json",
        return_value={"data": {"token": "tok123"}},
    ) as mock_post:
        conn._connect_impl()

    assert conn._token == "tok123"
    mock_post.assert_called_once_with(
        "https://wazuh.example.com:55000/security/user/authenticate",
        {},
        headers={"Authorization": _basic("admin", "pw")},
        verify=True,
    )


def test_wazuh_ensure_connected_sets_connected_true():
    conn = WazuhConnector(instance_name="test_wazuh", host="wazuh.example.com", username="admin", password="pw")
    with patch(
        "soar.connectors.wazuh.wazuh.http_client_sync.post_json",
        return_value={"data": {"token": "tok123"}},
    ):
        conn._ensure_connected()
    assert conn.is_connected is True


def test_wazuh_get_agents():
    conn = WazuhConnector(instance_name="test_wazuh", host="wazuh.example.com", username="admin", password="pw")
    conn._connected = True
    conn._token = "tok123"

    with patch(
        "soar.connectors.wazuh.wazuh.http_client_sync.get_json",
        return_value={"data": {"affected_items": [{"id": "001"}]}},
    ) as mock_get:
        result = conn.get_agents(status="active")

    assert result == [{"id": "001"}]
    mock_get.assert_called_once_with(
        "https://wazuh.example.com:55000/agents?status=active&limit=500",
        headers={"Authorization": "Bearer tok123"},
        verify=True,
    )


def test_wazuh_get_agent():
    conn = WazuhConnector(instance_name="test_wazuh", host="wazuh.example.com")
    conn._connected = True
    conn._token = "tok123"

    with patch(
        "soar.connectors.wazuh.wazuh.http_client_sync.get_json",
        return_value={"data": {"affected_items": [{"id": "001"}]}},
    ):
        result = conn.get_agent("001")

    assert result == {"id": "001"}


def test_wazuh_get_agent_not_found():
    conn = WazuhConnector(instance_name="test_wazuh", host="wazuh.example.com")
    conn._connected = True
    conn._token = "tok123"

    with patch(
        "soar.connectors.wazuh.wazuh.http_client_sync.get_json",
        return_value={"data": {"affected_items": []}},
    ):
        result = conn.get_agent("999")

    assert result == {}


def test_wazuh_get_alerts_with_rule_id():
    conn = WazuhConnector(instance_name="test_wazuh", host="wazuh.example.com")
    conn._connected = True
    conn._token = "tok123"

    with patch(
        "soar.connectors.wazuh.wazuh.http_client_sync.get_json",
        return_value={"data": {"affected_items": [{"rule": {"id": 100}}]}},
    ) as mock_get:
        result = conn.get_alerts(rule_id=100, limit=50)

    assert result == [{"rule": {"id": 100}}]
    mock_get.assert_called_once_with(
        "https://wazuh.example.com:55000/alerts?limit=50&rule_id=100",
        headers={"Authorization": "Bearer tok123"},
        verify=True,
    )


def test_wazuh_get_sca():
    conn = WazuhConnector(instance_name="test_wazuh", host="wazuh.example.com")
    conn._connected = True
    conn._token = "tok123"
    with patch(
        "soar.connectors.wazuh.wazuh.http_client_sync.get_json",
        return_value={"data": {"affected_items": [{"policy": "x"}]}},
    ):
        assert conn.get_sca("001") == [{"policy": "x"}]


def test_wazuh_get_vulnerabilities():
    conn = WazuhConnector(instance_name="test_wazuh", host="wazuh.example.com")
    conn._connected = True
    conn._token = "tok123"
    with patch(
        "soar.connectors.wazuh.wazuh.http_client_sync.get_json",
        return_value={"data": {"affected_items": [{"cve": "CVE-1"}]}},
    ):
        assert conn.get_vulnerabilities("001") == [{"cve": "CVE-1"}]


def test_wazuh_get_syscheck():
    conn = WazuhConnector(instance_name="test_wazuh", host="wazuh.example.com")
    conn._connected = True
    conn._token = "tok123"
    with patch(
        "soar.connectors.wazuh.wazuh.http_client_sync.get_json",
        return_value={"data": {"affected_items": [{"file": "/etc/passwd"}]}},
    ):
        assert conn.get_syscheck("001") == [{"file": "/etc/passwd"}]


def test_wazuh_get_rootcheck():
    conn = WazuhConnector(instance_name="test_wazuh", host="wazuh.example.com")
    conn._connected = True
    conn._token = "tok123"
    with patch(
        "soar.connectors.wazuh.wazuh.http_client_sync.get_json",
        return_value={"data": {"affected_items": [{"title": "check1"}]}},
    ):
        assert conn.get_rootcheck("001") == [{"title": "check1"}]


def test_wazuh_get_rules():
    conn = WazuhConnector(instance_name="test_wazuh", host="wazuh.example.com")
    conn._connected = True
    conn._token = "tok123"
    with patch(
        "soar.connectors.wazuh.wazuh.http_client_sync.get_json",
        return_value={"data": {"affected_items": [{"id": 1}]}},
    ):
        assert conn.get_rules() == [{"id": 1}]


def test_wazuh_get_decoders():
    conn = WazuhConnector(instance_name="test_wazuh", host="wazuh.example.com")
    conn._connected = True
    conn._token = "tok123"
    with patch(
        "soar.connectors.wazuh.wazuh.http_client_sync.get_json",
        return_value={"data": {"affected_items": [{"name": "json"}]}},
    ):
        assert conn.get_decoders() == [{"name": "json"}]


def test_wazuh_restart_agent_uses_put():
    conn = WazuhConnector(instance_name="test_wazuh", host="wazuh.example.com")
    conn._connected = True
    conn._token = "tok123"

    with patch(
        "soar.connectors.wazuh.wazuh.http_client_sync.put_json",
        return_value={"data": {"affected_items": ["001"]}},
    ) as mock_put:
        result = conn.restart_agent("001")

    assert result == {"data": {"affected_items": ["001"]}}
    mock_put.assert_called_once_with(
        "https://wazuh.example.com:55000/agents/001/restart",
        headers={"Authorization": "Bearer tok123"},
        verify=True,
    )
