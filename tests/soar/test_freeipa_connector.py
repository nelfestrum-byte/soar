import socket
from unittest.mock import MagicMock, patch

from soar.connectors.freeipa.freeipa import FreeIPAConnector


def _login_ctx(cookie: str = "sess123"):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.cookies = {"ipa_session": cookie}
    client = MagicMock()
    client.post.return_value = resp
    ctx = MagicMock()
    ctx.__enter__.return_value = client
    ctx.__exit__.return_value = False
    return ctx, client


def _fake_addrinfo(ip: str = "8.8.8.8"):
    return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", (ip, 443))]


def test_freeipa_init():
    conn = FreeIPAConnector(instance_name="test_ipa", host="ipa.example.com", username="admin", password="pw")
    assert conn.instance_name == "test_ipa"
    assert conn.host == "ipa.example.com"
    assert conn.port == 443
    assert conn.is_connected is False


def test_freeipa_connect_impl_logs_in_and_captures_cookie():
    conn = FreeIPAConnector(instance_name="test_ipa", host="ipa.example.com", username="admin", password="pw")
    ctx, client = _login_ctx("sess123")

    with patch("soar.connectors.freeipa.freeipa.httpx.Client", return_value=ctx) as mock_cls, \
            patch("socket.getaddrinfo", return_value=_fake_addrinfo()):
        conn._connect_impl()

    assert conn._session_cookie == "sess123"
    assert conn._base_url == "https://ipa.example.com:443"
    mock_cls.assert_called_once_with(timeout=30, verify=True)
    client.post.assert_called_once_with(
        "https://ipa.example.com:443/ipa/session/login_password",
        data={"user": "admin", "password": "pw"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )


def test_freeipa_ensure_connected_sets_connected_true():
    conn = FreeIPAConnector(instance_name="test_ipa", host="ipa.example.com", username="admin", password="pw")
    ctx, _ = _login_ctx()
    with patch("soar.connectors.freeipa.freeipa.httpx.Client", return_value=ctx), \
            patch("socket.getaddrinfo", return_value=_fake_addrinfo()):
        conn._ensure_connected()
    assert conn.is_connected is True


def test_freeipa_api_call_forwards_cookie():
    conn = FreeIPAConnector(instance_name="test_ipa", host="ipa.example.com")
    conn._connected = True
    conn._base_url = "https://ipa.example.com:443"
    conn._session_cookie = "sess123"

    with patch(
        "soar.connectors.freeipa.freeipa.http_client_sync.post_json",
        return_value={"result": {"result": [{"uid": "bob"}]}},
    ) as mock_post:
        result = conn.user_find(criteria="bob")

    assert result == [{"uid": "bob"}]
    mock_post.assert_called_once_with(
        "https://ipa.example.com:443/ipa/json",
        {"method": "user_find", "params": [["user_find"], {"criteria": "bob"}], "options": {}},
        headers={"Cookie": "ipa_session=sess123"},
        verify=True,
    )


def test_freeipa_api_call_raises_on_error():
    conn = FreeIPAConnector(instance_name="test_ipa", host="ipa.example.com")
    conn._connected = True
    conn._base_url = "https://ipa.example.com:443"
    conn._session_cookie = "sess123"

    with patch(
        "soar.connectors.freeipa.freeipa.http_client_sync.post_json",
        return_value={"error": "not found"},
    ):
        try:
            conn.user_show("nonexistent")
            raise AssertionError("expected exception")
        except Exception as e:
            assert "not found" in str(e)


def test_freeipa_user_show():
    conn = FreeIPAConnector(instance_name="test_ipa", host="ipa.example.com")
    conn._connected = True
    conn._base_url = "https://ipa.example.com:443"
    conn._session_cookie = "sess123"

    with patch(
        "soar.connectors.freeipa.freeipa.http_client_sync.post_json",
        return_value={"result": {"uid": ["bob"]}},
    ):
        result = conn.user_show("bob")

    assert result == {"uid": ["bob"]}


def test_freeipa_user_add():
    conn = FreeIPAConnector(instance_name="test_ipa", host="ipa.example.com")
    conn._connected = True
    conn._base_url = "https://ipa.example.com:443"
    conn._session_cookie = "sess123"

    with patch(
        "soar.connectors.freeipa.freeipa.http_client_sync.post_json",
        return_value={"result": {"uid": ["newuser"]}},
    ) as mock_post:
        result = conn.user_add("newuser", "New", "User")

    assert result == {"uid": ["newuser"]}
    payload = mock_post.call_args[0][1]
    assert payload["params"][1]["uid"] == "newuser"
    assert payload["params"][1]["givenname"] == "New"
    assert payload["params"][1]["sn"] == "User"


def test_freeipa_user_disable_and_enable():
    conn = FreeIPAConnector(instance_name="test_ipa", host="ipa.example.com")
    conn._connected = True
    conn._base_url = "https://ipa.example.com:443"
    conn._session_cookie = "sess123"

    with patch(
        "soar.connectors.freeipa.freeipa.http_client_sync.post_json",
        return_value={"result": {"uid": ["bob"]}},
    ) as mock_post:
        conn.user_disable("bob")
        conn.user_enable("bob")

    methods = [c.args[1]["method"] for c in mock_post.call_args_list]
    assert methods == ["user_disable", "user_enable"]


def test_freeipa_group_find():
    conn = FreeIPAConnector(instance_name="test_ipa", host="ipa.example.com")
    conn._connected = True
    conn._base_url = "https://ipa.example.com:443"
    conn._session_cookie = "sess123"

    with patch(
        "soar.connectors.freeipa.freeipa.http_client_sync.post_json",
        return_value={"result": {"result": [{"cn": "admins"}]}},
    ):
        assert conn.group_find() == [{"cn": "admins"}]


def test_freeipa_host_find_and_show():
    conn = FreeIPAConnector(instance_name="test_ipa", host="ipa.example.com")
    conn._connected = True
    conn._base_url = "https://ipa.example.com:443"
    conn._session_cookie = "sess123"

    with patch(
        "soar.connectors.freeipa.freeipa.http_client_sync.post_json",
        return_value={"result": {"result": [{"fqdn": "host1.example.com"}]}},
    ):
        assert conn.host_find() == [{"fqdn": "host1.example.com"}]

    with patch(
        "soar.connectors.freeipa.freeipa.http_client_sync.post_json",
        return_value={"result": {"fqdn": ["host1.example.com"]}},
    ):
        assert conn.host_show("host1.example.com") == {"fqdn": ["host1.example.com"]}


def test_freeipa_hbac_rule_find_and_cert_find():
    conn = FreeIPAConnector(instance_name="test_ipa", host="ipa.example.com")
    conn._connected = True
    conn._base_url = "https://ipa.example.com:443"
    conn._session_cookie = "sess123"

    with patch(
        "soar.connectors.freeipa.freeipa.http_client_sync.post_json",
        return_value={"result": {"result": [{"cn": "rule1"}]}},
    ):
        assert conn.hbac_rule_find() == [{"cn": "rule1"}]

    with patch(
        "soar.connectors.freeipa.freeipa.http_client_sync.post_json",
        return_value={"result": {"result": [{"serial_number": "1"}]}},
    ):
        assert conn.cert_find() == [{"serial_number": "1"}]
