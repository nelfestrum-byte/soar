import asyncio

from aiogram import Bot
from aiogram.enums import ParseMode

from soar.connectors.base import BaseConnector


class TelegramConnector(BaseConnector):
    def __init__(self, instance_name: str, token: str, parse_mode: str = ""):
        super().__init__(instance_name)
        self.token = token
        self._parse_mode = parse_mode
        self._bot: Bot | None = None

    def _connect_impl(self):
        self._bot = Bot(token=self.token)

    def disconnect(self):
        if self._bot:
            self._bot = None
            self._connected = False
            self._logger.info(f"Disconnected from {self.instance_name}")

    def _run(self, coro):
        try:
            loop = asyncio.get_running_loop()
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                return loop.run_in_executor(pool, lambda: asyncio.run(coro))
        except RuntimeError:
            return asyncio.run(coro)

    def send_message(self, chat_id: str, text: str, parse_mode: str = "") -> dict:
        self._ensure_connected()
        assert self._bot is not None

        async def _send():
            pm = parse_mode or self._parse_mode
            kwargs = {"chat_id": chat_id, "text": text}
            if pm:
                kwargs["parse_mode"] = ParseMode(pm.upper()) if pm.upper() in ["HTML", "MARKDOWN"] else pm
            msg = await self._bot.send_message(**kwargs)
            return {"message_id": msg.message_id, "chat": {"id": msg.chat.id}}

        result = self._run(_send())
        return result if isinstance(result, dict) else {}

    def send_photo(self, chat_id: str, photo: str, caption: str = "") -> dict:
        self._ensure_connected()
        assert self._bot is not None

        async def _send():
            kwargs: dict = {"chat_id": chat_id, "photo": photo}
            if caption:
                kwargs["caption"] = caption
            msg = await self._bot.send_photo(**kwargs)
            return {"message_id": msg.message_id, "chat": {"id": msg.chat.id}}

        result = self._run(_send())
        return result if isinstance(result, dict) else {}

    def send_document(self, chat_id: str, document: str, caption: str = "") -> dict:
        self._ensure_connected()
        assert self._bot is not None

        async def _send():
            kwargs: dict = {"chat_id": chat_id, "document": document}
            if caption:
                kwargs["caption"] = caption
            msg = await self._bot.send_document(**kwargs)
            return {"message_id": msg.message_id, "chat": {"id": msg.chat.id}}

        result = self._run(_send())
        return result if isinstance(result, dict) else {}

    def send_animation(self, chat_id: str, animation: str, caption: str = "") -> dict:
        self._ensure_connected()
        assert self._bot is not None

        async def _send():
            kwargs: dict = {"chat_id": chat_id, "animation": animation}
            if caption:
                kwargs["caption"] = caption
            msg = await self._bot.send_animation(**kwargs)
            return {"message_id": msg.message_id, "chat": {"id": msg.chat.id}}

        result = self._run(_send())
        return result if isinstance(result, dict) else {}

    def get_updates(self, offset: int = 0, limit: int = 100) -> list[dict]:
        self._ensure_connected()
        assert self._bot is not None

        async def _get():
            updates = await self._bot.get_updates(offset=offset, limit=limit)
            return [
                {
                    "update_id": u.update_id,
                    "message": {
                        "message_id": u.message.message_id,
                        "chat": {"id": u.message.chat.id},
                        "text": u.message.text,
                        "from": {"id": u.message.from_user.id, "username": u.message.from_user.username} if u.message.from_user else None,
                    } if u.message else None,
                }
                for u in updates
            ]

        result = self._run(_get())
        return result if isinstance(result, list) else []

    def get_chat(self, chat_id: str) -> dict:
        self._ensure_connected()
        assert self._bot is not None

        async def _get():
            chat = await self._bot.get_chat(chat_id)
            return {"id": chat.id, "type": chat.type, "title": chat.title, "username": chat.username}

        result = self._run(_get())
        return result if isinstance(result, dict) else {}

    def get_me(self) -> dict:
        self._ensure_connected()
        assert self._bot is not None

        async def _get():
            me = await self._bot.get_me()
            return {"id": me.id, "username": me.username, "first_name": me.first_name, "is_bot": me.is_bot}

        result = self._run(_get())
        return result if isinstance(result, dict) else {}
