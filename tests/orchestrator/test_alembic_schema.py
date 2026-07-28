"""Smoke test: alembic upgrade head must produce exactly the schema Base.metadata
describes — catches drift between the versioned migration and the ORM models.

Runs `alembic upgrade head` as a subprocess (same as the real deploy runbook),
not via alembic.command.upgrade() in-process — the latter calls asyncio.run()
internally (see alembic/env.py's async migration recipe), which tears down
the event loop this test session's pytest-asyncio fixtures depend on and
corrupts every async test collected after this one.
"""

import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect

# Import models so Base.metadata is fully populated for comparison.
from orchestrator.audit import models as _audit_models  # noqa: F401
from orchestrator.auth import models as _auth_models  # noqa: F401
from orchestrator.db.base import Base
from orchestrator.store import models as _store_models  # noqa: F401

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def test_alembic_upgrade_head_matches_orm_metadata(tmp_path):
    db_path = tmp_path / "alembic_schema_test.db"
    config_path = tmp_path / "config.yaml"
    config_path.write_text(f"database:\n  url: sqlite+aiosqlite:///{db_path.as_posix()}\n")

    env = {**os.environ, "SOAR_CONFIG": str(config_path)}
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=str(_REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr

    sync_engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    inspector = inspect(sync_engine)

    reflected_tables = set(inspector.get_table_names()) - {"alembic_version"}
    expected_tables = set(Base.metadata.tables.keys())
    assert reflected_tables == expected_tables

    for table_name, table in Base.metadata.tables.items():
        reflected_columns = {c["name"] for c in inspector.get_columns(table_name)}
        expected_columns = {c.name for c in table.columns}
        assert reflected_columns == expected_columns, table_name

    sync_engine.dispose()


def test_alembic_upgrade_head_respects_table_prefix(tmp_path):
    """Regression test for BAGFIX_PLAN S6: 3067dea7c75b and 42fbd47b0d46 used to
    hardcode literal table/index names, silently ignoring database.table_prefix
    (unlike ea0bb43fc071, which already used prefixed()/fk() throughout)."""
    db_path = tmp_path / "alembic_schema_prefix_test.db"
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        f"database:\n"
        f"  url: sqlite+aiosqlite:///{db_path.as_posix()}\n"
        f"  table_prefix: test_\n"
    )

    env = {**os.environ, "SOAR_CONFIG": str(config_path)}
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=str(_REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr

    sync_engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    inspector = inspect(sync_engine)

    reflected_tables = set(inspector.get_table_names()) - {"alembic_version"}
    assert reflected_tables == {
        "test_api_keys",
        "test_users",
        "test_workflow_jobs",
        "test_refresh_tokens",
        "test_audit_log",
    }

    all_index_names = {
        index["name"]
        for table_name in reflected_tables
        for index in inspector.get_indexes(table_name)
    }
    unprefixed_bug_names = {
        "ix_workflow_jobs_pending_triggered_at",
        "ix_audit_log_action",
        "ix_audit_log_created_at",
        "ix_audit_log_resource_id",
        "ix_audit_log_resource_type",
    }
    assert not (all_index_names & unprefixed_bug_names)

    sync_engine.dispose()
