"""initial schema

Revision ID: 817599408074
Revises: 
Create Date: 2026-11-10 17:48:41.724424
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '817599408074'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('health_metrics',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('type', sa.String(length=32), nullable=False),
    sa.Column('day', sa.Date(), nullable=False),
    sa.Column('value', sa.Float(), nullable=False),
    sa.Column('unit', sa.String(length=32), nullable=False),
    sa.Column('measured_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('type', 'day', name='uq_health_metrics_type_day')
    )
    op.create_table('imports',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('filename', sa.String(length=255), nullable=False),
    sa.Column('size_bytes', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('progress', sa.Float(), nullable=False),
    sa.Column('message', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('finished_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('workouts',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('import_id', sa.String(length=32), nullable=True),
    sa.Column('source_name', sa.String(length=255), nullable=True),
    sa.Column('start_at', sa.DateTime(), nullable=False),
    sa.Column('end_at', sa.DateTime(), nullable=False),
    sa.Column('utc_offset_min', sa.Integer(), nullable=False),
    sa.Column('distance_m', sa.Float(), nullable=False),
    sa.Column('duration_s', sa.Float(), nullable=False),
    sa.Column('avg_hr', sa.Float(), nullable=True),
    sa.Column('max_hr', sa.Float(), nullable=True),
    sa.Column('energy_kcal', sa.Float(), nullable=True),
    sa.Column('elevation_gain_m', sa.Float(), nullable=True),
    sa.Column('avg_cadence', sa.Float(), nullable=True),
    sa.Column('temperature_c', sa.Float(), nullable=True),
    sa.Column('indoor', sa.Boolean(), nullable=False),
    sa.ForeignKeyConstraint(['import_id'], ['imports.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('workouts', schema=None) as batch_op:
        batch_op.create_index('ix_workouts_start_at', ['start_at'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('workouts', schema=None) as batch_op:
        batch_op.drop_index('ix_workouts_start_at')

    op.drop_table('workouts')
    op.drop_table('imports')
    op.drop_table('health_metrics')
