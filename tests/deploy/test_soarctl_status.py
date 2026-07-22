from urllib.error import URLError

from deploy.soarctl_lib.status import check_health, summarize


def test_check_health_ok(monkeypatch):
    class _Resp:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b'{"status": "ok"}'

    monkeypatch.setattr("deploy.soarctl_lib.status.urlopen", lambda url, timeout=5: _Resp())
    ok, message = check_health("http://localhost:8000")
    assert ok is True
    assert "ok" in message.lower()


def test_check_health_unreachable(monkeypatch):
    def raise_error(url, timeout=5):
        raise URLError("connection refused")

    monkeypatch.setattr("deploy.soarctl_lib.status.urlopen", raise_error)
    ok, message = check_health("http://localhost:8000")
    assert ok is False
    assert "connection refused" in message


def test_summarize_combines_ps_and_health():
    text = summarize(ps_output="soar-orchestrator   running", health=(True, "ok"))
    assert "soar-orchestrator" in text
    assert "health: ok" in text.lower()
