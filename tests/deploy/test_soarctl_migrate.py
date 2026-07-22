from pathlib import Path

from deploy.soarctl_lib.migrate import stamp_head, upgrade_head


def _make_instance(tmp_path: Path) -> Path:
    (tmp_path / "docker-compose.yml").write_text("services: {}\n")
    (tmp_path / ".env").write_text("SOAR_VERSION=1.2.3\n")
    return tmp_path


def test_stamp_head_argv(tmp_path, monkeypatch):
    instance = _make_instance(tmp_path)
    calls = []
    monkeypatch.setattr("deploy.soarctl_lib.migrate.run", lambda argv, **kw: calls.append(argv))
    stamp_head(instance)
    argv = calls[0]
    assert argv[-7:] == ["exec", "orchestrator", "python", "-m", "alembic", "stamp", "head"]


def test_upgrade_head_argv(tmp_path, monkeypatch):
    instance = _make_instance(tmp_path)
    calls = []
    monkeypatch.setattr("deploy.soarctl_lib.migrate.run", lambda argv, **kw: calls.append(argv))
    upgrade_head(instance)
    argv = calls[0]
    assert argv[-7:] == ["exec", "orchestrator", "python", "-m", "alembic", "upgrade", "head"]
