"""Tests for the generic CLI-to-HTTP bridge (`misc/web-agent/server.py`).

`misc/web-agent` has a hyphen in its directory name, so it can't be
`import`ed as a normal package — it's loaded with the same
`importlib.util.spec_from_file_location` mechanism the module itself uses
for `settings.py`. All exchanges in this suite go through
`tests/misc/web_agent/fake_cli.py`, never the real `claude` binary.
"""

import http.client
import importlib.util
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SERVER_PATH = REPO_ROOT / "misc" / "web-agent" / "server.py"
FAKE_CLI_PATH = Path(__file__).resolve().parent / "fake_cli.py"


def _load_server_module():
    spec = importlib.util.spec_from_file_location("web_agent_bridge_server", SERVER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


server = _load_server_module()


def make_settings(tmp_path, prompt_mode="arg", timeout_s=5, base_args=None):
    return SimpleNamespace(
        BASE_ARGS=base_args if base_args is not None else [sys.executable, str(FAKE_CLI_PATH)],
        NEW_SESSION_ARGS=["--new", "{session_id}"],
        RESUME_SESSION_ARGS=["--resume", "{session_id}"],
        PROMPT_MODE=prompt_mode,
        CWD=str(tmp_path),
        HOST="127.0.0.1",
        PORT=0,
        LOG_FILE=str(tmp_path / "bridge.log"),
        TIMEOUT_S=timeout_s,
    )


class RunningServer:
    def __init__(self, settings):
        self.httpd = server.build_server(settings)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    @property
    def port(self):
        return self.httpd.server_port

    def get(self, path):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            conn.request("GET", path)
            resp = conn.getresponse()
            body = resp.read()
            return resp.status, body
        finally:
            conn.close()

    def post(self, path, body_bytes, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            hdrs = {"Content-Type": "application/json"}
            if headers:
                hdrs.update(headers)
            conn.request("POST", path, body=body_bytes, headers=hdrs)
            resp = conn.getresponse()
            body = resp.read()
            return resp.status, body
        finally:
            conn.close()

    def stop(self):
        self.httpd.shutdown()
        self.thread.join(timeout=5)
        self.httpd.server_close()


@pytest.fixture
def running_server(tmp_path):
    started = []

    def _start(settings):
        rs = RunningServer(settings)
        started.append(rs)
        return rs

    yield _start

    for rs in started:
        rs.stop()


def post_message(rs, text):
    status, body = rs.post("/message", json.dumps({"text": text}).encode("utf-8"))
    return status, json.loads(body.decode("utf-8"))


def test_health_returns_ok_and_session_id_without_invoking_cli(tmp_path, running_server, monkeypatch):
    calls_log = tmp_path / "calls.log"
    monkeypatch.setenv("FAKE_CLI_CALLS_LOG", str(calls_log))
    settings = make_settings(tmp_path)
    rs = running_server(settings)

    status, body = rs.get("/health")
    payload = json.loads(body.decode("utf-8"))

    assert status == 200
    assert payload["status"] == "ok"
    assert payload["session_id"] is None
    assert not calls_log.exists()


def test_first_message_creates_session_and_uses_new_session_args(tmp_path, running_server, monkeypatch):
    calls_log = tmp_path / "calls.log"
    monkeypatch.setenv("FAKE_CLI_CALLS_LOG", str(calls_log))
    settings = make_settings(tmp_path, prompt_mode="arg")
    rs = running_server(settings)

    status, payload = post_message(rs, "hi")

    assert status == 200
    assert isinstance(payload["session_id"], str) and payload["session_id"]
    assert "returncode" in payload
    assert "duration_s" in payload
    echoed = json.loads(payload["stdout"])
    assert echoed["argv"][:2] == ["--new", payload["session_id"]]
    assert echoed["argv"][-1] == "hi"


def test_second_message_reuses_session_id_and_uses_resume_args(tmp_path, running_server):
    settings = make_settings(tmp_path, prompt_mode="arg")
    rs = running_server(settings)

    status1, payload1 = post_message(rs, "first")
    status2, payload2 = post_message(rs, "second")

    assert status1 == 200
    assert status2 == 200
    assert payload2["session_id"] == payload1["session_id"]
    echoed2 = json.loads(payload2["stdout"])
    assert echoed2["argv"][:2] == ["--resume", payload1["session_id"]]


def test_prompt_mode_stdin_writes_text_to_subprocess_stdin(tmp_path, running_server):
    settings = make_settings(tmp_path, prompt_mode="stdin")
    rs = running_server(settings)

    status, payload = post_message(rs, "via-stdin")

    assert status == 200
    echoed = json.loads(payload["stdout"])
    assert echoed["stdin"] == "via-stdin"
    assert "via-stdin" not in echoed["argv"]


def test_prompt_mode_arg_appends_text_as_trailing_argv(tmp_path, running_server):
    settings = make_settings(tmp_path, prompt_mode="arg")
    rs = running_server(settings)

    status, payload = post_message(rs, "via-argv")

    assert status == 200
    echoed = json.loads(payload["stdout"])
    assert echoed["argv"][-1] == "via-argv"
    assert echoed["stdin"] == ""


def test_nonzero_cli_returncode_is_still_http_200(tmp_path, running_server, monkeypatch):
    monkeypatch.setenv("FAKE_CLI_EXIT_CODE", "1")
    settings = make_settings(tmp_path)
    rs = running_server(settings)

    status, payload = post_message(rs, "boom")

    assert status == 200
    assert payload["returncode"] == 1


def test_malformed_request_body_returns_non_200(tmp_path, running_server, monkeypatch):
    calls_log = tmp_path / "calls.log"
    monkeypatch.setenv("FAKE_CLI_CALLS_LOG", str(calls_log))
    settings = make_settings(tmp_path)
    rs = running_server(settings)

    status1, _ = rs.post("/message", b"not-json")
    status2, _ = rs.post("/message", json.dumps({"nope": "field"}).encode("utf-8"))
    status3, _ = rs.post("/message", json.dumps({"text": 123}).encode("utf-8"))

    assert status1 != 200
    assert status2 != 200
    assert status3 != 200
    assert not calls_log.exists()


def test_subprocess_timeout_returns_non_200(tmp_path, running_server, monkeypatch):
    monkeypatch.setenv("FAKE_CLI_SLEEP", "2")
    settings = make_settings(tmp_path, timeout_s=0.3)
    rs = running_server(settings)

    status, payload = post_message(rs, "too-slow")

    assert status != 200


def test_missing_cli_binary_returns_non_200(tmp_path, running_server):
    missing = tmp_path / "does-not-exist-binary"
    settings = make_settings(tmp_path, base_args=[str(missing)])
    rs = running_server(settings)

    status, payload = post_message(rs, "hello")

    assert status != 200


def test_transcript_log_appends_readable_block_per_exchange(tmp_path, running_server):
    settings = make_settings(tmp_path)
    rs = running_server(settings)
    log_path = Path(settings.LOG_FILE)

    status1, payload1 = post_message(rs, "first-request-text")
    content_after_first = log_path.read_text(encoding="utf-8")

    assert "first-request-text" in content_after_first
    assert str(payload1["returncode"]) in content_after_first

    status2, payload2 = post_message(rs, "second-request-text")
    content_after_second = log_path.read_text(encoding="utf-8")

    assert content_after_second.startswith(content_after_first)
    assert "first-request-text" in content_after_second
    assert "second-request-text" in content_after_second


def test_requests_are_served_strictly_sequentially(tmp_path, running_server, monkeypatch):
    calls_log = tmp_path / "calls.log"
    monkeypatch.setenv("FAKE_CLI_CALLS_LOG", str(calls_log))
    monkeypatch.setenv("FAKE_CLI_SLEEP", "0.4")
    settings = make_settings(tmp_path, timeout_s=10)
    rs = running_server(settings)

    with ThreadPoolExecutor(max_workers=2) as pool:
        f1 = pool.submit(post_message, rs, "call-1")
        time.sleep(0.05)  # ensure call-1 is issued first
        f2 = pool.submit(post_message, rs, "call-2")
        status1, payload1 = f1.result()
        status2, payload2 = f2.result()

    assert status1 == 200
    assert status2 == 200

    lines = [json.loads(line) for line in calls_log.read_text(encoding="utf-8").splitlines() if line.strip()]
    starts = [entry["t"] for entry in lines if entry["event"] == "start"]
    ends = [entry["t"] for entry in lines if entry["event"] == "end"]
    assert len(starts) == 2
    assert len(ends) == 2

    # Serialized handling means the second invocation cannot start before
    # the first one's subprocess finished (HTTPServer, not ThreadingHTTPServer).
    first_end = min(ends)
    second_start = max(starts)
    assert second_start >= first_end
