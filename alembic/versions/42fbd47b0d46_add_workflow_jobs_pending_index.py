"""add partial index on workflow_jobs(status, triggered_at) where status='PENDING'

Revision ID: 42fbd47b0d46
Revises: 3067dea7c75b
Create Date: 2026-07-27 00:00:00.000000

Keeps SQLQueue.pop()'s atomic claim query (see
docs/compose/specs/2026-07-27-sql-job-queue-design.md [S4]/[S5]) cheap
independent of how many historical COMPLETED/FAILED/TIMEOUT/CANCELLED rows
accumulate in workflow_jobs.

NOTE: uses `prefixed("workflow_jobs")`, consistent with ea0bb43fc071 (which
already accounted for `database.table_prefix` correctly) and 3067dea7c75b
(fixed to do the same in this same change — see
docs/compose/specs/2026-07-28-workflow-jobs-index-table-prefix-design.md).
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from orchestrator.db.base import prefixed

# revision identifiers, used by Alembic.
revision: str = '42fbd47b0d46'
down_revision: str | Sequence[str] | None = '3067dea7c75b'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_index(
        f"ix_{prefixed('workflow_jobs')}_pending_triggered_at",
        prefixed("workflow_jobs"),
        ["status", "triggered_at"],
        postgresql_where=sa.text("status = 'PENDING'"),
        sqlite_where=sa.text("status = 'PENDING'"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        f"ix_{prefixed('workflow_jobs')}_pending_triggered_at",
        table_name=prefixed("workflow_jobs"),
    )
