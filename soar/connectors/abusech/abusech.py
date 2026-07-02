import requests

from soar.connectors.base import BaseConnector


class AbuseChConnector(BaseConnector):
    THREATFOX_API = "https://threatfox-api.abuse.ch/api/v1/"
    BAZAAR_API = "https://mb-api.abuse.ch/api/v1/"
    URLHAUS_API = "https://urlhaus-api.abuse.ch/v1/"

    def __init__(self, instance_name: str):
        super().__init__(instance_name)
        self._session: requests.Session | None = None

    def _connect_impl(self):
        self._session = requests.Session()
        self._session.headers["User-Agent"] = "SOAR-Connector/1.0"

    def disconnect(self):
        if self._session:
            self._session.close()
            self._session = None
            self._connected = False
            self._logger.info(f"Disconnected from {self.instance_name}")

    def _post(self, url: str, data: dict) -> dict:
        self._ensure_connected()
        assert self._session is not None
        resp = self._session.post(url, data=data, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def get_malware_iocs(self, malware: str = "") -> list[dict]:
        query = {"query": "get_iocs", "malware": malware} if malware else {"query": "get_iocs"}
        data = self._post(self.THREATFOX_API, query)
        if data.get("query_status") == "no_data":
            return []
        return data.get("data", [])

    def get_iocs_by_tag(self, tag: str) -> list[dict]:
        data = self._post(self.THREATFOX_API, {"query": "taginfo", "tag": tag})
        if data.get("query_status") == "no_data":
            return []
        return data.get("data", [])

    def get_iocs_by_country(self, country: str) -> list[dict]:
        data = self._post(self.THREATFOX_API, {"query": "countryinfo", "country": country})
        if data.get("query_status") == "no_data":
            return []
        return data.get("data", [])

    def get_feeds(self) -> dict:
        data = self._post(self.THREATFOX_API, {"query": "get_feeds"})
        return data

    def get_bazaar_samples(self, query: str = "") -> list[dict]:
        data = self._post(self.BAZAAR_API, {"query": "get_recent", "selector": "100"})
        return data.get("data", [])

    def get_bazaar_file(self, hash_value: str) -> dict:
        data = self._post(self.BAZAAR_API, {"query": "get_info", "hash": hash_value})
        if data.get("query_status") == "hash_not_found":
            return {}
        items = data.get("data", [])
        return items[0] if items else {}

    def get_urlhaus_urls(self, url: str = "") -> list[dict]:
        if url:
            data = self._post(self.URLHAUS_API, {"url": url})
        else:
            data = self._post(self.URLHAUS_API, {"limit": "100"})
        if data.get("query_status") == "no_results":
            return []
        return data.get("urls", [])

    def get_urlhaus_host(self, host: str) -> dict:
        data = self._post(self.URLHAUS_API, {"host": host})
        return data
