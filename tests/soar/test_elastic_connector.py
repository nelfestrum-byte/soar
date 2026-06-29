import sys
import pytest
from unittest.mock import MagicMock


@pytest.fixture(autouse=True)
def mock_elasticsearch():
    mock_es = MagicMock()
    mock_client = MagicMock()
    mock_es.return_value = mock_client
    sys.modules["elasticsearch"] = mock_es
    yield
    sys.modules.pop("elasticsearch", None)


def test_elastic_connector_init():
    from soar.connectors.elastic.elastic import ElasticConnector
    conn = ElasticConnector(instance_name="elastic1", host="10.0.0.1", port=9200, api_key="key123")
    assert conn.instance_name == "elastic1"
    assert conn.host == "10.0.0.1"
    assert conn.port == 9200
    assert conn.api_key == "key123"
    assert conn._connected is False


def test_elastic_connector_connect_impl():
    from soar.connectors.elastic.elastic import ElasticConnector
    conn = ElasticConnector(instance_name="elastic1", host="10.0.0.1", api_key="key")
    conn._connect_impl()
    import elasticsearch
    elasticsearch.Elasticsearch.assert_called_once()


def test_elastic_connector_query():
    from soar.connectors.elastic.elastic import ElasticConnector
    import elasticsearch
    mock_client = elasticsearch.Elasticsearch.return_value
    mock_client.search.return_value = {"hits": {"hits": [{"_source": {"alert": "test"}}]}}

    conn = ElasticConnector(instance_name="elastic1", host="10.0.0.1", api_key="key")
    conn._ensure_connected()
    result = conn.query("alerts", {"query": {"match_all": {}}})

    assert result == [{"alert": "test"}]
    mock_client.search.assert_called_once_with(index="alerts", body={"query": {"match_all": {}}})


def test_elastic_connector_disconnect():
    from soar.connectors.elastic.elastic import ElasticConnector
    conn = ElasticConnector(instance_name="elastic1", host="10.0.0.1", api_key="key")
    conn._ensure_connected()
    conn.disconnect()
    assert conn._connected is False
    assert conn._client is None
