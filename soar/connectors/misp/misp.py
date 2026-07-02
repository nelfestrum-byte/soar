from pymisp import ExpandedPyMISP

from soar.connectors.base import BaseConnector


class MISPConnector(BaseConnector):
    def __init__(self, instance_name: str, url: str, api_key: str, verify_ssl: bool = True):
        super().__init__(instance_name)
        self.url = url
        self.api_key = api_key
        self.verify_ssl = verify_ssl
        self._client: ExpandedPyMISP | None = None

    def _connect_impl(self):
        self._client = ExpandedPyMISP(self.url, self.api_key, ssl=self.verify_ssl)

    def disconnect(self):
        if self._client:
            self._client = None
            self._connected = False
            self._logger.info(f"Disconnected from {self.instance_name}")

    def search_events(self, keyword: str, **kwargs) -> list[dict]:
        self._ensure_connected()
        assert self._client is not None
        response = self._client.search(value=keyword, **kwargs)
        if isinstance(response, list):
            return response
        return response.get("response", []) if isinstance(response, dict) else []

    def get_event(self, event_id: int | str) -> dict:
        self._ensure_connected()
        assert self._client is not None
        result = self._client.get_event(event_id)
        return result if isinstance(result, dict) else {}

    def add_event(self, event_dict: dict) -> dict:
        self._ensure_connected()
        assert self._client is not None
        result = self._client.add_event(event_dict, pythonify=True)
        return result if isinstance(result, dict) else {}

    def delete_event(self, event_id: int | str) -> dict:
        self._ensure_connected()
        assert self._client is not None
        result = self._client.delete_event(event_id)
        return result if isinstance(result, dict) else {}

    def search_attributes(self, **kwargs) -> list[dict]:
        self._ensure_connected()
        assert self._client is not None
        response = self._client.search(controller="attributes", **kwargs)
        if isinstance(response, list):
            return response
        return response.get("response", []) if isinstance(response, dict) else []

    def get_attribute(self, attribute_id: int | str) -> dict:
        self._ensure_connected()
        assert self._client is not None
        result = self._client.get_attribute(attribute_id)
        return result if isinstance(result, dict) else {}

    def add_attribute(self, event_id: int | str, **kwargs) -> dict:
        self._ensure_connected()
        assert self._client is not None
        result = self._client.add_attribute(event_id, **kwargs)
        return result if isinstance(result, dict) else {}

    def get_sightings(self, attribute_id: int | str) -> list[dict]:
        self._ensure_connected()
        assert self._client is not None
        result = self._client.sighting_list(attribute_id)
        if isinstance(result, list):
            return result
        return result.get("response", []) if isinstance(result, dict) else []

    def add_sighting(self, attribute_id: int | str, source: str = "") -> dict:
        self._ensure_connected()
        assert self._client is not None
        result = self._client.sighting_add(attribute_id, source=source)
        return result if isinstance(result, dict) else {}
