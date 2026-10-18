-- One-time database bootstrap for the Companion. Run as HealthLog's database
-- owner (the POSTGRES_USER superuser), e.g.:
--
--   docker exec -i healthlog-db psql -U healthlog -d healthlog \
--     -v companion_password="$COMPANION_DB_PASSWORD" < companion/bootstrap/bootstrap.sql
--
-- Idempotent: safe to re-run (it also resets the role's password).
--
-- What it sets up (design §8.3, risks.md A1/A4/A5):
--   * role `companion` (login), owner of schema `companion`;
--   * SELECT-only on HealthLog's schema `public`, including tables HealthLog
--     creates in future migrations (default privileges);
--   * pgvector inside schema `companion` (diary embeddings, milestone M8).
-- Nothing here creates an object that depends on `public` (R2).

SELECT set_config('companion.bootstrap_password', :'companion_password', false);

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'companion') THEN
        EXECUTE format('CREATE ROLE companion LOGIN PASSWORD %L', current_setting('companion.bootstrap_password'));
    ELSE
        EXECUTE format('ALTER ROLE companion LOGIN PASSWORD %L', current_setting('companion.bootstrap_password'));
    END IF;
END
$$;

SELECT set_config('companion.bootstrap_password', '', false);

CREATE SCHEMA IF NOT EXISTS companion AUTHORIZATION companion;
ALTER ROLE companion SET search_path = companion, public;

-- Read-only on HealthLog. No write privileges are granted anywhere in `public`.
GRANT USAGE ON SCHEMA public TO companion;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO companion;
REVOKE CREATE ON SCHEMA public FROM companion;

-- Tables HealthLog creates later (as this same owner role) become readable too.
DO $$
BEGIN
    EXECUTE format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public GRANT SELECT ON TABLES TO companion',
                   current_user);
END
$$;

CREATE EXTENSION IF NOT EXISTS vector SCHEMA companion;
