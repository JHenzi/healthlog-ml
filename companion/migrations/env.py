"""Companion Alembic environment: its own history in schema ``companion`` (R12).

The version table is ``companion.alembic_version``, so it never collides with
HealthLog's ``public.alembic_version``.
"""

from __future__ import annotations

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import create_engine, pool

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models import SCHEMA, Base  # noqa: E402

config = context.config
if config.config_file_name is not None:
    # Keep loggers created before migrating (the web process migrates, then logs).
    fileConfig(config.config_file_name, disable_existing_loggers=False)


def run_migrations_online() -> None:
    url = config.attributes.get("database_url") or os.environ["DATABASE_URL"]
    engine = create_engine(url, poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=Base.metadata,
            version_table_schema=SCHEMA,
            include_schemas=False,
        )
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
