"""initial auth and jobs tables

Revision ID: ea0bb43fc071
Revises:
Create Date: 2026-07-17 13:12:41.889447

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from orchestrator.db.base import fk, prefixed

# revision identifiers, used by Alembic.
revision: str = 'ea0bb43fc071'
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# NOTE: table AND index/constraint names go through prefixed()/fk() — not just
# table names — because Postgres index names must be unique per-schema, not
# per-table. Two instances sharing one database with different table_prefix
# values would collide on a bare 'ix_workflow_jobs_status' otherwise. Every
# future migration touching these tables must follow the same convention.


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(prefixed('api_keys'),
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('name', sa.String(length=128), nullable=False),
    sa.Column('key_prefix', sa.String(length=12), nullable=False),
    sa.Column('key_hash', sa.String(length=64), nullable=False),
    sa.Column('role', sa.String(length=32), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('key_hash')
    )
    op.create_table(prefixed('users'),
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('username', sa.String(length=64), nullable=False),
    sa.Column('password_hash', sa.String(length=128), nullable=False),
    sa.Column('role', sa.String(length=32), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('username')
    )
    op.create_table(prefixed('workflow_jobs'),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('workflow_name', sa.String(length=255), nullable=False),
    sa.Column('workflow_type', sa.String(length=64), nullable=False),
    sa.Column('triggered_by', sa.String(length=255), nullable=False),
    sa.Column('context', sa.JSON(), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('concurrency', sa.String(length=32), nullable=False),
    sa.Column('pid', sa.Integer(), nullable=True),
    sa.Column('log_path', sa.String(length=1024), nullable=True),
    sa.Column('timeout', sa.Integer(), nullable=True),
    sa.Column('triggered_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('result_success', sa.Boolean(), nullable=True),
    sa.Column('result_data', sa.JSON(), nullable=True),
    sa.Column('result_error', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(f"ix_{prefixed('workflow_jobs')}_status", prefixed('workflow_jobs'), ['status'], unique=False)
    op.create_index(f"ix_{prefixed('workflow_jobs')}_triggered_at", prefixed('workflow_jobs'), ['triggered_at'], unique=False)
    op.create_index(f"ix_{prefixed('workflow_jobs')}_workflow_name", prefixed('workflow_jobs'), ['workflow_name'], unique=False)
    op.create_table(prefixed('refresh_tokens'),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], [fk('users', 'id')], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(f"ix_{prefixed('refresh_tokens')}_token_hash", prefixed('refresh_tokens'), ['token_hash'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(f"ix_{prefixed('refresh_tokens')}_token_hash", table_name=prefixed('refresh_tokens'))
    op.drop_table(prefixed('refresh_tokens'))
    op.drop_index(f"ix_{prefixed('workflow_jobs')}_workflow_name", table_name=prefixed('workflow_jobs'))
    op.drop_index(f"ix_{prefixed('workflow_jobs')}_triggered_at", table_name=prefixed('workflow_jobs'))
    op.drop_index(f"ix_{prefixed('workflow_jobs')}_status", table_name=prefixed('workflow_jobs'))
    op.drop_table(prefixed('workflow_jobs'))
    op.drop_table(prefixed('users'))
    op.drop_table(prefixed('api_keys'))
