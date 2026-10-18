"""Companion migrations: own history in schema companion, reversible (risks.md F2)."""

from __future__ import annotations

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from tests.conftest import COMPANION_DIR


def _tables(url: str) -> set[str]:
    engine = create_engine(url)
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname = 'companion'")).scalars().all()
    engine.dispose()
    return set(rows)


def test_version_table_lives_in_companion_schema(companion_db_url):
    tables = _tables(companion_db_url)
    assert {"alembic_version", "users", "sessions", "api_tokens", "settings"} <= tables


def test_down_and_up_round_trip(companion_db_url):
    cfg = Config(str(COMPANION_DIR / "alembic.ini"))
    cfg.attributes["database_url"] = companion_db_url
    command.downgrade(cfg, "base")
    assert _tables(companion_db_url) == {"alembic_version"}
    command.upgrade(cfg, "head")
    assert "users" in _tables(companion_db_url)
