from pathlib import Path

import pytest

from deploy.soarctl_lib import cli


def test_no_args_prints_help_and_exits_nonzero(capsys):
    with pytest.raises(SystemExit) as exc_info:
        cli.main([])
    assert exc_info.value.code != 0
    assert "usage" in capsys.readouterr().out.lower()


def test_package_dispatches_to_bundle_package(monkeypatch, tmp_path):
    calls = {}
    monkeypatch.setattr(cli.bundle, "package", lambda repo_root, version, output: calls.update(
        repo_root=repo_root, version=version, output=output
    ) or output)
    monkeypatch.setattr(cli.paths, "repo_root", lambda start: Path("/fake/repo"))

    cli.main(["package", "--version", "9.9.9", "--output", str(tmp_path / "out.tar.gz")])

    assert calls["version"] == "9.9.9"
    assert calls["repo_root"] == Path("/fake/repo")
    assert calls["output"] == tmp_path / "out.tar.gz"


def test_install_dispatches_to_bundle_install(monkeypatch, tmp_path):
    calls = {}
    monkeypatch.setattr(
        cli.bundle, "install", lambda bundle_path, dest_dir: calls.update(bundle=bundle_path, dest=dest_dir)
    )
    bundle_file = tmp_path / "b.tar.gz"
    bundle_file.write_bytes(b"x")

    cli.main(["install", str(bundle_file), "--dir", str(tmp_path / "instance")])

    assert calls["bundle"] == bundle_file
    assert calls["dest"] == tmp_path / "instance"


def test_init_dispatches_to_env_init_instance(monkeypatch, tmp_path):
    calls = {}
    monkeypatch.setattr(
        cli.env, "init_instance", lambda directory, force=False: calls.update(directory=directory, force=force)
    )

    cli.main(["init", "--dir", str(tmp_path)])

    assert calls["directory"] == tmp_path
    assert calls["force"] is False


def test_up_dispatches_to_compose_up(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(cli.compose, "up", lambda instance: calls.append(instance))
    cli.main(["up", "--dir", str(tmp_path)])
    assert calls == [tmp_path]


def test_down_dispatches_to_compose_down(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(cli.compose, "down", lambda instance: calls.append(instance))
    cli.main(["down", "--dir", str(tmp_path)])
    assert calls == [tmp_path]


def test_migrate_fresh_dispatches_to_stamp_head(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(cli.migrate, "stamp_head", lambda instance: calls.append(("stamp", instance)))
    monkeypatch.setattr(cli.migrate, "upgrade_head", lambda instance: calls.append(("upgrade", instance)))
    cli.main(["migrate", "--fresh", "--dir", str(tmp_path)])
    assert calls == [("stamp", tmp_path)]


def test_migrate_upgrade_dispatches_to_upgrade_head(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(cli.migrate, "stamp_head", lambda instance: calls.append(("stamp", instance)))
    monkeypatch.setattr(cli.migrate, "upgrade_head", lambda instance: calls.append(("upgrade", instance)))
    cli.main(["migrate", "--upgrade", "--dir", str(tmp_path)])
    assert calls == [("upgrade", tmp_path)]


def test_migrate_requires_one_flag(tmp_path):
    with pytest.raises(SystemExit):
        cli.main(["migrate", "--dir", str(tmp_path)])


def test_users_create_dispatches(monkeypatch, tmp_path):
    calls = {}
    monkeypatch.setattr(
        cli.users, "create", lambda instance, username, role: calls.update(instance=instance, username=username, role=role)
    )
    cli.main(["users", "create", "--username", "alice", "--role", "admin", "--dir", str(tmp_path)])
    assert calls == {"instance": tmp_path, "username": "alice", "role": "admin"}


def test_users_deactivate_dispatches(monkeypatch, tmp_path):
    calls = {}
    monkeypatch.setattr(
        cli.users, "deactivate", lambda instance, username: calls.update(instance=instance, username=username)
    )
    cli.main(["users", "deactivate", "--username", "alice", "--dir", str(tmp_path)])
    assert calls == {"instance": tmp_path, "username": "alice"}


def test_backup_create_dispatches(monkeypatch, tmp_path):
    calls = {}
    monkeypatch.setattr(cli.backup, "create", lambda instance, output: calls.update(instance=instance, output=output))
    cli.main(["backup", "create", "--dir", str(tmp_path), "--output", str(tmp_path / "b.tar.gz")])
    assert calls == {"instance": tmp_path, "output": tmp_path / "b.tar.gz"}


def test_backup_restore_requires_confirm_flag(monkeypatch, tmp_path):
    calls = {}
    monkeypatch.setattr(
        cli.backup,
        "restore",
        lambda instance, archive, confirm: calls.update(instance=instance, archive=archive, confirm=confirm),
    )
    archive = tmp_path / "b.tar.gz"
    archive.write_bytes(b"x")
    cli.main(["backup", "restore", str(archive), "--dir", str(tmp_path), "--confirm"])
    assert calls == {"instance": tmp_path, "archive": archive, "confirm": True}


def test_doctor_dispatches_and_prints_results(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli.doctor, "run_checks", lambda instance: [("docker", True, "found")])
    cli.main(["doctor", "--dir", str(tmp_path)])
    out = capsys.readouterr().out
    assert "docker" in out
