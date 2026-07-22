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
