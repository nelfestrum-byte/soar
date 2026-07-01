from soar.connectors import connectors


def send_tg_soc_team(message: str) -> None:
    connectors.telegram_main.send_message(chat_id="-100123456789", text=message)
