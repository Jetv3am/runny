"""model versions

Revision ID: 2af3a72001bd
Revises: ebf97d31e424
Create Date: 2026-11-10 23:02:14.292397
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '2af3a72001bd'
down_revision: str | None = 'ebf97d31e424'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'model_versions',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('task', sa.String(length=32), nullable=False),
        sa.Column('status', sa.String(length=24), nullable=False),
        sa.Column('trained_at', sa.DateTime(), nullable=False),
        sa.Column('examples', sa.Integer(), nullable=False),
        sa.Column('algorithm', sa.String(length=32), nullable=True),
        sa.Column('metrics', sa.JSON(), nullable=True),
        sa.Column('artifact', sa.String(length=255), nullable=True),
        sa.Column('artifact_sha256', sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_model_versions_task_trained_at', 'model_versions',
                    ['task', 'trained_at'])


def downgrade() -> None:
    op.drop_index('ix_model_versions_task_trained_at', table_name='model_versions')
    op.drop_table('model_versions')
