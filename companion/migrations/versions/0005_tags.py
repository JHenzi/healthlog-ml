"""tracker tags

Revision ID: 0005_tags
Revises: 0004_trackers
Create Date: 2026-10-18

Tags: quick picks attached to a tracker ("meeting heavy", "in-fighting"),
logged per day next to (or instead of) a value. ``trackers.tags`` holds their
display text and is editable at any time; an entry stores the tag's slug in
``observations.tag``. A new ``tags`` type is a tracker that is only tags.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_tags"
down_revision: str | None = "0004_trackers"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "companion"

OLD_TYPES = "'count', 'scale', 'check', 'quantity', 'duration', 'time', 'choice', 'moment'"
NEW_TYPES = OLD_TYPES + ", 'tags'"


def upgrade() -> None:
    op.add_column(
        "trackers",
        sa.Column("tags", postgresql.ARRAY(sa.Text()), nullable=False, server_default="{}"),
        schema=SCHEMA,
    )
    op.add_column("observations", sa.Column("tag", sa.Text(), nullable=True), schema=SCHEMA)
    op.drop_constraint("ck_trackers_type", "trackers", schema=SCHEMA)
    op.create_check_constraint("ck_trackers_type", "trackers", f"type IN ({NEW_TYPES})", schema=SCHEMA)


def downgrade() -> None:
    op.execute(f"DELETE FROM {SCHEMA}.observations WHERE tag IS NOT NULL")
    op.drop_constraint("ck_trackers_type", "trackers", schema=SCHEMA)
    op.create_check_constraint("ck_trackers_type", "trackers", f"type IN ({OLD_TYPES})", schema=SCHEMA)
    op.drop_column("observations", "tag", schema=SCHEMA)
    op.drop_column("trackers", "tags", schema=SCHEMA)
