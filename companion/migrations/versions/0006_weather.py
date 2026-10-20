"""weather hours

Revision ID: 0006_weather
Revises: 0005_tags
Create Date: 2026-10-20

M3: hourly weather and air quality for the home area, loaded from the
collector's file (``app/outside.py``). One row per UTC hour; a missing value
is NULL. Daily weather features are computed from it on every refresh.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_weather"
down_revision: str | None = "0005_tags"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "companion"

COLUMNS = (
    "temperature_c",
    "humidity_pct",
    "dew_point_c",
    "pressure_hpa",
    "precipitation_mm",
    "cloud_pct",
    "wind_kmh",
    "uv_index",
    "radiation_wm2",
    "pm25",
    "pm10",
    "us_aqi",
)


def upgrade() -> None:
    op.create_table(
        "weather_hours",
        sa.Column("time", sa.DateTime(timezone=True), primary_key=True),
        *(sa.Column(c, sa.Float(), nullable=True) for c in COLUMNS),
        sa.Column("loaded_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_table("weather_hours", schema=SCHEMA)
