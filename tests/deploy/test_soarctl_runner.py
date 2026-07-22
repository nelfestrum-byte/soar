import subprocess

import pytest

from deploy.soarctl_lib.runner import CommandError, run


def test_run_success_returns_completed_process():
    result = run(["python", "-c", "print('ok')"])
    assert result.returncode == 0
    assert "ok" in result.stdout


def test_run_passes_cwd(tmp_path):
    result = run(["python", "-c", "import os; print(os.getcwd())"], cwd=tmp_path)
    assert str(tmp_path) in result.stdout


def test_run_raises_commanderror_on_nonzero_exit_by_default():
    with pytest.raises(CommandError) as exc_info:
        run(["python", "-c", "import sys; sys.exit(3)"])
    assert exc_info.value.returncode == 3


def test_run_check_false_does_not_raise():
    result = run(["python", "-c", "import sys; sys.exit(3)"], check=False)
    assert result.returncode == 3


def test_run_error_message_includes_argv(monkeypatch):
    def fake_run(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 1, stdout="", stderr="boom")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(CommandError) as exc_info:
        run(["docker", "compose", "up"])
    assert "docker compose up" in str(exc_info.value)
    assert "boom" in str(exc_info.value)
