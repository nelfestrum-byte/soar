from pathlib import Path

import pytest

from deploy.soarctl_lib.compose import ComposeError, compose_argv, down, logs, ps, restart, up


def _make_instance(tmp_path: Path) -> Path:
    (tmp_path / "docker-compose.yml").write_text("services: {}\n")
    (tmp_path / ".env").write_text("SOAR_VERSION=1.2.3\n")
    return tmp_path


def test_compose_argv_prefix(tmp_path):
    instance = _make_instance(tmp_path)
    argv = compose_argv(instance, "ps")
    assert argv[:2] == ["docker", "compose"]
    assert argv[2:4] == ["-f", str(instance / "docker-compose.yml")]
    assert "--env-file" in argv
    assert str(instance / ".env") in argv
    assert argv[-1] == "ps"


def test_compose_argv_missing_env_raises(tmp_path):
    (tmp_path / "docker-compose.yml").write_text("services: {}\n")
    with pytest.raises(ComposeError):
        compose_argv(tmp_path, "ps")


def test_up_calls_run_with_up_dash_d(tmp_path, monkeypatch):
    instance = _make_instance(tmp_path)
    calls = []
    monkeypatch.setattr("deploy.soarctl_lib.compose.run", lambda argv, **kw: calls.append(argv))
    up(instance)
    assert calls[0][-2:] == ["up", "-d"]


def test_down_calls_run_with_down(tmp_path, monkeypatch):
    instance = _make_instance(tmp_path)
    calls = []
    monkeypatch.setattr("deploy.soarctl_lib.compose.run", lambda argv, **kw: calls.append(argv))
    down(instance)
    assert calls[0][-1] == "down"


def test_restart_calls_run_with_restart(tmp_path, monkeypatch):
    instance = _make_instance(tmp_path)
    calls = []
    monkeypatch.setattr("deploy.soarctl_lib.compose.run", lambda argv, **kw: calls.append(argv))
    restart(instance)
    assert calls[0][-1] == "restart"


def test_ps_calls_run_with_ps(tmp_path, monkeypatch):
    instance = _make_instance(tmp_path)
    calls = []

    class _Result:
        stdout = "fake ps output"

    def fake_run(argv, **kw):
        calls.append(argv)
        return _Result()

    monkeypatch.setattr("deploy.soarctl_lib.compose.run", fake_run)
    output = ps(instance)
    assert calls[0][-1] == "ps"
    assert output == "fake ps output"


def test_logs_without_service(tmp_path, monkeypatch):
    instance = _make_instance(tmp_path)
    calls = []
    monkeypatch.setattr("deploy.soarctl_lib.compose.run", lambda argv, **kw: calls.append(argv))
    logs(instance)
    assert calls[0][-2:] == ["logs", "-f"]


def test_logs_with_service(tmp_path, monkeypatch):
    instance = _make_instance(tmp_path)
    calls = []
    monkeypatch.setattr("deploy.soarctl_lib.compose.run", lambda argv, **kw: calls.append(argv))
    logs(instance, service="orchestrator")
    assert calls[0][-3:] == ["logs", "-f", "orchestrator"]
