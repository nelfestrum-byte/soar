from pathlib import Path

import pytest

from deploy.soarctl_lib.users import activate, create, deactivate


def _make_instance(tmp_path: Path) -> Path:
    (tmp_path / "docker-compose.yml").write_text("services: {}\n")
    (tmp_path / ".env").write_text("SOAR_VERSION=1.2.3\n")
    return tmp_path


def _tail(instance: Path, calls, kw_check=None):
    assert len(calls) == 1
    argv = calls[0]
    idx = argv.index("orchestrator.auth.cli")
    return argv[idx:]


def test_create_argv_default_role(tmp_path, monkeypatch):
    instance = _make_instance(tmp_path)
    calls = []
    monkeypatch.setattr("deploy.soarctl_lib.users.run", lambda argv, **kw: calls.append(argv))
    create(instance, username="alice")
    tail = _tail(instance, calls)
    assert tail == ["orchestrator.auth.cli", "create-user", "--username", "alice", "--role", "analyst"]


def test_create_argv_admin_role(tmp_path, monkeypatch):
    instance = _make_instance(tmp_path)
    calls = []
    monkeypatch.setattr("deploy.soarctl_lib.users.run", lambda argv, **kw: calls.append(argv))
    create(instance, username="admin", role="admin")
    tail = _tail(instance, calls)
    assert tail == ["orchestrator.auth.cli", "create-user", "--username", "admin", "--role", "admin"]


def test_create_rejects_unknown_role(tmp_path):
    instance = _make_instance(tmp_path)
    with pytest.raises(ValueError):
        create(instance, username="bob", role="superuser")


def test_deactivate_argv(tmp_path, monkeypatch):
    instance = _make_instance(tmp_path)
    calls = []
    monkeypatch.setattr("deploy.soarctl_lib.users.run", lambda argv, **kw: calls.append(argv))
    deactivate(instance, username="alice")
    tail = _tail(instance, calls)
    assert tail == ["orchestrator.auth.cli", "deactivate-user", "--username", "alice"]


def test_activate_argv(tmp_path, monkeypatch):
    instance = _make_instance(tmp_path)
    calls = []
    monkeypatch.setattr("deploy.soarctl_lib.users.run", lambda argv, **kw: calls.append(argv))
    activate(instance, username="alice")
    tail = _tail(instance, calls)
    assert tail == ["orchestrator.auth.cli", "activate-user", "--username", "alice"]
