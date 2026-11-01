"""note trackers

Revision ID: 0008_notes
Revises: 0007_push_subscriptions
Create Date: 2026-10-31

A ``note`` tracker holds free text for a day (the diary). A tag entry with
``value_num`` 0 means "recorded as off", which needs no schema change.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0008_notes"
down_revision: str | None = "0007_push_subscriptions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "companion"

OLD_TYPES = "'count', 'scale', 'check', 'quantity', 'duration', 'time', 'choice', 'moment', 'tags'"
NEW_TYPES = OLD_TYPES + ", 'note'"


def upgrade() -> None:
    op.drop_constraint("ck_trackers_type", "trackers", schema=SCHEMA)
    op.create_check_constraint("ck_trackers_type", "trackers", f"type IN ({NEW_TYPES})", schema=SCHEMA)


def downgrade() -> None:
    op.execute(
        f"DELETE FROM {SCHEMA}.observations WHERE tracker_id IN (SELECT id FROM {SCHEMA}.trackers WHERE type = 'note')"
    )
    op.execute(f"DELETE FROM {SCHEMA}.trackers WHERE type = 'note'")
    op.drop_constraint("ck_trackers_type", "trackers", schema=SCHEMA)
    op.create_check_constraint("ck_trackers_type", "trackers", f"type IN ({OLD_TYPES})", schema=SCHEMA)
