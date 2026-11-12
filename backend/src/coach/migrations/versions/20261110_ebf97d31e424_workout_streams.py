"""workout streams

Revision ID: ebf97d31e424
Revises: 817599408074
Create Date: 2026-11-10 21:42:12.636249
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'ebf97d31e424'
down_revision: str | None = '817599408074'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'workout_streams',
        sa.Column('workout_id', sa.String(length=32), nullable=False),
        sa.Column('sample_count', sa.Integer(), nullable=False),
        sa.Column('data', sa.LargeBinary(), nullable=False),
        sa.ForeignKeyConstraint(['workout_id'], ['workouts.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('workout_id'),
    )


def downgrade() -> None:
    op.drop_table('workout_streams')
