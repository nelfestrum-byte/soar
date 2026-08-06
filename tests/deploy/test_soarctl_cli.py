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


def test_package_defaults_version_from_git_describe(monkeypatch, tmp_path):
    calls = {}
    monkeypatch.setattr(cli.bundle, "package", lambda repo_root, version, output: calls.update(
        repo_root=repo_root, version=version, output=output
    ) or output)
    monkeypatch.setattr(cli.paths, "repo_root", lambda start: Path("/fake/repo"))
    monkeypatch.setattr(cli.git_source, "resolve_version", lambda checkout: "0.1-42-gabc1234")

    cli.main(["package", "--output", str(tmp_path / "out.tar.gz")])

    assert calls["version"] == "0.1-42-gabc1234"


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
        cli.env,
        "init_instance",
        lambda directory, force=False, overrides=None: calls.update(
            directory=directory, force=force, overrides=overrides
        ),
    )

    cli.main(["init", "--dir", str(tmp_path)])

    assert calls["directory"] == tmp_path
    assert calls["force"] is False
    assert calls["overrides"] is None


def test_init_interactive_prompts_and_passes_overrides(monkeypatch, tmp_path):
    calls = {}
    monkeypatch.setattr(
        cli.env,
        "init_instance",
        lambda directory, force=False, overrides=None: calls.update(overrides=overrides),
    )
    monkeypatch.setattr(cli.prompts, "prompt_cors_origins", lambda: ["https://soar.example.com"])

    cli.main(["init", "--interactive", "--dir", str(tmp_path)])

    assert calls["overrides"] == {"CORS_ORIGINS_JSON": '["https://soar.example.com"]'}


def test_init_cors_origin_flags_skip_prompting(monkeypatch, tmp_path):
    calls = {}
    monkeypatch.setattr(
        cli.env,
        "init_instance",
        lambda directory, force=False, overrides=None: calls.update(overrides=overrides),
    )

    def fail_prompt():
        raise AssertionError("should not prompt when --cors-origin is given")

    monkeypatch.setattr(cli.prompts, "prompt_cors_origins", fail_prompt)

    cli.main(["init", "--cors-origin", "https://a.example.com", "--cors-origin", "https://b.example.com", "--dir", str(tmp_path)])

    assert calls["overrides"] == {"CORS_ORIGINS_JSON": '["https://a.example.com", "https://b.example.com"]'}


def test_init_interactive_and_cors_origin_are_mutually_exclusive(tmp_path):
    with pytest.raises(SystemExit):
        cli.main(["init", "--interactive", "--cors-origin", "https://a.example.com", "--dir", str(tmp_path)])


def test_install_repo_dispatches_to_git_source_install(monkeypatch, tmp_path):
    calls = {}
    monkeypatch.setattr(
        cli.git_source,
        "install",
        lambda checkout, ref: calls.update(checkout=checkout, ref=ref),
    )
    checkout = tmp_path / "repo"
    checkout.mkdir()

    cli.main(["install", "--repo", str(checkout), "--ref", "v1.0.0"])

    assert calls == {"checkout": checkout.resolve(), "ref": "v1.0.0"}


def test_install_without_bundle_or_repo_auto_discovers_checkout_from_cwd(monkeypatch, tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "pyproject.toml").write_text("[tool.x]\n")
    monkeypatch.chdir(root)

    calls = {}
    monkeypatch.setattr(
        cli.git_source,
        "install",
        lambda checkout, ref: calls.update(checkout=checkout, ref=ref),
    )

    cli.main(["install"])

    assert calls == {"checkout": root.resolve(), "ref": None}


def test_install_without_bundle_or_repo_outside_checkout_errors(monkeypatch, tmp_path):
    outside = tmp_path / "nowhere"
    outside.mkdir()
    monkeypatch.chdir(outside)

    with pytest.raises(SystemExit):
        cli.main(["install"])


def test_install_rejects_both_bundle_and_repo(tmp_path):
    bundle_file = tmp_path / "b.tar.gz"
    bundle_file.write_bytes(b"x")
    checkout = tmp_path / "repo"
    checkout.mkdir()
    with pytest.raises(SystemExit):
        cli.main(["install", str(bundle_file), "--repo", str(checkout)])


def test_update_dispatches_to_git_source_update(monkeypatch, tmp_path):
    calls = {}
    monkeypatch.setattr(
        cli.git_source,
        "update",
        lambda instance, ref, migrate: calls.update(instance=instance, ref=ref, migrate=migrate),
    )

    cli.main(["update", "--ref", "v1.2.3", "--dir", str(tmp_path)])

    assert calls == {"instance": tmp_path, "ref": "v1.2.3", "migrate": None}


def test_update_migrate_flag_passed_through(monkeypatch, tmp_path):
    calls = {}
    monkeypatch.setattr(
        cli.git_source,
        "update",
        lambda instance, ref, migrate: calls.update(instance=instance, ref=ref, migrate=migrate),
    )

    cli.main(["update", "--migrate", "fresh", "--dir", str(tmp_path)])

    assert calls == {"instance": tmp_path, "ref": None, "migrate": "fresh"}


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


def test_content_install_dispatches(monkeypatch, tmp_path, capsys):
    calls = {}
    monkeypatch.setattr(
        cli.content, "install",
        lambda instance, pack, ref=None: calls.update(instance=instance, pack=pack, ref=ref)
        or {"new": ["fake_conn"], "update": [], "unchanged": [], "skip_modified": []},
    )
    cli.main(["content", "install", str(tmp_path), "--ref", "v1", "--dir", str(tmp_path)])
    assert calls == {"instance": tmp_path, "pack": str(tmp_path), "ref": "v1"}
    assert "fake_conn" in capsys.readouterr().out


def test_content_list_dispatches_and_prints_table(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(
        cli.content, "list_installed",
        lambda instance: [{"name": "fake_conn", "pack_version": "1.0.0", "modified": False}],
    )
    cli.main(["content", "list", "--dir", str(tmp_path)])
    out = capsys.readouterr().out
    assert "fake_conn" in out
    assert "1.0.0" in out


def test_content_remove_dispatches(monkeypatch, tmp_path):
    calls = {}
    monkeypatch.setattr(
        cli.content, "remove", lambda instance, name, force=False: calls.update(instance=instance, name=name, force=force),
    )
    cli.main(["content", "remove", "fake_conn", "--force", "--dir", str(tmp_path)])
    assert calls == {"instance": tmp_path, "name": "fake_conn", "force": True}


def test_content_remove_error_exits_nonzero(monkeypatch, tmp_path, capsys):
    def _raise(instance, name, force=False):
        raise cli.content.ContentError("modified since install")

    monkeypatch.setattr(cli.content, "remove", _raise)
    with pytest.raises(SystemExit) as exc_info:
        cli.main(["content", "remove", "fake_conn", "--dir", str(tmp_path)])
    assert exc_info.value.code != 0
    assert "modified" in capsys.readouterr().out
