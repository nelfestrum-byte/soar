"""End-to-end CLI tests via subprocess — table_prefix is baked in at model
import time (see orchestrator/db/base.py), so the only way to verify the CLI
applies it correctly is to run it as a real, separate process."""
import os
import sqlite3
import subprocess
import sys

import pytest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def _run_cli(*args, config_path):
    env = {**os.environ, "SOAR_CONFIG": config_path}
    return subprocess.run(
        [sys.executable, "-m", "orchestrator.auth.cli", *args],
        capture_output=True, text=True, timeout=30, cwd=_REPO_ROOT, env=env,
    )


@pytest.fixture
def prefixed_config(tmp_path):
    db_path = tmp_path / "cli_test.db"
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        f"database:\n"
        f'  url: "sqlite+aiosqlite:///{db_path.as_posix()}"\n'
        f'  table_prefix: "cli_"\n'
    )
    return str(config_path), str(db_path)


def test_create_user_applies_table_prefix(prefixed_config):
    config_path, db_path = prefixed_config
    result = _run_cli(
        "create-user", "--username", "clitest", "--password", "x", "--role", "admin",
        config_path=config_path,
    )
    assert result.returncode == 0, result.stdout + result.stderr

    conn = sqlite3.connect(db_path)
    try:
        tables = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        assert "cli_users" in tables, tables
        assert "users" not in tables, tables
        row = conn.execute("SELECT username, role FROM cli_users").fetchone()
        assert row == ("clitest", "admin")
    finally:
        conn.close()


def test_deactivate_and_activate_user(prefixed_config):
    config_path, db_path = prefixed_config
    _run_cli("create-user", "--username", "clitest", "--password", "x", "--role", "admin",
              config_path=config_path)

    result = _run_cli("deactivate-user", "--username", "clitest", config_path=config_path)
    assert result.returncode == 0, result.stdout + result.stderr

    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute("SELECT is_active FROM cli_users WHERE username='clitest'").fetchone()
        assert row == (0,)
    finally:
        conn.close()

    result = _run_cli("activate-user", "--username", "clitest", config_path=config_path)
    assert result.returncode == 0, result.stdout + result.stderr

    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute("SELECT is_active FROM cli_users WHERE username='clitest'").fetchone()
        assert row == (1,)
    finally:
        conn.close()


def test_deactivate_unknown_user_fails(prefixed_config):
    config_path, _ = prefixed_config
    result = _run_cli("deactivate-user", "--username", "ghost", config_path=config_path)
    assert result.returncode != 0
    assert "ghost" in (result.stdout + result.stderr)
