-- One-time database role for Grafana (compose.local.yml): read-only on HealthLog's tables.
-- Run as HealthLog's database owner, after bootstrap.sql, e.g.:
--
--   docker exec -i healthlog-db psql -U healthlog -d healthlog \
--     -v grafana_ro_password="$GRAFANA_RO_PASSWORD" < companion/bootstrap/grafana_ro.sql
--
-- Idempotent: safe to re-run (it also resets the role's password). The provisioned datasource
-- (grafana/provisioning) logs in as `grafana_ro` with GRAFANA_RO_PASSWORD. The same grants as
-- grafana/README.md: every dashboard, ours included, reads only HealthLog's schema `public`.

SELECT set_config('grafana_ro.bootstrap_password', :'grafana_ro_password', false);

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'grafana_ro') THEN
        EXECUTE format('CREATE ROLE grafana_ro LOGIN PASSWORD %L', current_setting('grafana_ro.bootstrap_password'));
    ELSE
        EXECUTE format('ALTER ROLE grafana_ro LOGIN PASSWORD %L', current_setting('grafana_ro.bootstrap_password'));
    END IF;
END
$$;

SELECT set_config('grafana_ro.bootstrap_password', '', false);

DO $$
BEGIN
    EXECUTE format('GRANT CONNECT ON DATABASE %I TO grafana_ro', current_database());
END
$$;

GRANT USAGE ON SCHEMA public TO grafana_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO grafana_ro;
DO $$
BEGIN
    EXECUTE format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public GRANT SELECT ON TABLES TO grafana_ro',
                   current_user);
END
$$;
