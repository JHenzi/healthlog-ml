"""push subscriptions

Revision ID: 0007_push_subscriptions
Revises: 0006_weather
Create Date: 2026-10-22

Reminders (web push, opt-in): one row per phone or browser that asked for them. The endpoint is the push
service's URL for that device; p256dh and auth are its public encryption key and secret, used to seal each
reminder so only the device can read it (``app/push.py``).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_push_subscriptions"
down_revision: str | None = "0006_weather"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "companion"


def upgrade() -> None:
    op.create_table(
        "push_subscriptions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("endpoint", sa.Text(), nullable=False, unique=True),
        sa.Column("p256dh", sa.Text(), nullable=False),
        sa.Column("auth", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_status", sa.Integer(), nullable=True),
        sa.Column("last_sent_at", sa.DateTime(timezone=True), nullable=True),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_table("push_subscriptions", schema=SCHEMA)
