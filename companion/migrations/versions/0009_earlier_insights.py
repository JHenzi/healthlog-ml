"""insights.first_seen/last_seen, earlier_insights

Revision ID: 0009_earlier_insights
Revises: 0008_notes
Create Date: 2026-11-04

Roadmap B17. Each run still replaces ``insights``; a finding that was reported
before and isn't now moves to ``earlier_insights`` with the days it held, and
moves back if it clears the bar again. Presentation only: the analysis never
reads this table (R8).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009_earlier_insights"
down_revision: str | None = "0008_notes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "companion"


def upgrade() -> None:
    op.add_column("insights", sa.Column("first_seen", sa.Date(), nullable=True), schema=SCHEMA)
    op.add_column("insights", sa.Column("last_seen", sa.Date(), nullable=True), schema=SCHEMA)
    op.create_table(
        "earlier_insights",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        # kind|horizon|feature_a|feature_b|lag|method: the same finding across runs
        sa.Column("key", sa.Text(), nullable=False, unique=True),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("horizon", sa.Text(), nullable=False),
        sa.Column("feature_a", sa.Text(), nullable=False),
        sa.Column("feature_b", sa.Text(), nullable=True),
        sa.Column("lag", sa.Integer(), nullable=True),
        sa.Column("method", sa.Text(), nullable=False),
        sa.Column("effect", sa.Float(), nullable=False),
        sa.Column("p_adj", sa.Float(), nullable=False),
        sa.Column("n", sa.Integer(), nullable=False),
        sa.Column("strength", sa.Text(), nullable=False),
        sa.Column("sentence", sa.Text(), nullable=False),
        sa.Column("details", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("first_seen", sa.Date(), nullable=True),
        sa.Column("last_held", sa.Date(), nullable=False),
        sa.Column("dropped_on", sa.Date(), nullable=False),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_table("earlier_insights", schema=SCHEMA)
    op.drop_column("insights", "last_seen", schema=SCHEMA)
    op.drop_column("insights", "first_seen", schema=SCHEMA)
