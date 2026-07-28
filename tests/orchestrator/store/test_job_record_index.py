"""Regression test for BAGFIX_PLAN S6: the partial index on
workflow_jobs(status, triggered_at) WHERE status='PENDING' must be created by
Base.metadata.create_all() alone (fresh installs use `soarctl migrate --fresh`,
which only stamps the alembic revision — it never runs the migration's DDL)."""

from sqlalchemy import create_engine, text

from orchestrator.db.base import Base
from orchestrator.store import models as _store_models  # noqa: F401


def test_create_all_creates_pending_index():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type = 'index'")
        ).fetchall()

    index_names = {row[0] for row in rows}
    assert "ix_workflow_jobs_pending_triggered_at" in index_names

    engine.dispose()
