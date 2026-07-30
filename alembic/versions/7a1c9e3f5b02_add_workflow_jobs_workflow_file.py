"""add workflow_file column to workflow_jobs

Revision ID: 7a1c9e3f5b02
Revises: 42fbd47b0d46
Create Date: 2026-07-30 00:00:00.000000

Privilege narrowing (Фаза 4, docs/compose/specs/2026-07-30-privilege-
narrowing-design.md): SubprocessRunner needs the workflow's .py file path
to statically scan its connector imports (parse_connector_usage) and build
a scoped config for the job's subprocess. WorkflowJob.workflow_file carries
that path from JobManager.enqueue() through to Worker._execute() — this
column lets it survive a round-trip through SQLJobStore/SQLQueue (the
InMemoryQueue passes the same Python object by reference and never needed
this, but SQL/Redis-backed installs reconstruct WorkflowJob from a
serialized form, see orchestrator/store/mapping.py and
orchestrator/core/queue/redis_queue.py).
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from orchestrator.db.base import prefixed

# revision identifiers, used by Alembic.
revision: str = '7a1c9e3f5b02'
down_revision: str | Sequence[str] | None = '42fbd47b0d46'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        prefixed("workflow_jobs"),
        sa.Column("workflow_file", sa.String(length=1024), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column(prefixed("workflow_jobs"), "workflow_file")
