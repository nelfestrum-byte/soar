from unittest.mock import MagicMock, patch

from soar.connectors.urlhaus.urlhaus import UrlhausConnector


def test_urlhaus_init():
    conn = UrlhausConnector(instance_name="test_urlhaus")
    assert conn.instance_name == "test_urlhaus"
    assert conn._session is None
    assert conn.is_connected is False


def test_urlhaus_connect_impl():
    conn = UrlhausConnector(instance_name="test_urlhaus")
    with patch("soar.connectors.urlhaus.urlhaus.requests.Session") as mock_session_cls:
        conn._connect_impl()
        mock_session_cls.assert_called_once()
        assert conn._session is mock_session_cls.return_value
        assert conn._session.headers.__setitem__.call_args is not None


def test_urlhaus_disconnect():
    conn = UrlhausConnector(instance_name="test_urlhaus")
    mock_session = MagicMock()
    conn._session = mock_session
    conn._connected = True
    conn.disconnect()
    assert conn.is_connected is False
    assert conn._session is None
    mock_session.close.assert_called_once()


def test_urlhaus_get_url_info():
    conn = UrlhausConnector(instance_name="test_urlhaus")
    mock_session = MagicMock()
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "query_status": "ok",
        "urls": [{"url": "http://evil.com", "threat": "malware_download"}],
    }
    mock_session.post.return_value = mock_resp
    conn._session = mock_session
    conn._connected = True

    result = conn.get_url_info("http://evil.com")
    assert len(result) == 1
    assert result[0]["url"] == "http://evil.com"


def test_urlhaus_get_url_info_no_results():
    conn = UrlhausConnector(instance_name="test_urlhaus")
    mock_session = MagicMock()
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"query_status": "no_results"}
    mock_session.post.return_value = mock_resp
    conn._session = mock_session
    conn._connected = True

    result = conn.get_url_info("http://safe.com")
    assert result == []


def test_urlhaus_get_host_info():
    conn = UrlhausConnector(instance_name="test_urlhaus")
    mock_session = MagicMock()
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "query_status": "ok",
        "urls": [{"host": "evil.com"}],
    }
    mock_session.post.return_value = mock_resp
    conn._session = mock_session
    conn._connected = True

    result = conn.get_host_info("evil.com")
    assert len(result) == 1
    assert result[0]["host"] == "evil.com"


def test_urlhaus_get_payload_info():
    conn = UrlhausConnector(instance_name="test_urlhaus")
    mock_session = MagicMock()
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "query_status": "ok",
        "md5_hash": "abc123",
    }
    mock_session.post.return_value = mock_resp
    conn._session = mock_session
    conn._connected = True

    result = conn.get_payload_info("abc123")
    assert result["md5_hash"] == "abc123"


def test_urlhaus_get_recent_urls():
    conn = UrlhausConnector(instance_name="test_urlhaus")
    mock_session = MagicMock()
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "query_status": "ok",
        "urls": [{"url": "http://a.com"}, {"url": "http://b.com"}],
    }
    mock_session.post.return_value = mock_resp
    conn._session = mock_session
    conn._connected = True

    result = conn.get_recent_urls(limit=50)
    assert len(result) == 2


def test_urlhaus_url_exists_true():
    conn = UrlhausConnector(instance_name="test_urlhaus")
    mock_session = MagicMock()
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"query_status": "ok", "urls": []}
    mock_session.post.return_value = mock_resp
    conn._session = mock_session
    conn._connected = True

    assert conn.url_exists("http://evil.com") is True


def test_urlhaus_url_exists_false():
    conn = UrlhausConnector(instance_name="test_urlhaus")
    mock_session = MagicMock()
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"query_status": "no_results"}
    mock_session.post.return_value = mock_resp
    conn._session = mock_session
    conn._connected = True

    assert conn.url_exists("http://safe.com") is False


def test_urlhaus_tag_url():
    conn = UrlhausConnector(instance_name="test_urlhaus")
    mock_session = MagicMock()
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"query_status": "ok", "tags_status": "success"}
    mock_session.post.return_value = mock_resp
    conn._session = mock_session
    conn._connected = True

    result = conn.tag_url("http://evil.com", tag="apt28", threat="apt")
    assert result["tags_status"] == "success"
