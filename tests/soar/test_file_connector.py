import json
import os
import tempfile

import pytest


@pytest.fixture
def file_connector():
    from soar.connectors.file.file import FileConnector
    with tempfile.TemporaryDirectory() as tmpdir:
        conn = FileConnector(instance_name="test_file", base_dir=tmpdir)
        conn._ensure_connected()
        yield conn


def test_file_connector_init():
    from soar.connectors.file.file import FileConnector
    conn = FileConnector(instance_name="test", base_dir="/tmp/test")
    assert conn.instance_name == "test"
    assert conn.base_dir == os.path.realpath("/tmp/test")


def test_file_connector_write(file_connector):
    filepath = file_connector.write("test.txt", "hello world")
    assert os.path.exists(filepath)
    with open(filepath) as f:
        assert f.read() == "hello world"


def test_file_connector_write_json(file_connector):
    data = {"key": "value", "number": 42}
    filepath = file_connector.write_json("test.json", data)
    assert os.path.exists(filepath)
    with open(filepath) as f:
        loaded = json.load(f)
    assert loaded == data


def test_file_connector_write_lines(file_connector):
    lines = ["line1", "line2", "line3"]
    filepath = file_connector.write_lines("test.txt", lines)
    with open(filepath) as f:
        content = f.read()
    assert content == "line1\nline2\nline3\n"


def test_file_connector_append(file_connector):
    file_connector.write("log.txt", "first\n")
    file_connector.append("log.txt", "second\n")
    with open(file_connector.base_dir + "/log.txt") as f:
        assert f.read() == "first\nsecond\n"


def test_file_connector_read(file_connector):
    file_connector.write("readme.txt", "content")
    content = file_connector.read("readme.txt")
    assert content == "content"


def test_file_connector_read_not_found(file_connector):
    with pytest.raises(FileNotFoundError):
        file_connector.read("nonexistent.txt")


def test_file_connector_list_files(file_connector):
    file_connector.write("a.txt", "a")
    file_connector.write("b.txt", "b")
    file_connector.write("sub/c.txt", "c")
    files = file_connector.list_files()
    assert "a.txt" in files
    assert "b.txt" in files


def test_file_connector_delete(file_connector):
    file_connector.write("delete_me.txt", "bye")
    assert file_connector.delete("delete_me.txt") is True
    assert file_connector.delete("delete_me.txt") is False


def test_webhook_to_file_workflow():
    from soar.workflows.webhook_to_file import WebhookToFile
    wf = WebhookToFile()
    assert wf.workflow_type == "webhook"
    assert wf.path == "/webhook/to-file"
    assert isinstance(wf.token, str) and len(wf.token) > 10
