from unittest.mock import MagicMock, patch

from soar.connectors.smb_rpc.smb_rpc import SMBRPCConnector


def test_smb_rpc_init():
    conn = SMBRPCConnector(
        instance_name="test_smb",
        host="10.0.0.1",
        username="admin",
        password="pass",
        domain="WORKGROUP",
    )
    assert conn.instance_name == "test_smb"
    assert conn.host == "10.0.0.1"
    assert conn.port == 445
    assert conn.domain == "WORKGROUP"
    assert conn.is_connected is False


def test_smb_rpc_connect_impl():
    conn = SMBRPCConnector(
        instance_name="test_smb",
        host="10.0.0.1",
        username="admin",
        password="pass",
    )
    with patch("soar.connectors.smb_rpc.smb_rpc.Connection") as mock_conn_cls:
        with patch("soar.connectors.smb_rpc.smb_rpc.Session") as mock_session_cls:
            conn._connect_impl()
            mock_conn_cls.assert_called_once()
            mock_session_cls.assert_called_once()
            mock_session_cls.return_value.connect.assert_called_once()


def test_smb_rpc_disconnect():
    conn = SMBRPCConnector(
        instance_name="test_smb",
        host="10.0.0.1",
        username="admin",
        password="pass",
    )
    with patch("soar.connectors.smb_rpc.smb_rpc.Connection"):
        with patch("soar.connectors.smb_rpc.smb_rpc.Session"):
            conn._connect_impl()
            conn._connected = True
    conn.disconnect()
    assert conn.is_connected is False
    assert conn._connection is None
    assert conn._session is None


def test_smb_rpc_list_files():
    conn = SMBRPCConnector(
        instance_name="test_smb",
        host="10.0.0.1",
        username="admin",
        password="pass",
    )
    with patch("soar.connectors.smb_rpc.smb_rpc.Connection"):
        with patch("soar.connectors.smb_rpc.smb_rpc.Session"):
            with patch("soar.connectors.smb_rpc.smb_rpc.TreeConnect") as mock_tree_cls:
                with patch("soar.connectors.smb_rpc.smb_rpc.Open") as mock_open_cls:
                    mock_tree = MagicMock()
                    mock_tree.share_name = "C$"
                    mock_tree_cls.return_value = mock_tree

                    mock_file = MagicMock()
                    mock_file.query_directory.return_value = (
                        [
                            {"file_name": "test.txt", "end_of_file": 100, "file_attributes": 0x20, "creation_time": 0, "last_access": 0, "last_write": 0},
                            {"file_name": "subdir", "end_of_file": 0, "file_attributes": 0x10, "creation_time": 0, "last_access": 0, "last_write": 0},
                            {"file_name": ".", "end_of_file": 0, "file_attributes": 0x10, "creation_time": 0, "last_access": 0, "last_write": 0},
                            {"file_name": "..", "end_of_file": 0, "file_attributes": 0x10, "creation_time": 0, "last_access": 0, "last_write": 0},
                        ],
                        None,
                    )
                    mock_open_cls.return_value = mock_file

                    conn._connect_impl()
                    conn._connected = True

                    files = conn.list_files("C$", "Users\\Admin")
                    assert len(files) == 2
                    assert files[0]["filename"] == "test.txt"
                    assert files[1]["filename"] == "subdir"
                    assert files[1]["is_directory"] is True


def test_smb_rpc_upload_file():
    conn = SMBRPCConnector(
        instance_name="test_smb",
        host="10.0.0.1",
        username="admin",
        password="pass",
    )
    with patch("soar.connectors.smb_rpc.smb_rpc.Connection"):
        with patch("soar.connectors.smb_rpc.smb_rpc.Session"):
            with patch("soar.connectors.smb_rpc.smb_rpc.TreeConnect") as mock_tree_cls:
                with patch("soar.connectors.smb_rpc.smb_rpc.Open") as mock_open_cls:
                    mock_tree = MagicMock()
                    mock_tree_cls.return_value = mock_tree

                    mock_file = MagicMock()
                    mock_open_cls.return_value = mock_file

                    conn._connect_impl()
                    conn._connected = True

                    with patch("builtins.open", MagicMock()):
                        result = conn.upload_file("C$", "remote.txt", "/local/file.txt")
                    assert result is True


def test_smb_rpc_download_file():
    conn = SMBRPCConnector(
        instance_name="test_smb",
        host="10.0.0.1",
        username="admin",
        password="pass",
    )
    with patch("soar.connectors.smb_rpc.smb_rpc.Connection"):
        with patch("soar.connectors.smb_rpc.smb_rpc.Session"):
            with patch("soar.connectors.smb_rpc.smb_rpc.TreeConnect") as mock_tree_cls:
                with patch("soar.connectors.smb_rpc.smb_rpc.Open") as mock_open_cls:
                    mock_tree = MagicMock()
                    mock_tree_cls.return_value = mock_tree

                    mock_file = MagicMock()
                    mock_file.query_file.return_value = {"end_of_file": 100}
                    mock_file.read.return_value = b"test data"
                    mock_open_cls.return_value = mock_file

                    conn._connect_impl()
                    conn._connected = True

                    with patch("builtins.open", MagicMock()):
                        result = conn.download_file("C$", "remote.txt", "/local/file.txt")
                    assert result is True


def test_smb_rpc_delete_file():
    conn = SMBRPCConnector(
        instance_name="test_smb",
        host="10.0.0.1",
        username="admin",
        password="pass",
    )
    with patch("soar.connectors.smb_rpc.smb_rpc.Connection"):
        with patch("soar.connectors.smb_rpc.smb_rpc.Session"):
            with patch("soar.connectors.smb_rpc.smb_rpc.TreeConnect") as mock_tree_cls:
                with patch("soar.connectors.smb_rpc.smb_rpc.Open") as mock_open_cls:
                    mock_tree = MagicMock()
                    mock_tree_cls.return_value = mock_tree

                    mock_file = MagicMock()
                    mock_open_cls.return_value = mock_file

                    conn._connect_impl()
                    conn._connected = True

                    result = conn.delete_file("C$", "Users\\Admin\\file.txt")
                    assert result is True


def test_smb_rpc_check_file_exists():
    conn = SMBRPCConnector(
        instance_name="test_smb",
        host="10.0.0.1",
        username="admin",
        password="pass",
    )
    with patch("soar.connectors.smb_rpc.smb_rpc.Connection"):
        with patch("soar.connectors.smb_rpc.smb_rpc.Session"):
            with patch("soar.connectors.smb_rpc.smb_rpc.TreeConnect") as mock_tree_cls:
                with patch("soar.connectors.smb_rpc.smb_rpc.Open") as mock_open_cls:
                    mock_tree = MagicMock()
                    mock_tree_cls.return_value = mock_tree

                    mock_file = MagicMock()
                    mock_open_cls.return_value = mock_file

                    conn._connect_impl()
                    conn._connected = True

                    result = conn.check_file_exists("C$", "file.txt")
                    assert result is True
