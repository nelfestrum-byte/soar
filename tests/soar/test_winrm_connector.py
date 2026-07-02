from unittest.mock import MagicMock, patch

from soar.connectors.winrm.winrm import WinRMConnector


def test_winrm_init():
    conn = WinRMConnector(
        instance_name="test_winrm",
        host="10.0.0.1",
        username="admin",
        password="pass",
    )
    assert conn.instance_name == "test_winrm"
    assert conn.host == "10.0.0.1"
    assert conn.port == 5985
    assert conn.transport == "ntlm"
    assert conn.is_connected is False


def test_winrm_connect_impl():
    conn = WinRMConnector(
        instance_name="test_winrm",
        host="10.0.0.1",
        username="admin",
        password="pass",
    )
    with patch("soar.connectors.winrm.winrm.winrm.Session") as mock_client:
        conn._connect_impl()
        mock_client.assert_called_once_with(
            "https://10.0.0.1:5985/wsman",
            auth=("admin", "pass"),
            transport="ntlm",
            server_cert_validation="validate",
        )
        assert conn.is_connected is False


def test_winrm_exec_command():
    conn = WinRMConnector(
        instance_name="test_winrm",
        host="10.0.0.1",
        username="admin",
        password="pass",
    )
    with patch("soar.connectors.winrm.winrm.winrm.Session") as mock_client:
        mock_session = MagicMock()
        mock_run = MagicMock()
        mock_run.std_out = "output"
        mock_run.std_err = "error"
        mock_run.status_code = 0
        mock_session.run.return_value = mock_run
        mock_client.return_value = mock_session
        conn._connect_impl()
        conn._connected = True

        result = conn.exec_command("whoami")
        assert result == {"stdout": "output", "stderr": "error", "exit_code": 0}
        mock_session.run.assert_called_once_with("whoami", timeout=30)


def test_winrm_exec_command_with_timeout():
    conn = WinRMConnector(
        instance_name="test_winrm",
        host="10.0.0.1",
        username="admin",
        password="pass",
    )
    with patch("soar.connectors.winrm.winrm.winrm.Session") as mock_client:
        mock_session = MagicMock()
        mock_run = MagicMock()
        mock_run.std_out = ""
        mock_run.std_err = ""
        mock_run.status_code = 0
        mock_session.run.return_value = mock_run
        mock_client.return_value = mock_session
        conn._connect_impl()
        conn._connected = True

        conn.exec_command("dir", timeout=60)
        mock_session.run.assert_called_once_with("dir", timeout=60)


def test_winrm_upload_file():
    conn = WinRMConnector(
        instance_name="test_winrm",
        host="10.0.0.1",
        username="admin",
        password="pass",
    )
    with patch("soar.connectors.winrm.winrm.winrm.Session") as mock_client:
        mock_session = MagicMock()
        mock_client.return_value = mock_session
        conn._connect_impl()
        conn._connected = True

        result = conn.upload_file("/local/file.txt", "C:\\remote\\file.txt")
        assert result is True
        mock_session.upload.assert_called_once_with("C:\\remote\\file.txt", "/local/file.txt")


def test_winrm_download_file():
    conn = WinRMConnector(
        instance_name="test_winrm",
        host="10.0.0.1",
        username="admin",
        password="pass",
    )
    with patch("soar.connectors.winrm.winrm.winrm.Session") as mock_client:
        mock_session = MagicMock()
        mock_client.return_value = mock_session
        conn._connect_impl()
        conn._connected = True

        result = conn.download_file("C:\\remote\\file.txt", "/local/file.txt")
        assert result is True
        mock_session.download.assert_called_once_with("C:\\remote\\file.txt", "/local/file.txt")


def test_winrm_disconnect():
    conn = WinRMConnector(
        instance_name="test_winrm",
        host="10.0.0.1",
        username="admin",
        password="pass",
    )
    with patch("soar.connectors.winrm.winrm.winrm.Session"):
        conn._connect_impl()
        conn._connected = True
    conn.disconnect()
    assert conn.is_connected is False
    assert conn._client is None
