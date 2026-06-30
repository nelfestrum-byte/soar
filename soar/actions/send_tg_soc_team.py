from soar.connectors import connectors


def send_tg_soc_team(message: str) -> None:
    connectors.telegram_main.send(chat_id="-100123456789", text=message)  # type: ignore[attr-defined]
