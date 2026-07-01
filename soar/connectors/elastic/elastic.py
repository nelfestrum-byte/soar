from elasticsearch import Elasticsearch

from soar.connectors.base import BaseConnector


class ElasticConnector(BaseConnector):
    def __init__(
        self,
        instance_name: str,
        host: str = "localhost",
        port: int = 9200,
        api_key: str = "",
        username: str = "",
        password: str = "",
        verify_certs: bool = True,
        ca_cert: str = "",
    ):
        super().__init__(instance_name)
        self.host = host
        self.port = port
        self.api_key = api_key
        self.username = username
        self.password = password
        self.verify_certs = verify_certs
        self.ca_cert = ca_cert
        self._client: Elasticsearch | None = None

    def _connect_impl(self):
        kwargs: dict = {
            "hosts": [f"https://{self.host}:{self.port}"],
            "verify_certs": self.verify_certs,
        }
        if self.ca_cert:
            kwargs["ca_certs"] = self.ca_cert
        if self.api_key:
            kwargs["api_key"] = self.api_key
        elif self.username and self.password:
            kwargs["basic_auth"] = (self.username, self.password)
        self._client = Elasticsearch(**kwargs)

    def disconnect(self):
        if self._client:
            self._client = None
            self._connected = False
            self._logger.info(f"Disconnected from {self.instance_name}")

    def query(self, index: str, dsl: dict) -> list[dict]:
        self._ensure_connected()
        assert self._client is not None
        resp = self._client.search(index=index, body=dsl)
        return [hit["_source"] | {"_id": hit["_id"]} for hit in resp["hits"]["hits"]]

    def index(self, index: str, document: dict) -> dict:
        self._ensure_connected()
        assert self._client is not None
        return self._client.index(index=index, body=document)

    def delete(self, index: str, doc_id: str) -> dict:
        self._ensure_connected()
        assert self._client is not None
        return self._client.delete(index=index, id=doc_id)

    def bulk(self, index: str, documents: list[dict]) -> dict:
        self._ensure_connected()
        assert self._client is not None
        actions = []
        for doc in documents:
            actions.append({"index": {"_index": index}})
            actions.append(doc)
        return self._client.bulk(operations=actions)

    def get(self, index: str, doc_id: str) -> dict:
        self._ensure_connected()
        assert self._client is not None
        resp = self._client.get(index=index, id=doc_id)
        return resp["_source"] | {"_id": resp["_id"]}

    def update(self, index: str, doc_id: str, doc: dict) -> dict:
        self._ensure_connected()
        assert self._client is not None
        return self._client.update(index=index, id=doc_id, body={"doc": doc})

    def indices_exists(self, index: str) -> bool:
        self._ensure_connected()
        assert self._client is not None
        return self._client.indices.exists(index=index).meta.status == 200

    def indices_create(self, index: str, mappings: dict | None = None) -> dict:
        self._ensure_connected()
        assert self._client is not None
        kwargs: dict = {}
        if mappings:
            kwargs["mappings"] = mappings
        return self._client.indices.create(index=index, **kwargs)

    def indices_delete(self, index: str) -> dict:
        self._ensure_connected()
        assert self._client is not None
        return self._client.indices.delete(index=index)

    def cat_indices(self) -> list[dict]:
        self._ensure_connected()
        assert self._client is not None
        resp = self._client.cat.indices(format="json", h="index,health,docs.count,store.size")
        return resp

    def ilm_get_policy(self, policy: str) -> dict:
        self._ensure_connected()
        assert self._client is not None
        return self._client.ilm.get_lifecycle(policy=policy)
