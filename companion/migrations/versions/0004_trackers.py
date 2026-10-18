"""trackers, events, observations, day_reviews

Revision ID: 0004_trackers
Revises: 0003_insights
Create Date: 2026-10-17

M4: custom tracking beyond Apple Health. A tracker is a row (design §2: data,
not code). ``events`` is the append-only log and the source of truth;
``observations`` and ``day_reviews`` are derived from it and can be rebuilt
by replaying it. Deletes are tombstone events, never row deletes.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_trackers"
down_revision: str | None = "0003_insights"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "companion"

TYPES = "'count', 'scale', 'check', 'quantity', 'duration', 'time', 'choice', 'moment'"


def upgrade() -> None:
    op.create_table(
        "trackers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("key", sa.Text(), nullable=False, unique=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("unit", sa.Text(), nullable=True),
        sa.Column("scale_min", sa.Float(), nullable=True),
        sa.Column("scale_max", sa.Float(), nullable=True),
        sa.Column("scale_labels", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("options", postgresql.ARRAY(sa.Text()), nullable=False, server_default="{}"),
        sa.Column("polarity", sa.Text(), nullable=False, server_default="neutral"),
        sa.Column("category", sa.Text(), nullable=True),
        sa.Column("in_review", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("always_logged", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("pinned", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("archived", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("successor_id", sa.Integer(), sa.ForeignKey(f"{SCHEMA}.trackers.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(f"type IN ({TYPES})", name="ck_trackers_type"),
        sa.CheckConstraint("key ~ '^[a-z][a-z0-9_]{0,63}$'", name="ck_trackers_key"),
        sa.CheckConstraint("polarity IN ('good', 'bad', 'neutral')", name="ck_trackers_polarity"),
        schema=SCHEMA,
    )
    op.create_table(
        "events",
        sa.Column("seq", sa.BigInteger(), primary_key=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        # The observation (or review day) the event is about; device-generated for offline capture.
        sa.Column("client_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("op", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.CheckConstraint("op IN ('log', 'edit', 'delete', 'review', 'unreview')", name="ck_events_op"),
        schema=SCHEMA,
    )
    op.create_index("ix_events_client_id", "events", ["client_id"], schema=SCHEMA)
    op.create_table(
        "observations",
        sa.Column("client_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tracker_id", sa.Integer(), sa.ForeignKey(f"{SCHEMA}.trackers.id"), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("value_num", sa.Float(), nullable=True),
        sa.Column("value_text", sa.Text(), nullable=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("deleted", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("updated_seq", sa.BigInteger(), nullable=False),
        schema=SCHEMA,
    )
    op.create_index("ix_observations_tracker_day", "observations", ["tracker_id", "day"], schema=SCHEMA)
    op.create_table(
        "day_reviews",
        sa.Column("day", sa.Date(), primary_key=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_table("day_reviews", schema=SCHEMA)
    op.drop_table("observations", schema=SCHEMA)
    op.drop_table("events", schema=SCHEMA)
    op.drop_table("trackers", schema=SCHEMA)
