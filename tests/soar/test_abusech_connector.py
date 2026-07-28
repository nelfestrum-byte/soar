from unittest.mock import patch

from soar.connectors.abusech.abusech import AbuseChConnector


def test_abusech_connect_impl_is_noop():
    conn = AbuseChConnector(instance_name="test_abusech")
    conn._connect_impl()
    assert conn.is_connected is False  # BaseConnector._ensure_connected sets it, not _connect_impl


def test_abusech_ensure_connected_sets_connected_true():
    conn = AbuseChConnector(instance_name="test_abusech")
    with patch("soar.connectors.abusech.abusech.http_client_sync.post_json", return_value={}):
        conn.get_feeds()
    assert conn.is_connected is True


def test_abusech_get_malware_iocs():
    conn = AbuseChConnector(instance_name="test_abusech")
    with patch(
        "soar.connectors.abusech.abusech.http_client_sync.post_json",
        return_value={"query_status": "ok", "data": [{"ioc": "1.2.3.4"}]},
    ) as mock_post:
        result = conn.get_malware_iocs("emotet")

    assert result == [{"ioc": "1.2.3.4"}]
    mock_post.assert_called_once_with(
        AbuseChConnector.THREATFOX_API,
        {"query": "get_iocs", "malware": "emotet"},
        headers={"User-Agent": "SOAR-Connector/1.0"},
    )


def test_abusech_get_malware_iocs_no_data():
    conn = AbuseChConnector(instance_name="test_abusech")
    with patch(
        "soar.connectors.abusech.abusech.http_client_sync.post_json",
        return_value={"query_status": "no_data"},
    ):
        assert conn.get_malware_iocs() == []


def test_abusech_get_iocs_by_tag():
    conn = AbuseChConnector(instance_name="test_abusech")
    with patch(
        "soar.connectors.abusech.abusech.http_client_sync.post_json",
        return_value={"query_status": "ok", "data": [{"tag": "emotet"}]},
    ) as mock_post:
        result = conn.get_iocs_by_tag("emotet")

    assert result == [{"tag": "emotet"}]
    mock_post.assert_called_once_with(
        AbuseChConnector.THREATFOX_API,
        {"query": "taginfo", "tag": "emotet"},
        headers={"User-Agent": "SOAR-Connector/1.0"},
    )


def test_abusech_get_iocs_by_country():
    conn = AbuseChConnector(instance_name="test_abusech")
    with patch(
        "soar.connectors.abusech.abusech.http_client_sync.post_json",
        return_value={"query_status": "ok", "data": [{"country": "US"}]},
    ):
        result = conn.get_iocs_by_country("US")

    assert result == [{"country": "US"}]


def test_abusech_get_feeds():
    conn = AbuseChConnector(instance_name="test_abusech")
    with patch(
        "soar.connectors.abusech.abusech.http_client_sync.post_json",
        return_value={"query_status": "ok", "feeds": []},
    ):
        result = conn.get_feeds()

    assert result == {"query_status": "ok", "feeds": []}


def test_abusech_get_bazaar_samples():
    conn = AbuseChConnector(instance_name="test_abusech")
    with patch(
        "soar.connectors.abusech.abusech.http_client_sync.post_json",
        return_value={"data": [{"sha256": "abc"}]},
    ) as mock_post:
        result = conn.get_bazaar_samples()

    assert result == [{"sha256": "abc"}]
    mock_post.assert_called_once_with(
        AbuseChConnector.BAZAAR_API,
        {"query": "get_recent", "selector": "100"},
        headers={"User-Agent": "SOAR-Connector/1.0"},
    )


def test_abusech_get_bazaar_file():
    conn = AbuseChConnector(instance_name="test_abusech")
    with patch(
        "soar.connectors.abusech.abusech.http_client_sync.post_json",
        return_value={"data": [{"sha256": "abc123"}]},
    ):
        result = conn.get_bazaar_file("abc123")

    assert result == {"sha256": "abc123"}


def test_abusech_get_bazaar_file_hash_not_found():
    conn = AbuseChConnector(instance_name="test_abusech")
    with patch(
        "soar.connectors.abusech.abusech.http_client_sync.post_json",
        return_value={"query_status": "hash_not_found"},
    ):
        assert conn.get_bazaar_file("abc123") == {}


def test_abusech_get_urlhaus_urls_with_url():
    conn = AbuseChConnector(instance_name="test_abusech")
    with patch(
        "soar.connectors.abusech.abusech.http_client_sync.post_json",
        return_value={"urls": [{"url": "http://evil.com"}]},
    ) as mock_post:
        result = conn.get_urlhaus_urls("http://evil.com")

    assert result == [{"url": "http://evil.com"}]
    mock_post.assert_called_once_with(
        AbuseChConnector.URLHAUS_API,
        {"url": "http://evil.com"},
        headers={"User-Agent": "SOAR-Connector/1.0"},
    )


def test_abusech_get_urlhaus_urls_no_results():
    conn = AbuseChConnector(instance_name="test_abusech")
    with patch(
        "soar.connectors.abusech.abusech.http_client_sync.post_json",
        return_value={"query_status": "no_results"},
    ):
        assert conn.get_urlhaus_urls() == []


def test_abusech_get_urlhaus_host():
    conn = AbuseChConnector(instance_name="test_abusech")
    with patch(
        "soar.connectors.abusech.abusech.http_client_sync.post_json",
        return_value={"host": "evil.com"},
    ) as mock_post:
        result = conn.get_urlhaus_host("evil.com")

    assert result == {"host": "evil.com"}
    mock_post.assert_called_once_with(
        AbuseChConnector.URLHAUS_API,
        {"host": "evil.com"},
        headers={"User-Agent": "SOAR-Connector/1.0"},
    )
