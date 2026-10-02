-- Canonical NEXUS PostgreSQL role provisioning.
--
-- Run by a database administrator, never by the application or the migration job.
-- It is idempotent: run it again after any change and it converges on the same state.
--
-- Roles (names can be overridden with the nexus.*_role settings below):
--   nexus_migrator  owns every schema object and runs Alembic. No superuser, no BYPASSRLS.
--   nexus_app       the runtime role. DML on tables and sequence use only. Owns nothing,
--                   so it cannot ALTER or DROP tables, triggers, policies or RLS, and it
--                   is bound by FORCE ROW LEVEL SECURITY.
--   nexus_system    cross-tenant maintenance. BYPASSRLS, DML only, owns nothing.
--
-- Inputs are session settings, so no secret appears in a command line or in this file:
--   nexus.migrator_password, nexus.app_password, nexus.system_password
--     required when the role does not exist yet; when the role exists, a value rotates
--     the password and no value leaves it unchanged.
--   nexus.migrator_role, nexus.app_role, nexus.system_role   optional role names.
--
-- Example, with the secrets in the environment and never in arguments:
--   PGOPTIONS="-c nexus.migrator_password=$M -c nexus.app_password=$A -c nexus.system_password=$S" \
--     psql -v ON_ERROR_STOP=1 -d nexus -f deploy/postgres/provision-roles.sql
--
-- The administrator must be a superuser, or on managed PostgreSQL a member of
-- nexus_migrator with CREATEROLE, so it can transfer schema public and set default
-- privileges for objects that nexus_migrator creates.

DO $provision$
DECLARE
    migrator text := coalesce(nullif(current_setting('nexus.migrator_role', true), ''), 'nexus_migrator');
    app text := coalesce(nullif(current_setting('nexus.app_role', true), ''), 'nexus_app');
    sys text := coalesce(nullif(current_setting('nexus.system_role', true), ''), 'nexus_system');
    spec record;
    pair record;
    grantee text;
    pw text;
BEGIN
    IF migrator = app OR migrator = sys OR app = sys THEN
        RAISE EXCEPTION 'the migrator, application and system roles must be three different roles';
    END IF;

    -- 1. Roles. Attributes are re-asserted on every run, so a drifted role is corrected.
    FOR spec IN
        SELECT * FROM (VALUES
            (migrator, 'migrator_password', 'NOBYPASSRLS'),
            (app, 'app_password', 'NOBYPASSRLS'),
            (sys, 'system_password', 'BYPASSRLS')
        ) AS t(role_name, setting, bypass)
    LOOP
        pw := nullif(current_setting('nexus.' || spec.setting, true), '');
        IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = spec.role_name) THEN
            IF pw IS NULL THEN
                RAISE EXCEPTION 'role % does not exist and nexus.% is not set', spec.role_name, spec.setting;
            END IF;
            EXECUTE format('CREATE ROLE %I LOGIN PASSWORD %L', spec.role_name, pw);
        ELSIF pw IS NOT NULL THEN
            EXECUTE format('ALTER ROLE %I PASSWORD %L', spec.role_name, pw);
        END IF;
        EXECUTE format(
            'ALTER ROLE %I WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION INHERIT %s',
            spec.role_name, spec.bypass
        );
    END LOOP;

    -- No role may reach another's privileges through membership.
    FOR pair IN
        SELECT g.rolname AS granted, m.rolname AS member
          FROM pg_auth_members am
          JOIN pg_roles g ON g.oid = am.roleid
          JOIN pg_roles m ON m.oid = am.member
         WHERE g.rolname IN (migrator, app, sys) AND m.rolname IN (migrator, app, sys)
    LOOP
        EXECUTE format('REVOKE %I FROM %I', pair.granted, pair.member);
    END LOOP;

    -- 2. Extension, created by the administrator so nexus_migrator needs no database-level
    --    privilege. Migration d5b1f7a3c210 only runs CREATE EXTENSION IF NOT EXISTS.
    CREATE EXTENSION IF NOT EXISTS vector;

    -- 3. Schema public: owned by the migrator, usable but not writable by the others.
    EXECUTE format('ALTER SCHEMA public OWNER TO %I', migrator);
    REVOKE CREATE ON SCHEMA public FROM PUBLIC;
    EXECUTE format('REVOKE CREATE ON SCHEMA public FROM %I, %I', app, sys);
    EXECUTE format('GRANT USAGE ON SCHEMA public TO %I, %I', app, sys);
    EXECUTE format(
        'REVOKE CREATE ON DATABASE %I FROM PUBLIC, %I, %I', current_database(), app, sys
    );

    -- 4. Objects the migrator creates from now on. This is what keeps a table that a later
    --    migration (or a downgrade and upgrade) recreates usable by the application, with
    --    nothing named after a role in any migration.
    FOREACH grantee IN ARRAY ARRAY[app, sys] LOOP
        EXECUTE format(
            'ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public '
            'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO %I', migrator, grantee
        );
        EXECUTE format(
            'ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public '
            'GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO %I', migrator, grantee
        );
        -- Objects that exist already (a database provisioned before this script).
        EXECUTE format(
            'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO %I', grantee
        );
        EXECUTE format(
            'GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public TO %I', grantee
        );
        EXECUTE format(
            'REVOKE TRUNCATE, REFERENCES, TRIGGER ON ALL TABLES IN SCHEMA public FROM %I', grantee
        );
        -- The migration version table is for the migrator alone (nexus.db_migrate seals it).
        IF to_regclass('public.alembic_version') IS NOT NULL THEN
            EXECUTE format('REVOKE ALL ON TABLE public.alembic_version FROM %I', grantee);
        END IF;
    END LOOP;
END
$provision$;
