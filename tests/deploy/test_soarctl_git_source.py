import json
from pathlib import Path

import pytest

from deploy.soarctl_lib import git_source


def _make_fake_checkout(root: Path) -> Path:
    prod = root / "deploy" / "prod"
    prod.mkdir(parents=True)
    (prod / "docker-compose.yml").write_text("services: {}\n")
    (prod / "config.yaml.template").write_text('auth:\n  cors_origins: ${CORS_ORIGINS_JSON}\n')
    return root


def _fake_run(calls):
    def run(argv, **kw):
        calls.append(argv)
        return type("R", (), {"stdout": "v1.2.3-4-gabcdef\n"})()

    return run


def test_resolve_version_runs_git_describe(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(git_source, "run", _fake_run(calls))

    version = git_source.resolve_version(tmp_path)

    assert version == "v1.2.3-4-gabcdef"
    assert calls == [["git", "-C", str(tmp_path), "describe", "--tags", "--always", "--dirty"]]


def test_install_writes_version_and_source_json_in_place(monkeypatch, tmp_path):
    checkout = _make_fake_checkout(tmp_path / "repo")
    calls = []
    monkeypatch.setattr(git_source, "run", _fake_run(calls))
    monkeypatch.setattr(git_source, "build_images", lambda repo_root, version: (f"soar-orchestrator:{version}", f"soar-ui:{version}"))

    result = git_source.install(checkout, ref=None)

    instance = checkout / "deploy" / "prod"
    assert result == instance
    assert (instance / "VERSION").read_text().strip() == "v1.2.3-4-gabcdef"

    source = json.loads((instance / "source.json").read_text())
    assert source == {"checkout": str(checkout.resolve())}


def test_install_does_not_touch_existing_compose_files(monkeypatch, tmp_path):
    checkout = _make_fake_checkout(tmp_path / "repo")
    instance = checkout / "deploy" / "prod"
    original_compose = (instance / "docker-compose.yml").read_text()
    original_template = (instance / "config.yaml.template").read_text()
    monkeypatch.setattr(git_source, "run", _fake_run([]))
    monkeypatch.setattr(git_source, "build_images", lambda repo_root, version: ("o", "u"))

    git_source.install(checkout, ref=None)

    assert (instance / "docker-compose.yml").read_text() == original_compose
    assert (instance / "config.yaml.template").read_text() == original_template


def test_install_with_ref_checks_out_before_resolving_version(monkeypatch, tmp_path):
    checkout = _make_fake_checkout(tmp_path / "repo")
    calls = []
    monkeypatch.setattr(git_source, "run", _fake_run(calls))
    monkeypatch.setattr(git_source, "build_images", lambda repo_root, version: ("o", "u"))

    git_source.install(checkout, ref="v1.2.3")

    assert calls[0] == ["git", "-C", str(checkout), "checkout", "v1.2.3"]
    assert calls[1] == ["git", "-C", str(checkout), "describe", "--tags", "--always", "--dirty"]


def test_install_builds_images_tagged_with_resolved_version(monkeypatch, tmp_path):
    checkout = _make_fake_checkout(tmp_path / "repo")
    calls = []
    monkeypatch.setattr(git_source, "run", _fake_run(calls))
    build_calls = []
    monkeypatch.setattr(
        git_source,
        "build_images",
        lambda repo_root, version: build_calls.append((repo_root, version)) or (f"soar-orchestrator:{version}", f"soar-ui:{version}"),
    )

    git_source.install(checkout, ref=None)

    assert build_calls == [(checkout.resolve(), "v1.2.3-4-gabcdef")]
    assert not any(c[:2] == ["docker", "save"] for c in calls)
    assert not any(c[:2] == ["docker", "load"] for c in calls)
    assert not any(c[:2] == ["git", "clone"] for c in calls)


def test_update_without_source_json_raises_before_any_call(monkeypatch, tmp_path):
    dest = tmp_path / "instance"
    dest.mkdir()
    calls = []
    monkeypatch.setattr(git_source, "run", _fake_run(calls))

    with pytest.raises(FileNotFoundError):
        git_source.update(dest, ref=None, migrate=None)

    assert calls == []


def test_update_with_ref_fetches_and_checks_out(monkeypatch, tmp_path):
    checkout = _make_fake_checkout(tmp_path / "repo")
    dest = tmp_path / "instance"
    dest.mkdir()
    (dest / "source.json").write_text(json.dumps({"checkout": str(checkout)}))
    (dest / ".env").write_text("SOAR_VERSION=0.1.0\n")

    calls = []
    monkeypatch.setattr(git_source, "run", _fake_run(calls))
    monkeypatch.setattr(git_source, "build_images", lambda repo_root, version: ("o", "u"))
    update_calls = []
    monkeypatch.setattr(git_source, "update_version", lambda instance, version: update_calls.append((instance, version)))
    up_calls = []
    monkeypatch.setattr(git_source, "compose_up", lambda instance: up_calls.append(instance))

    git_source.update(dest, ref="v2.0.0", migrate=None)

    assert calls[0] == ["git", "-C", str(checkout), "fetch", "--tags"]
    assert calls[1] == ["git", "-C", str(checkout), "checkout", "v2.0.0"]
    assert not any(c[:3] == ["git", "-C", str(checkout)] and "pull" in c for c in calls)
    assert update_calls == [(dest, "v1.2.3-4-gabcdef")]
    assert up_calls == [dest]


def test_update_without_ref_pulls_ff_only(monkeypatch, tmp_path):
    checkout = _make_fake_checkout(tmp_path / "repo")
    dest = tmp_path / "instance"
    dest.mkdir()
    (dest / "source.json").write_text(json.dumps({"checkout": str(checkout)}))

    calls = []
    monkeypatch.setattr(git_source, "run", _fake_run(calls))
    monkeypatch.setattr(git_source, "build_images", lambda repo_root, version: ("o", "u"))
    monkeypatch.setattr(git_source, "update_version", lambda instance, version: None)
    monkeypatch.setattr(git_source, "compose_up", lambda instance: None)

    git_source.update(dest, ref=None, migrate=None)

    assert calls[0] == ["git", "-C", str(checkout), "fetch", "--tags"]
    assert calls[1] == ["git", "-C", str(checkout), "pull", "--ff-only"]


def test_update_migrate_fresh_calls_stamp_head(monkeypatch, tmp_path):
    checkout = _make_fake_checkout(tmp_path / "repo")
    dest = tmp_path / "instance"
    dest.mkdir()
    (dest / "source.json").write_text(json.dumps({"checkout": str(checkout)}))

    monkeypatch.setattr(git_source, "run", _fake_run([]))
    monkeypatch.setattr(git_source, "build_images", lambda repo_root, version: ("o", "u"))
    monkeypatch.setattr(git_source, "update_version", lambda instance, version: None)
    monkeypatch.setattr(git_source, "compose_up", lambda instance: None)
    stamp_calls = []
    upgrade_calls = []
    monkeypatch.setattr(git_source.migrate_module, "stamp_head", lambda instance: stamp_calls.append(instance))
    monkeypatch.setattr(git_source.migrate_module, "upgrade_head", lambda instance: upgrade_calls.append(instance))

    git_source.update(dest, ref=None, migrate="fresh")

    assert stamp_calls == [dest]
    assert upgrade_calls == []


def test_update_migrate_upgrade_calls_upgrade_head(monkeypatch, tmp_path):
    checkout = _make_fake_checkout(tmp_path / "repo")
    dest = tmp_path / "instance"
    dest.mkdir()
    (dest / "source.json").write_text(json.dumps({"checkout": str(checkout)}))

    monkeypatch.setattr(git_source, "run", _fake_run([]))
    monkeypatch.setattr(git_source, "build_images", lambda repo_root, version: ("o", "u"))
    monkeypatch.setattr(git_source, "update_version", lambda instance, version: None)
    monkeypatch.setattr(git_source, "compose_up", lambda instance: None)
    stamp_calls = []
    upgrade_calls = []
    monkeypatch.setattr(git_source.migrate_module, "stamp_head", lambda instance: stamp_calls.append(instance))
    monkeypatch.setattr(git_source.migrate_module, "upgrade_head", lambda instance: upgrade_calls.append(instance))

    git_source.update(dest, ref=None, migrate="upgrade")

    assert upgrade_calls == [dest]
    assert stamp_calls == []


def test_update_without_migrate_flag_runs_no_migration(monkeypatch, tmp_path):
    checkout = _make_fake_checkout(tmp_path / "repo")
    dest = tmp_path / "instance"
    dest.mkdir()
    (dest / "source.json").write_text(json.dumps({"checkout": str(checkout)}))

    monkeypatch.setattr(git_source, "run", _fake_run([]))
    monkeypatch.setattr(git_source, "build_images", lambda repo_root, version: ("o", "u"))
    monkeypatch.setattr(git_source, "update_version", lambda instance, version: None)
    monkeypatch.setattr(git_source, "compose_up", lambda instance: None)
    stamp_calls = []
    upgrade_calls = []
    monkeypatch.setattr(git_source.migrate_module, "stamp_head", lambda instance: stamp_calls.append(instance))
    monkeypatch.setattr(git_source.migrate_module, "upgrade_head", lambda instance: upgrade_calls.append(instance))

    git_source.update(dest, ref=None, migrate=None)

    assert stamp_calls == []
    assert upgrade_calls == []
