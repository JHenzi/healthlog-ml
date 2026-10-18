"""Test fixtures: a real TimescaleDB with HealthLog's schema, our bootstrap and our migrations.

Set ``COMPANION_TEST_ADMIN_URL`` to a superuser URL whose database name ends in
``_test`` (the suite refuses anything else, because it resets the schema):

    postgresql+psycopg://healthlog:healthlog@127.0.0.1:5432/companion_test

Per session: create the database if needed, run HealthLog's own migrations
from ``UPSTREAM_BACKEND_DIR`` (default ``../backend``) in a subprocess, run
``bootstrap/bootstrap.sql`` and our migrations (down to base, then up). Each
test then runs in a rolled-back transaction as the ``companion`` role.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

COMPANION_DIR = Path(__file__).resolve().parents[1]
REPO_DIR = COMPANION_DIR.parent
DEFAULT_ADMIN_URL = "postgresql+psycopg://healthlog:healthlog@127.0.0.1:5432/companion_test"
COMPANION_PASSWORD = "companion-test-password"
TEST_TZ = "America/New_York"


def _admin_url() -> str:
    url = os.environ.get("COMPANION_TEST_ADMIN_URL", DEFAULT_ADMIN_URL)
    if not (make_url(url).database or "").endswith("_test"):
        pytest.exit(f"refusing to run: test database name must end in '_test' ({make_url(url).database!r})", 2)
    return url


def _ensure_database(admin_url: str) -> None:
    url = make_url(admin_url)
    maintenance = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with maintenance.connect() as conn:
        exists = conn.execute(text("SELECT 1 FROM pg_database WHERE datname = :d"), {"d": url.database}).first()
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{url.database}"'))
    maintenance.dispose()


def _upstream_migrations(admin_url: str) -> None:
    backend = Path(os.environ.get("UPSTREAM_BACKEND_DIR", REPO_DIR / "backend"))
    env = {**os.environ, "DATABASE_URL": admin_url, "PYTHONPATH": str(backend)}
    subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(backend / "alembic.ini"), "upgrade", "head"],
        cwd=backend,
        env=env,
        check=True,
        capture_output=True,
    )


def bootstrap_sql(password: str = COMPANION_PASSWORD) -> str:
    """bootstrap.sql with the psql variable filled in (psql isn't available to the test process)."""
    sql = (COMPANION_DIR / "bootstrap" / "bootstrap.sql").read_text()
    return sql.replace(":'companion_password'", "'" + password.replace("'", "''") + "'")


def _run_bootstrap(admin_engine) -> None:
    # Raw driver call without parameters: psycopg then leaves the script's '%L' format() specifiers alone.
    raw = admin_engine.raw_connection()
    try:
        raw.driver_connection.execute(bootstrap_sql())
        raw.commit()
    finally:
        raw.close()


def companion_url(admin_url: str) -> str:
    return (
        make_url(admin_url).set(username="companion", password=COMPANION_PASSWORD).render_as_string(hide_password=False)
    )


@pytest.fixture(scope="session")
def admin_url() -> str:
    return _admin_url()


@pytest.fixture(scope="session")
def admin_engine(admin_url):
    _ensure_database(admin_url)
    _upstream_migrations(admin_url)
    engine = create_engine(admin_url)
    _run_bootstrap(engine)
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def companion_db_url(admin_engine, admin_url) -> str:
    url = companion_url(admin_url)
    os.environ["DATABASE_URL"] = url
    os.environ["TZ"] = TEST_TZ
    os.environ.setdefault("DAY_BOUNDARY", "04:00")

    from alembic import command
    from alembic.config import Config

    from app.config import get_settings
    from app.db import get_engine

    get_settings.cache_clear()
    get_engine.cache_clear()
    cfg = Config(str(COMPANION_DIR / "alembic.ini"))
    cfg.attributes["database_url"] = url
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    return url


@pytest.fixture(scope="session")
def companion_engine(companion_db_url):
    engine = create_engine(companion_db_url)
    yield engine
    engine.dispose()


@pytest.fixture
def db_conn(companion_engine):
    conn = companion_engine.connect()
    trans = conn.begin()
    yield conn
    trans.rollback()
    conn.close()


@pytest.fixture
def db(db_conn) -> Session:
    session = Session(bind=db_conn, join_transaction_mode="create_savepoint")
    yield session
    session.close()


@pytest.fixture
def client(db):
    """HTTPS TestClient (so Secure cookies flow) sharing the test transaction."""
    from fastapi.testclient import TestClient

    from app.db import get_db
    from app.main import create_app

    app = create_app(check_on_startup=False)
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app, base_url="https://testserver") as c:
        yield c
