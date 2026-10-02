-- Local development bootstrap for docker-compose.yml (WP-8, WP-16a).
--
-- The role model lives in deploy/postgres/provision-roles.sql, which docker-compose.yml
-- mounts at /opt/nexus-postgres. This file only supplies the throwaway local passwords
-- that docker-compose.yml also uses, then runs that script. It is for local development:
-- production provisioning supplies its own secrets (see docs/runbooks/database-roles.md).
--
-- Scripts in /docker-entrypoint-initdb.d execute only on a fresh data directory.
-- Existing volumes require `docker compose down -v` to re-initialize.

SELECT set_config('nexus.migrator_password', 'nexus_migrator_pass', false);
SELECT set_config('nexus.app_password', 'nexus_app_pass', false);
SELECT set_config('nexus.system_password', 'nexus_system_pass', false);

\i /opt/nexus-postgres/provision-roles.sql
