"""add audit_log table

Revision ID: 3067dea7c75b
Revises: ea0bb43fc071
Create Date: 2026-07-18 12:15:15.635811

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from orchestrator.db.base import prefixed

# revision identifiers, used by Alembic.
revision: str = '3067dea7c75b'
down_revision: str | Sequence[str] | None = 'ea0bb43fc071'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(prefixed('audit_log'),
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('actor_id', sa.Integer(), nullable=False),
    sa.Column('actor_type', sa.String(length=16), nullable=False),
    sa.Column('actor_name', sa.String(length=128), nullable=False),
    sa.Column('action', sa.String(length=64), nullable=False),
    sa.Column('resource_type', sa.String(length=32), nullable=False),
    sa.Column('resource_id', sa.String(length=255), nullable=False),
    sa.Column('client_ip', sa.String(length=64), nullable=True),
    sa.Column('request_id', sa.String(length=32), nullable=True),
    sa.Column('detail', sa.JSON(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(f"ix_{prefixed('audit_log')}_action", prefixed('audit_log'), ['action'], unique=False)
    op.create_index(f"ix_{prefixed('audit_log')}_created_at", prefixed('audit_log'), ['created_at'], unique=False)
    op.create_index(f"ix_{prefixed('audit_log')}_resource_id", prefixed('audit_log'), ['resource_id'], unique=False)
    op.create_index(f"ix_{prefixed('audit_log')}_resource_type", prefixed('audit_log'), ['resource_type'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(f"ix_{prefixed('audit_log')}_resource_type", table_name=prefixed('audit_log'))
    op.drop_index(f"ix_{prefixed('audit_log')}_resource_id", table_name=prefixed('audit_log'))
    op.drop_index(f"ix_{prefixed('audit_log')}_created_at", table_name=prefixed('audit_log'))
    op.drop_index(f"ix_{prefixed('audit_log')}_action", table_name=prefixed('audit_log'))
    op.drop_table(prefixed('audit_log'))
