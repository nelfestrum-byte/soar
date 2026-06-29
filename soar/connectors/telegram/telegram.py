from soar.connectors.base import BaseConnector


class TelegramConnector(BaseConnector):
    def __init__(self, instance_name: str, bot_token: str, base_url: str = "https://api.telegram.org"):
        super().__init__(instance_name)
        self.bot_token = bot_token
        self.base_url = base_url.rstrip("/")
        self._connected = False

    def _connect_impl(self):
        import requests
        url = f"{self.base_url}/bot{self.bot_token}/getMe"
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if not data.get("ok"):
            raise ConnectionError(f"Telegram API error: {data.get('description', 'unknown')}")
        self._logger.info(f"Bot connected: @{data['result'].get('username', 'unknown')}")
        self._connected = True

    def disconnect(self):
        self._connected = False
        self._logger.info(f"Disconnected from {self.instance_name}")

    def send_message(self, chat_id: str, text: str, parse_mode: str = "HTML") -> dict:
        self._ensure_connected()
        import requests
        url = f"{self.base_url}/bot{self.bot_token}/sendMessage"
        payload = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode}
        resp = requests.post(url, json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if not data.get("ok"):
            raise RuntimeError(f"Send failed: {data.get('description', 'unknown')}")
        return data["result"]

    def send_photo(self, chat_id: str, photo: str, caption: str = "") -> dict:
        self._ensure_connected()
        import requests
        url = f"{self.base_url}/bot{self.bot_token}/sendPhoto"
        payload = {"chat_id": chat_id, "photo": photo, "caption": caption}
        resp = requests.post(url, json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if not data.get("ok"):
            raise RuntimeError(f"Send photo failed: {data.get('description', 'unknown')}")
        return data["result"]

    def send_document(self, chat_id: str, document: str, caption: str = "") -> dict:
        self._ensure_connected()
        import requests
        url = f"{self.base_url}/bot{self.bot_token}/sendDocument"
        payload = {"chat_id": chat_id, "document": document, "caption": caption}
        resp = requests.post(url, json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if not data.get("ok"):
            raise RuntimeError(f"Send document failed: {data.get('description', 'unknown')}")
        return data["result"]

    def get_updates(self, offset: int = 0, limit: int = 100) -> list[dict]:
        self._ensure_connected()
        import requests
        url = f"{self.base_url}/bot{self.bot_token}/getUpdates"
        params = {"offset": offset, "limit": limit}
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if not data.get("ok"):
            raise RuntimeError(f"Get updates failed: {data.get('description', 'unknown')}")
        return data["result"]

    def get_chat(self, chat_id: str) -> dict:
        self._ensure_connected()
        import requests
        url = f"{self.base_url}/bot{self.bot_token}/getChat"
        resp = requests.get(url, params={"chat_id": chat_id}, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if not data.get("ok"):
            raise RuntimeError(f"Get chat failed: {data.get('description', 'unknown')}")
        return data["result"]
