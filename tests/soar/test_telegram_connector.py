import sys
import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture(autouse=True)
def mock_requests():
    mock_req = MagicMock()
    sys.modules["requests"] = mock_req
    yield mock_req
    sys.modules.pop("requests", None)


def test_telegram_connector_init():
    from soar.connectors.telegram.telegram import TelegramConnector
    conn = TelegramConnector(instance_name="tg_main", bot_token="123:abc")
    assert conn.instance_name == "tg_main"
    assert conn.bot_token == "123:abc"
    assert conn.base_url == "https://api.telegram.org"


def test_telegram_connector_connect(mock_requests):
    from soar.connectors.telegram.telegram import TelegramConnector
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"ok": True, "result": {"username": "testbot"}}
    mock_requests.get.return_value = mock_resp

    conn = TelegramConnector(instance_name="tg_main", bot_token="123:abc")
    conn._connect_impl()
    assert conn._connected is True
    mock_requests.get.assert_called_once()


def test_telegram_connector_send_message(mock_requests):
    from soar.connectors.telegram.telegram import TelegramConnector
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"ok": True, "result": {"message_id": 42}}
    mock_requests.post.return_value = mock_resp

    conn = TelegramConnector(instance_name="tg_main", bot_token="123:abc")
    conn._connected = True

    result = conn.send_message(chat_id="123456", text="Hello")
    assert result["message_id"] == 42
    mock_requests.post.assert_called_once()


def test_telegram_connector_send_photo(mock_requests):
    from soar.connectors.telegram.telegram import TelegramConnector
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"ok": True, "result": {"message_id": 43}}
    mock_requests.post.return_value = mock_resp

    conn = TelegramConnector(instance_name="tg_main", bot_token="123:abc")
    conn._connected = True

    result = conn.send_photo(chat_id="123456", photo="https://example.com/photo.jpg", caption="Look")
    assert result["message_id"] == 43


def test_telegram_connector_get_updates(mock_requests):
    from soar.connectors.telegram.telegram import TelegramConnector
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"ok": True, "result": [{"update_id": 1, "message": {"text": "/start"}}]}
    mock_requests.get.return_value = mock_resp

    conn = TelegramConnector(instance_name="tg_main", bot_token="123:abc")
    conn._connected = True

    updates = conn.get_updates()
    assert len(updates) == 1
    assert updates[0]["message"]["text"] == "/start"


def test_telegram_connector_disconnect():
    from soar.connectors.telegram.telegram import TelegramConnector
    conn = TelegramConnector(instance_name="tg_main", bot_token="123:abc")
    conn._connected = True
    conn.disconnect()
    assert conn._connected is False


def test_telegram_connector_send_api_error(mock_requests):
    from soar.connectors.telegram.telegram import TelegramConnector
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"ok": False, "description": "Bad Request"}
    mock_requests.post.return_value = mock_resp

    conn = TelegramConnector(instance_name="tg_main", bot_token="123:abc")
    conn._connected = True

    with pytest.raises(RuntimeError, match="Send failed"):
        conn.send_message(chat_id="123456", text="Hello")
