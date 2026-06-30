import sys
from unittest.mock import MagicMock

import pytest


@pytest.fixture(autouse=True)
def mock_smtplib():
    mock_smtp = MagicMock()
    mock_smtp.SMTP.return_value = MagicMock()
    sys.modules["smtplib"] = mock_smtp
    yield mock_smtp
    sys.modules.pop("smtplib", None)


def test_smtp_connector_init():
    from soar.connectors.smtp.smtp import SmtpConnector
    conn = SmtpConnector(
        instance_name="smtp_main",
        host="smtp.gmail.com",
        port=587,
        username="user@gmail.com",
        password="pass",
        from_email="alerts@company.com",
    )
    assert conn.instance_name == "smtp_main"
    assert conn.host == "smtp.gmail.com"
    assert conn.port == 587
    assert conn.from_email == "alerts@company.com"


def test_smtp_connector_connect(mock_smtplib):
    from soar.connectors.smtp.smtp import SmtpConnector
    conn = SmtpConnector(
        instance_name="smtp_main",
        host="smtp.gmail.com",
        port=587,
        username="user@gmail.com",
        password="pass",
    )
    conn._connect_impl()
    assert conn._connected is True
    mock_smtplib.SMTP.assert_called_once_with("smtp.gmail.com", 587, timeout=10)


def test_smtp_connector_send_email(mock_smtplib):
    from soar.connectors.smtp.smtp import SmtpConnector
    mock_server = mock_smtplib.SMTP.return_value

    conn = SmtpConnector(
        instance_name="smtp_main",
        host="smtp.gmail.com",
        port=587,
        username="user@gmail.com",
        password="pass",
        from_email="alerts@company.com",
    )
    conn._connected = True
    conn._server = mock_server

    result = conn.send_email(
        to="recipient@example.com",
        subject="Test Subject",
        body="Test body",
    )
    assert result["status"] == "sent"
    assert result["to"] == ["recipient@example.com"]
    mock_server.sendmail.assert_called_once()


def test_smtp_connector_send_multiple_recipients(mock_smtplib):
    from soar.connectors.smtp.smtp import SmtpConnector
    mock_server = mock_smtplib.SMTP.return_value

    conn = SmtpConnector(
        instance_name="smtp_main",
        host="smtp.gmail.com",
        port=587,
        from_email="alerts@company.com",
    )
    conn._connected = True
    conn._server = mock_server

    result = conn.send_email(
        to=["a@example.com", "b@example.com"],
        subject="Broadcast",
        body="Hello all",
    )
    assert result["status"] == "sent"
    assert len(result["to"]) == 2


def test_smtp_connector_send_with_cc(mock_smtplib):
    from soar.connectors.smtp.smtp import SmtpConnector
    mock_server = mock_smtplib.SMTP.return_value

    conn = SmtpConnector(
        instance_name="smtp_main",
        host="smtp.gmail.com",
        port=587,
        from_email="alerts@company.com",
    )
    conn._connected = True
    conn._server = mock_server

    result = conn.send_email(
        to="main@example.com",
        cc="cc@example.com",
        subject="With CC",
        body="Body",
    )
    assert result["status"] == "sent"


def test_smtp_connector_send_html(mock_smtplib):
    from soar.connectors.smtp.smtp import SmtpConnector
    mock_server = mock_smtplib.SMTP.return_value

    conn = SmtpConnector(
        instance_name="smtp_main",
        host="smtp.gmail.com",
        port=587,
        from_email="alerts@company.com",
    )
    conn._connected = True
    conn._server = mock_server

    result = conn.send_html(
        to="user@example.com",
        subject="HTML Email",
        body="<h1>Hello</h1><p>World</p>",
    )
    assert result["status"] == "sent"


def test_smtp_connector_disconnect(mock_smtplib):
    from soar.connectors.smtp.smtp import SmtpConnector
    mock_server = mock_smtplib.SMTP.return_value

    conn = SmtpConnector(instance_name="smtp_main", host="smtp.gmail.com", port=587)
    conn._connected = True
    conn._server = mock_server

    conn.disconnect()
    assert conn._connected is False
    assert conn._server is None
    mock_server.quit.assert_called_once()
