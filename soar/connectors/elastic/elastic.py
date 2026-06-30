from soar.connectors.base import BaseConnector


class ElasticConnector(BaseConnector):
    def __init__(self, instance_name: str, host: str, port: int = 9200, api_key: str = "", verify_certs: bool = True):
        super().__init__(instance_name)
        self.host = host
        self.port = port
        self.api_key = api_key
        self.verify_certs = verify_certs
        self._client = None

    def _connect_impl(self):
        from elasticsearch import Elasticsearch

        self._client = Elasticsearch(
            f"https://{self.host}:{self.port}",
            api_key=self.api_key,
            verify_certs=self.verify_certs,
        )

    def disconnect(self):
        if self._client:
            self._client = None
            self._connected = False
            self._logger.info(f"Disconnected from {self.instance_name}")

    def query(self, index: str, dsl: dict) -> list[dict]:
        self._ensure_connected()
        resp = self._client.search(index=index, body=dsl)  # type: ignore[attr-defined]
        return [hit["_source"] for hit in resp["hits"]["hits"]]

    def index(self, index: str, document: dict) -> dict:
        self._ensure_connected()
        return self._client.index(index=index, body=document)  # type: ignore[attr-defined, no-any-return]

    def delete(self, index: str, doc_id: str) -> dict:
        self._ensure_connected()
        return self._client.delete(index=index, id=doc_id)  # type: ignore[attr-defined, no-any-return]
