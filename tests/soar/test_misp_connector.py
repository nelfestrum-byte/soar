from unittest.mock import MagicMock, patch

from soar.connectors.misp.misp import MISPConnector


def test_misp_init():
    conn = MISPConnector(instance_name="test_misp", url="https://misp.local", api_key="key123")
    assert conn.instance_name == "test_misp"
    assert conn.url == "https://misp.local"
    assert conn.api_key == "key123"
    assert conn._client is None
    assert conn.is_connected is False


def test_misp_connect_impl():
    conn = MISPConnector(instance_name="test_misp", url="https://misp.local", api_key="key123")
    with patch("soar.connectors.misp.misp.ExpandedPyMISP") as mock_cls:
        conn._connect_impl()
        mock_cls.assert_called_once_with("https://misp.local", "key123", ssl=True)
        assert conn._client is mock_cls.return_value


def test_misp_disconnect():
    conn = MISPConnector(instance_name="test_misp", url="https://misp.local", api_key="key123")
    mock_client = MagicMock()
    conn._client = mock_client
    conn._connected = True
    conn.disconnect()
    assert conn.is_connected is False
    assert conn._client is None


def test_misp_search_events():
    conn = MISPConnector(instance_name="test_misp", url="https://misp.local", api_key="key123")
    mock_client = MagicMock()
    mock_client.search.return_value = [{"Event": {"id": "1", "info": "test"}}]
    conn._client = mock_client
    conn._connected = True

    result = conn.search_events("apt28")
    assert len(result) == 1
    assert result[0]["Event"]["id"] == "1"
    mock_client.search.assert_called_once_with(value="apt28")


def test_misp_get_event():
    conn = MISPConnector(instance_name="test_misp", url="https://misp.local", api_key="key123")
    mock_client = MagicMock()
    mock_client.get_event.return_value = {"Event": {"id": "1"}}
    conn._client = mock_client
    conn._connected = True

    result = conn.get_event(1)
    assert result["Event"]["id"] == "1"
    mock_client.get_event.assert_called_once_with(1)


def test_misp_add_event():
    conn = MISPConnector(instance_name="test_misp", url="https://misp.local", api_key="key123")
    mock_client = MagicMock()
    mock_client.add_event.return_value = {"Event": {"id": "2"}}
    conn._client = mock_client
    conn._connected = True

    result = conn.add_event({"info": "test event"})
    assert result["Event"]["id"] == "2"
    mock_client.add_event.assert_called_once_with({"info": "test event"}, pythonify=True)


def test_misp_delete_event():
    conn = MISPConnector(instance_name="test_misp", url="https://misp.local", api_key="key123")
    mock_client = MagicMock()
    mock_client.delete_event.return_value = {"message": "Event deleted"}
    conn._client = mock_client
    conn._connected = True

    result = conn.delete_event(1)
    assert "deleted" in result["message"]
    mock_client.delete_event.assert_called_once_with(1)


def test_misp_search_attributes():
    conn = MISPConnector(instance_name="test_misp", url="https://misp.local", api_key="key123")
    mock_client = MagicMock()
    mock_client.search.return_value = {"response": [{"Attribute": {"id": "1"}}]}
    conn._client = mock_client
    conn._connected = True

    result = conn.search_attributes(type="ip-dst")
    assert len(result) == 1
    mock_client.search.assert_called_once_with(controller="attributes", type="ip-dst")


def test_misp_get_attribute():
    conn = MISPConnector(instance_name="test_misp", url="https://misp.local", api_key="key123")
    mock_client = MagicMock()
    mock_client.get_attribute.return_value = {"Attribute": {"id": "1", "value": "1.2.3.4"}}
    conn._client = mock_client
    conn._connected = True

    result = conn.get_attribute(1)
    assert result["Attribute"]["value"] == "1.2.3.4"


def test_misp_add_attribute():
    conn = MISPConnector(instance_name="test_misp", url="https://misp.local", api_key="key123")
    mock_client = MagicMock()
    mock_client.add_attribute.return_value = {"Attribute": {"id": "1"}}
    conn._client = mock_client
    conn._connected = True

    result = conn.add_attribute(1, type="ip-dst", value="1.2.3.4")
    assert result["Attribute"]["id"] == "1"
    mock_client.add_attribute.assert_called_once_with(1, type="ip-dst", value="1.2.3.4")


def test_misp_get_sightings():
    conn = MISPConnector(instance_name="test_misp", url="https://misp.local", api_key="key123")
    mock_client = MagicMock()
    mock_client.sighting_list.return_value = [{"Sighting": {"id": "1"}}]
    conn._client = mock_client
    conn._connected = True

    result = conn.get_sightings(1)
    assert len(result) == 1
    mock_client.sighting_list.assert_called_once_with(1)


def test_misp_add_sighting():
    conn = MISPConnector(instance_name="test_misp", url="https://misp.local", api_key="key123")
    mock_client = MagicMock()
    mock_client.sighting_add.return_value = {"Sighting": {"id": "1", "source": "analyst"}}
    conn._client = mock_client
    conn._connected = True

    result = conn.add_sighting(1, source="analyst")
    assert result["Sighting"]["source"] == "analyst"
    mock_client.sighting_add.assert_called_once_with(1, source="analyst")
