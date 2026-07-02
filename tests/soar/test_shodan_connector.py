from unittest.mock import MagicMock, patch

from soar.connectors.shodan.shodan import ShodanConnector


def test_shodan_init():
    conn = ShodanConnector(instance_name="test_shodan", api_key="abc123")
    assert conn.instance_name == "test_shodan"
    assert conn.api_key == "abc123"
    assert conn._client is None
    assert conn.is_connected is False


def test_shodan_connect_impl():
    conn = ShodanConnector(instance_name="test_shodan", api_key="abc123")
    with patch("soar.connectors.shodan.shodan.shodan.Shodan") as mock_cls:
        conn._connect_impl()
        mock_cls.assert_called_once_with("abc123")
        assert conn._client is mock_cls.return_value


def test_shodan_disconnect():
    conn = ShodanConnector(instance_name="test_shodan", api_key="abc123")
    with patch("soar.connectors.shodan.shodan.shodan.Shodan"):
        conn._connect_impl()
        conn._connected = True
    conn.disconnect()
    assert conn.is_connected is False
    assert conn._client is None


def test_shodan_search():
    conn = ShodanConnector(instance_name="test_shodan", api_key="abc123")
    mock_client = MagicMock()
    mock_client.search.return_value = {
        "total": 2,
        "matches": [{"ip": "1.2.3.4"}, {"ip": "5.6.7.8"}],
    }
    conn._client = mock_client
    conn._connected = True

    result = conn.search("apache", page=1, limit=1)
    assert result["total"] == 2
    assert len(result["matches"]) == 1
    mock_client.search.assert_called_once_with("apache", page=1)


def test_shodan_host_info():
    conn = ShodanConnector(instance_name="test_shodan", api_key="abc123")
    mock_client = MagicMock()
    mock_client.host.return_value = {"ip_str": "1.2.3.4", "ports": [80, 443]}
    conn._client = mock_client
    conn._connected = True

    result = conn.host_info("1.2.3.4")
    assert result["ip_str"] == "1.2.3.4"
    assert result["ports"] == [80, 443]
    mock_client.host.assert_called_once_with("1.2.3.4")


def test_shodan_dns_resolve():
    conn = ShodanConnector(instance_name="test_shodan", api_key="abc123")
    mock_client = MagicMock()
    mock_client.dns.resolve.return_value = {"google.com": ["142.250.80.46"]}
    conn._client = mock_client
    conn._connected = True

    result = conn.dns_resolve(["google.com"])
    assert result == {"google.com": ["142.250.80.46"]}
    mock_client.dns.resolve.assert_called_once_with(["google.com"])


def test_shodan_reverse_dns():
    conn = ShodanConnector(instance_name="test_shodan", api_key="abc123")
    mock_client = MagicMock()
    mock_client.dns.reverse.return_value = {"142.250.80.46": ["google.com"]}
    conn._client = mock_client
    conn._connected = True

    result = conn.reverse_dns(["142.250.80.46"])
    assert result == {"142.250.80.46": ["google.com"]}
    mock_client.dns.reverse.assert_called_once_with(["142.250.80.46"])


def test_shodan_get_my_ip():
    conn = ShodanConnector(instance_name="test_shodan", api_key="abc123")
    mock_client = MagicMock()
    mock_client.tools.myip.return_value = "1.2.3.4"
    conn._client = mock_client
    conn._connected = True

    result = conn.get_my_ip()
    assert result == {"ip": "1.2.3.4"}
    mock_client.tools.myip.assert_called_once()
