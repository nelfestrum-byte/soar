import argparse

import pytest

from deploy.soarctl_lib.paths import instance_dir, read_version, repo_root


def test_repo_root_finds_directory_with_pyproject(tmp_path):
    root = tmp_path / "repo"
    (root / "deploy").mkdir(parents=True)
    (root / "pyproject.toml").write_text("[tool.x]\n")
    start = root / "deploy" / "soarctl_lib" / "paths.py"
    start.parent.mkdir(parents=True, exist_ok=True)
    start.write_text("")

    assert repo_root(start) == root


def test_repo_root_raises_if_not_found(tmp_path):
    start = tmp_path / "a" / "b" / "c.py"
    start.parent.mkdir(parents=True)
    start.write_text("")

    with pytest.raises(RuntimeError):
        repo_root(start)


def test_read_version_strips_whitespace(tmp_path):
    (tmp_path / "VERSION").write_text("1.2.3\n")
    assert read_version(tmp_path) == "1.2.3"


def test_read_version_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        read_version(tmp_path)


def test_instance_dir_defaults_to_cwd(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    args = argparse.Namespace(dir=None)
    assert instance_dir(args) == tmp_path.resolve()


def test_instance_dir_uses_explicit_flag(tmp_path):
    args = argparse.Namespace(dir=str(tmp_path / "somewhere"))
    assert instance_dir(args) == (tmp_path / "somewhere").resolve()


def test_instance_dir_explicit_flag_wins_over_auto_discovery(monkeypatch, tmp_path):
    root = tmp_path / "repo"
    (root / "deploy" / "prod").mkdir(parents=True)
    (root / "pyproject.toml").write_text("[tool.x]\n")
    (root / "deploy" / "prod" / "docker-compose.yml").write_text("services: {}\n")
    monkeypatch.chdir(root)

    args = argparse.Namespace(dir=str(tmp_path / "elsewhere"))
    assert instance_dir(args) == (tmp_path / "elsewhere").resolve()


def test_instance_dir_finds_bundle_instance_from_its_own_root(monkeypatch, tmp_path):
    instance = tmp_path / "soar-prod"
    instance.mkdir()
    (instance / "docker-compose.yml").write_text("services: {}\n")
    monkeypatch.chdir(instance)

    args = argparse.Namespace(dir=None)
    assert instance_dir(args) == instance.resolve()


def test_instance_dir_finds_bundle_instance_from_a_subdirectory(monkeypatch, tmp_path):
    instance = tmp_path / "soar-prod"
    nested = instance / "sub" / "dir"
    nested.mkdir(parents=True)
    (instance / "docker-compose.yml").write_text("services: {}\n")
    monkeypatch.chdir(nested)

    args = argparse.Namespace(dir=None)
    assert instance_dir(args) == instance.resolve()


def test_instance_dir_finds_checkout_instance_from_repo_root(monkeypatch, tmp_path):
    root = tmp_path / "repo"
    prod = root / "deploy" / "prod"
    prod.mkdir(parents=True)
    (root / "pyproject.toml").write_text("[tool.x]\n")
    (prod / "docker-compose.yml").write_text("services: {}\n")
    monkeypatch.chdir(root)

    args = argparse.Namespace(dir=None)
    assert instance_dir(args) == prod.resolve()


def test_instance_dir_finds_checkout_instance_from_a_nested_subdirectory(monkeypatch, tmp_path):
    root = tmp_path / "repo"
    prod = root / "deploy" / "prod"
    prod.mkdir(parents=True)
    (root / "pyproject.toml").write_text("[tool.x]\n")
    (prod / "docker-compose.yml").write_text("services: {}\n")
    nested = root / "orchestrator" / "api"
    nested.mkdir(parents=True)
    monkeypatch.chdir(nested)

    args = argparse.Namespace(dir=None)
    assert instance_dir(args) == prod.resolve()


def test_instance_dir_falls_back_to_cwd_when_no_markers_found(monkeypatch, tmp_path):
    empty = tmp_path / "nowhere"
    empty.mkdir()
    monkeypatch.chdir(empty)

    args = argparse.Namespace(dir=None)
    assert instance_dir(args) == empty.resolve()


def test_instance_dir_falls_back_to_cwd_when_repo_root_has_no_deploy_prod(monkeypatch, tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "pyproject.toml").write_text("[tool.x]\n")
    monkeypatch.chdir(root)

    args = argparse.Namespace(dir=None)
    assert instance_dir(args) == root.resolve()
