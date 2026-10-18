"""feature_defs.family, insights

Revision ID: 0003_insights
Revises: 0002_metrics_mood_features
Create Date: 2026-10-17

M5: the analysis engine. ``family`` groups features that are linked by
definition (steps and distance, sleep and its stages, stress and the heart
rate it's derived from); the engine only relates features across families.
``insights`` holds the latest run's findings, each with its numbers and
evidence (R13), replaced on every run.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_insights"
down_revision: str | None = "0002_metrics_mood_features"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "companion"


def upgrade() -> None:
    op.add_column("feature_defs", sa.Column("family", sa.Text(), nullable=False, server_default="other"), schema=SCHEMA)
    op.create_table(
        "insights",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        # association | change | weekday
        sa.Column("kind", sa.Text(), nullable=False),
        # day | week | month (association: day level with lags)
        sa.Column("horizon", sa.Text(), nullable=False),
        sa.Column("feature_a", sa.Text(), nullable=False),
        sa.Column("feature_b", sa.Text(), nullable=True),
        sa.Column("lag", sa.Integer(), nullable=True),
        sa.Column("method", sa.Text(), nullable=False),
        sa.Column("effect", sa.Float(), nullable=False),
        sa.Column("p", sa.Float(), nullable=False),
        sa.Column("p_adj", sa.Float(), nullable=False),
        sa.Column("n", sa.Integer(), nullable=False),
        sa.Column("n_a", sa.Integer(), nullable=True),
        sa.Column("n_b", sa.Integer(), nullable=True),
        sa.Column("strength", sa.Text(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("sentence", sa.Text(), nullable=False),
        sa.Column("details", postgresql.JSONB(), nullable=False, server_default="{}"),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_table("insights", schema=SCHEMA)
    op.drop_column("feature_defs", "family", schema=SCHEMA)
