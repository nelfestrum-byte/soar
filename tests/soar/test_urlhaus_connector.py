from unittest.mock import patch

from soar.connectors.urlhaus.urlhaus import UrlhausConnector


def test_urlhaus_init():
    conn = UrlhausConnector(instance_name="test_urlhaus")
    assert conn.instance_name == "test_urlhaus"
    assert conn.is_connected is False


def test_urlhaus_connect_impl_is_noop():
    conn = UrlhausConnector(instance_name="test_urlhaus")
    conn._connect_impl()  # must not raise, nothing to set up


def test_urlhaus_ensure_connected_sets_connected_true():
    conn = UrlhausConnector(instance_name="test_urlhaus")
    with patch("soar.connectors.urlhaus.urlhaus.http_client_sync.post_json", return_value={}):
        conn.get_url_info("http://evil.com")
    assert conn.is_connected is True


def test_urlhaus_disconnect():
    conn = UrlhausConnector(instance_name="test_urlhaus")
    conn._connected = True
    conn.disconnect()
    assert conn.is_connected is False


def test_urlhaus_get_url_info():
    conn = UrlhausConnector(instance_name="test_urlhaus")
    with patch(
        "soar.connectors.urlhaus.urlhaus.http_client_sync.post_json",
        return_value={
            "query_status": "ok",
            "urls": [{"url": "http://evil.com", "threat": "malware_download"}],
        },
    ) as mock_post:
        result = conn.get_url_info("http://evil.com")

    assert len(result) == 1
    assert result[0]["url"] == "http://evil.com"
    mock_post.assert_called_once_with(
        f"{UrlhausConnector.BASE_URL}/url/",
        {"url": "http://evil.com"},
        headers={"User-Agent": "SOAR-Connector/1.0"},
    )


def test_urlhaus_get_url_info_no_results():
    conn = UrlhausConnector(instance_name="test_urlhaus")
    with patch(
        "soar.connectors.urlhaus.urlhaus.http_client_sync.post_json",
        return_value={"query_status": "no_results"},
    ):
        result = conn.get_url_info("http://safe.com")

    assert result == []


def test_urlhaus_get_host_info():
    conn = UrlhausConnector(instance_name="test_urlhaus")
    with patch(
        "soar.connectors.urlhaus.urlhaus.http_client_sync.post_json",
        return_value={"query_status": "ok", "urls": [{"host": "evil.com"}]},
    ):
        result = conn.get_host_info("evil.com")

    assert len(result) == 1
    assert result[0]["host"] == "evil.com"


def test_urlhaus_get_payload_info():
    conn = UrlhausConnector(instance_name="test_urlhaus")
    with patch(
        "soar.connectors.urlhaus.urlhaus.http_client_sync.post_json",
        return_value={"query_status": "ok", "md5_hash": "abc123"},
    ):
        result = conn.get_payload_info("abc123")

    assert result["md5_hash"] == "abc123"


def test_urlhaus_get_recent_urls():
    conn = UrlhausConnector(instance_name="test_urlhaus")
    with patch(
        "soar.connectors.urlhaus.urlhaus.http_client_sync.post_json",
        return_value={"query_status": "ok", "urls": [{"url": "http://a.com"}, {"url": "http://b.com"}]},
    ):
        result = conn.get_recent_urls(limit=50)

    assert len(result) == 2


def test_urlhaus_url_exists_true():
    conn = UrlhausConnector(instance_name="test_urlhaus")
    with patch(
        "soar.connectors.urlhaus.urlhaus.http_client_sync.post_json",
        return_value={"query_status": "ok", "urls": []},
    ):
        assert conn.url_exists("http://evil.com") is True


def test_urlhaus_url_exists_false():
    conn = UrlhausConnector(instance_name="test_urlhaus")
    with patch(
        "soar.connectors.urlhaus.urlhaus.http_client_sync.post_json",
        return_value={"query_status": "no_results"},
    ):
        assert conn.url_exists("http://safe.com") is False


def test_urlhaus_tag_url():
    conn = UrlhausConnector(instance_name="test_urlhaus")
    with patch(
        "soar.connectors.urlhaus.urlhaus.http_client_sync.post_json",
        return_value={"query_status": "ok", "tags_status": "success"},
    ) as mock_post:
        result = conn.tag_url("http://evil.com", tag="apt28", threat="apt")

    assert result["tags_status"] == "success"
    mock_post.assert_called_once_with(
        f"{UrlhausConnector.BASE_URL}/url/",
        {"url": "http://evil.com", "threat": "apt", "tags": "apt28"},
        headers={"User-Agent": "SOAR-Connector/1.0"},
    )
