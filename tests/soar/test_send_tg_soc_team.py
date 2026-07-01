from unittest.mock import patch

from soar.actions.send_tg_soc_team import send_tg_soc_team


@patch("soar.actions.send_tg_soc_team.connectors")
def test_send_tg_soc_team_calls_send_message(mock_connectors):
    send_tg_soc_team("test message")
    mock_connectors.telegram_main.send_message.assert_called_once_with(
        chat_id="-100123456789", text="test message"
    )
