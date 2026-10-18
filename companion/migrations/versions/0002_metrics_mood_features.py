"""metric_settings, mood_entries, feature_defs, daily_features

Revision ID: 0002_metrics_mood_features
Revises: 0001_initial
Create Date: 2026-10-17

M2: every HealthLog metric becomes analysable. ``metric_settings`` is our
editable copy of HealthLog's registry; ``mood_entries`` holds State of Mind entries read
from HealthLog's raw archive; ``daily_features`` (+ ``feature_defs``) is the
one-row-per-day-per-feature cache every analysis reads, rebuilt from scratch.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_metrics_mood_features"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "companion"


def upgrade() -> None:
    op.create_table(
        "metric_settings",
        sa.Column("metric", sa.Text(), primary_key=True),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("unit", sa.Text(), nullable=True),
        sa.Column("category", sa.Text(), nullable=True),
        sa.Column("aggregation", sa.Text(), nullable=False),
        sa.Column("min_value", sa.Float(), nullable=True),
        sa.Column("max_value", sa.Float(), nullable=True),
        sa.Column("source_priority", postgresql.ARRAY(sa.Text()), nullable=False, server_default="{}"),
        sa.Column("analyse", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("user_edited", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("aggregation IN ('sum', 'avg', 'min', 'max')", name="ck_metric_settings_aggregation"),
        schema=SCHEMA,
    )
    op.create_table(
        "mood_entries",
        sa.Column("hae_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("kind", sa.Text(), nullable=True),
        sa.Column("valence", sa.Float(), nullable=True),
        sa.Column("valence_classification", sa.Text(), nullable=True),
        sa.Column("labels", postgresql.ARRAY(sa.Text()), nullable=False, server_default="{}"),
        sa.Column("associations", postgresql.ARRAY(sa.Text()), nullable=False, server_default="{}"),
        # The HealthLog raw-archive row the entry was last seen in (no foreign key: R2).
        sa.Column("payload_id", sa.BigInteger(), nullable=False),
        schema=SCHEMA,
    )
    op.create_index("ix_mood_entries_start_time", "mood_entries", ["start_time"], schema=SCHEMA)
    op.create_table(
        "feature_defs",
        sa.Column("feature", sa.Text(), primary_key=True),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("unit", sa.Text(), nullable=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("analyse", sa.Boolean(), nullable=False, server_default="true"),
        schema=SCHEMA,
    )
    op.create_table(
        "daily_features",
        sa.Column("day", sa.Date(), primary_key=True),
        sa.Column("feature", sa.Text(), primary_key=True),
        sa.Column("value", sa.Float(), nullable=False),
        schema=SCHEMA,
    )
    op.create_index("ix_daily_features_feature_day", "daily_features", ["feature", "day"], schema=SCHEMA)


def downgrade() -> None:
    op.drop_table("daily_features", schema=SCHEMA)
    op.drop_table("feature_defs", schema=SCHEMA)
    op.drop_table("mood_entries", schema=SCHEMA)
    op.drop_table("metric_settings", schema=SCHEMA)
