"""Coupling guards (risks.md A1-A6): read-only on HealthLog, no dependencies on it, one read module."""

from __future__ import annotations

import re
import shutil
import subprocess

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from app import upstream
from tests.conftest import COMPANION_DIR, REPO_DIR


def test_no_dependencies_on_public(admin_engine, companion_db_url):
    """No companion object (view, FK, function body, ...) depends on a public object (A1)."""
    with admin_engine.connect() as conn:
        deps = conn.execute(
            text(
                """
                SELECT DISTINCT dep.classid::regclass::text, dep.objid
                FROM pg_depend dep
                JOIN pg_class ref ON dep.refclassid = 'pg_class'::regclass AND dep.refobjid = ref.oid
                JOIN pg_namespace refns ON refns.oid = ref.relnamespace
                LEFT JOIN pg_rewrite rw ON dep.classid = 'pg_rewrite'::regclass AND rw.oid = dep.objid
                LEFT JOIN pg_class rwc ON rwc.oid = rw.ev_class
                LEFT JOIN pg_namespace rwns ON rwns.oid = rwc.relnamespace
                LEFT JOIN pg_constraint con ON dep.classid = 'pg_constraint'::regclass AND con.oid = dep.objid
                LEFT JOIN pg_namespace conns ON conns.oid = con.connamespace
                LEFT JOIN pg_proc pr ON dep.classid = 'pg_proc'::regclass AND pr.oid = dep.objid
                LEFT JOIN pg_namespace prns ON prns.oid = pr.pronamespace
                WHERE refns.nspname = 'public'
                  AND 'companion' IN (rwns.nspname, conns.nspname, prns.nspname)
                """
            )
        ).all()
    assert deps == []


@pytest.mark.parametrize(
    "statement",
    [
        "INSERT INTO public.metric_samples (time, metric, source) VALUES (now(), 'x', '')",
        "UPDATE public.metric_samples SET qty = 0",
        "DELETE FROM public.metric_samples",
        "TRUNCATE public.metric_samples",
        "CREATE TABLE public.companion_was_here (id int)",
        "DROP TABLE public.metric_registry",
    ],
)
def test_role_cannot_write_public(companion_engine, statement):
    """A5: Postgres itself enforces read-only, whatever our code does."""
    with companion_engine.connect() as conn:
        with pytest.raises(DBAPIError, match="permission denied|must be owner"):
            conn.execute(text(statement))
        conn.rollback()


def test_future_upstream_tables_are_readable(admin_engine, companion_db_url):
    """A4: default privileges grant SELECT on tables HealthLog adds later."""
    with admin_engine.begin() as conn:
        conn.execute(text("CREATE TABLE public.future_table_test (id int)"))
    try:
        engine = create_engine(companion_db_url)
        with engine.connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM public.future_table_test")).scalar_one() == 0
        engine.dispose()
    finally:
        with admin_engine.begin() as conn:
            conn.execute(text("DROP TABLE public.future_table_test"))


def test_contract_reports_missing_table_and_column(db, monkeypatch):
    monkeypatch.setitem(upstream.CONTRACT, "no_such_table", ("x",))
    monkeypatch.setitem(upstream.CONTRACT, "metric_samples", ("time", "no_such_column"))
    problems = {str(p) for p in upstream.check_upstream(db)}
    assert "no_such_table: table missing or not visible to this role" in problems
    assert "metric_samples.no_such_column: column missing" in problems


def test_upstream_reads_only_in_contract_module():
    """A3: no module other than app/upstream.py names a HealthLog table or schema public."""
    names = [*upstream.CONTRACT, "public."]
    pattern = re.compile("|".join(re.escape(n) for n in names))
    offenders = [
        str(path.relative_to(COMPANION_DIR))
        for path in (COMPANION_DIR / "app").rglob("*.py")
        if path.name != "upstream.py" and pattern.search(path.read_text())
    ]
    assert offenders == []


@pytest.mark.skipif(shutil.which("git") is None, reason="git not available")
def test_branch_touches_only_allowlisted_paths():
    """A6 / R1: on companion branches, upstream-owned files stay untouched."""
    base = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", "upstream/main"], cwd=REPO_DIR, capture_output=True, text=True
    )
    if base.returncode != 0:
        pytest.skip("no upstream/main ref (add the upstream remote and fetch it)")
    result = subprocess.run(
        ["sh", str(COMPANION_DIR / "scripts" / "check_paths.sh"), "upstream/main"],
        cwd=REPO_DIR,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
